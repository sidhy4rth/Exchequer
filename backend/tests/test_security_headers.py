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
