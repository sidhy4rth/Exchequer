"""The app's catch-all route (main.py): a browser opening a page gets the app;
anything else asking for a path the API does not have gets a JSON 404.

Before R33c every unknown path answered 200 with the app's HTML, so a
mistyped API call (or the dev build's /api prefix) failed as "backend
unreachable" or as a JSON parse error, never as what it was.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main

NAVIGATE = {"sec-fetch-mode": "navigate", "accept": "text/html,application/xhtml+xml"}
FETCH = {"sec-fetch-mode": "cors", "accept": "*/*"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "favicon.svg").write_text("<svg/>")
    monkeypatch.setattr(main, "FRONTEND_DIR", dist)
    return TestClient(main.app)


@pytest.mark.parametrize("path", ["/", "/case/abc", "/signin/investigator", "/demo/3", "/anything/at/all"])
def test_a_browser_opening_a_page_gets_the_app(client, path):
    response = client.get(path, headers=NAVIGATE)
    assert response.status_code == 200 and "<div id=root>" in response.text
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("path", ["/chainz", "/api/chains", "/cases/nope/x", "/admin/whatever"])
def test_a_fetch_for_a_path_the_api_does_not_have_gets_a_json_404(client, path):
    response = client.get(path, headers=FETCH)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Not Found"}


def test_a_script_without_browser_headers_gets_the_404_too(client):
    response = client.get("/chainz")
    assert response.status_code == 404 and "<div id=root>" not in response.text


def test_a_real_file_is_still_served(client):
    assert client.get("/favicon.svg").text == "<svg/>"


def test_nothing_outside_the_app_folder_is_served(client):
    response = client.get("/..%2F..%2Fetc%2Fpasswd", headers=NAVIGATE)
    assert "root:" not in response.text


def test_the_api_itself_is_untouched(client):
    assert client.get("/health", headers=NAVIGATE).json()["status"] == "ok"


def test_without_a_built_app_every_unknown_path_is_a_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path / "missing")
    assert client.get("/case/abc", headers=NAVIGATE).status_code == 404
