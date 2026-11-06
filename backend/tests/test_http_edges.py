"""Edge cases at the HTTP layer that used to answer 405 or 500.

- HEAD /health and HEAD / were 405, so HEAD-based uptime monitors and
  keep-awake pingers reported the site down.
- A NaN or Infinity anywhere in a JSON body turned the 422 validation reply
  into a 500 (the reply echoed the value, and JSON cannot hold it), and a
  NaN amount_frozen was stored.
- An over-long path segment or a NUL byte made the SPA fallback raise: a 500
  with a traceback and no security headers.
- The page policy (CSP) was dropped for any path starting /docs or /redoc,
  even with the API docs switched off and the app served there.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import config, models, ownership
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'h.db'}", future=True))
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    return TestClient(app, raise_server_exceptions=False)


def test_head_requests_answer_like_get(client):
    assert client.head("/health").status_code == 200
    assert client.head("/").status_code != 405


def test_a_nan_in_a_body_is_a_422_not_a_500(client):
    r = client.post("/requests", content=b'{"case_id": NaN, "recipient": "Binance"}',
                    headers={"content-type": "application/json", ownership.OWNER_HEADER: "o" * 32})
    assert r.status_code == 422
    assert "NaN" not in r.text  # the reply describes the problem, never echoes the input


def test_a_nan_amount_is_refused_not_stored(client):
    h = {"content-type": "application/json", ownership.OWNER_HEADER: "o" * 32}
    rid = client.post("/requests", json={"case_id": "case-1", "recipient": "Binance"}, headers=h).json()["request_id"]
    r = client.patch(f"/requests/{rid}", content=b'{"amount_frozen": NaN}', headers=h)
    assert r.status_code == 422
    assert client.get("/requests", headers=h).status_code == 200


@pytest.mark.parametrize("built", [False, True])
@pytest.mark.parametrize("path", ["/" + "a" * 300, "/x%00y"])
def test_odd_paths_never_fail_and_keep_the_security_headers(client, monkeypatch, tmp_path, path, built):
    # An over-long segment or a NUL byte used to raise in the file lookup: a
    # 500 with a traceback and no security headers. Without a built frontend
    # it is a 404; with one, a browser gets the app shell like any deep link.
    # The build folder is set here so a local frontend/dist cannot change it.
    from app import main
    if built:
        (tmp_path / "index.html").write_text("<!doctype html><title>x</title>")
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path)
    r = client.get(path, headers={"sec-fetch-mode": "navigate"})
    assert r.status_code == (200 if built else 404)
    assert "x-content-type-options" in r.headers


def test_the_page_policy_stays_on_docs_like_paths_when_docs_are_off(client, monkeypatch):
    monkeypatch.setattr(config, "API_DOCS_ENABLED", False)
    for path in ("/docs", "/docsfoo", "/redoc/x"):
        assert "content-security-policy" in client.get(path).headers, path
