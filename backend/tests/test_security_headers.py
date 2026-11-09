"""Every response carries the security headers (app/security_headers.py)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_api_response_has_security_headers():
    r = client.get("/health")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "max-age=" in r.headers["strict-transport-security"]
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_error_responses_have_them_too():
    r = client.get("/trace/not-a-case")
    assert r.status_code == 404
    assert r.headers["x-frame-options"] == "DENY"


def test_docs_page_skips_the_page_policy():
    # Swagger UI loads from a CDN; it gets the other headers, not the CSP.
    r = client.get("/docs")
    if r.status_code == 200:  # disabled when EXCHEQUER_API_DOCS=0
        assert "content-security-policy" not in r.headers
        assert r.headers["x-content-type-options"] == "nosniff"


def test_oversized_bodies_are_refused():
    big = b"x" * 2_200_000
    r = client.post("/batches", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413
    # Streamed without a length: refused once it crosses the limit.
    def chunks():
        for _ in range(30):
            yield b"y" * 100_000
    r = client.post("/verify", content=chunks())
    assert r.status_code == 413
    # Normal bodies pass.
    assert client.post("/verify", content=b"hello").status_code == 200


def test_the_policy_trusts_no_other_origin():
    # The fonts are served from the app itself (R27): no Google, no CDN.
    csp = client.get("/health").headers["content-security-policy"]
    assert "https://" not in csp and "http://" not in csp
    assert "font-src 'self';" in csp + ";"


def test_ordinary_routes_take_a_much_smaller_body():
    # Only /verify takes a whole report; every JSON route used to accept the
    # same 2 MB, parsed and validated on the event loop.
    from app.security_headers import DEFAULT_MAX_BODY, LARGE_BODY_ROUTES
    assert DEFAULT_MAX_BODY <= 256_000 and LARGE_BODY_ROUTES == {"/verify": 2_100_000}
    just_over = b"x" * (DEFAULT_MAX_BODY + 1)
    for path in ("/batches", "/requests", "/watches", "/trace", "/alerts/read"):
        r = client.post(path, content=just_over, headers={"content-type": "application/json"})
        assert r.status_code == 413, path

    def chunks():  # streamed, no length
        for _ in range(3):
            yield b"y" * 100_000
    assert client.post("/batches", content=chunks(), headers={"content-type": "application/json"}).status_code == 413
    # A report of 1 MB is still checked.
    assert client.post("/verify", content=b"z" * 1_000_000).status_code == 200


# -- caching: case data never lands in a shared cache or a shared PC's disk cache --------
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import PlainTextResponse  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app import config, models  # noqa: E402
from app.routes import cases  # noqa: E402
from app.security_headers import SecurityHeadersMiddleware  # noqa: E402

NAVIGATE = {"sec-fetch-mode": "navigate", "accept": "text/html"}
FETCH = {"sec-fetch-mode": "cors"}


@pytest.fixture
def stored_case(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'h.db'}", future=True))
    models.init_db()
    models.save_case("hdr-case", "0x" + "1" * 40, {"address": "0x" + "1" * 40})
    return "hdr-case"


def _vary(response) -> set[str]:
    return {v.strip().lower() for v in response.headers.get("vary", "").split(",") if v.strip()}


def test_case_json_is_never_stored_and_varies_on_how_it_was_asked(stored_case):
    r = client.get(f"/trace/{stored_case}", headers={**FETCH, "origin": "http://localhost:5173"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    assert r.headers["cache-control"] == "no-store"
    assert {"sec-fetch-mode", "accept", "origin"} <= _vary(r)


def test_the_page_for_the_same_url_keeps_its_own_cache_rule_and_varies_too(stored_case, monkeypatch, tmp_path):
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><title>app</title>")
    monkeypatch.setattr(cases, "_INDEX_HTML", index)
    r = client.get(f"/trace/{stored_case}", headers=NAVIGATE)
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert {"sec-fetch-mode", "accept"} <= _vary(r)


@pytest.mark.parametrize("path", ["/health", "/cases", "/trace/no-such-case", "/no/such/api"])
def test_api_answers_and_errors_are_not_stored(path):
    assert client.get(path, headers=FETCH).headers["cache-control"] == "no-store"


def test_hashed_assets_keep_their_caching():
    tiny = FastAPI()
    tiny.add_middleware(SecurityHeadersMiddleware)

    @tiny.get("/assets/x.js")
    def asset():
        return PlainTextResponse("x", headers={"cache-control": "public, max-age=31536000, immutable"})

    @tiny.get("/assets/y.js")
    def bare():
        return PlainTextResponse("y")

    with TestClient(tiny) as c:
        assert c.get("/assets/x.js").headers["cache-control"] == "public, max-age=31536000, immutable"
        assert "cache-control" not in c.get("/assets/y.js").headers


# -- no WebSocket protocol: an upgrade never reaches a route past the middlewares ---------
@pytest.mark.parametrize("code", ["", "a-demo-code-long-enough-1"])
@pytest.mark.parametrize("path", ["/trace", "/trace/jobs", "/health"])
def test_a_websocket_upgrade_is_refused_before_any_route(monkeypatch, code, path):
    monkeypatch.setattr(config, "DEMO_CODE", code)
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(path):
            pass
    assert refused.value.code == 1008


def test_the_server_runs_no_websocket_stack_and_sends_no_banner():
    root = config.BACKEND_DIR.parent
    entrypoint = (root / "docker-entrypoint.sh").read_text()
    assert "--ws none" in entrypoint and "--no-server-header" in entrypoint
    requirements = (config.BACKEND_DIR / "requirements.txt").read_text()
    assert "uvicorn[standard]" not in requirements
    assert any(line.startswith("uvicorn==") for line in requirements.splitlines())
