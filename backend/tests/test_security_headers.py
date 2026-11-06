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
