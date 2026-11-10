"""The Vercel side: each file in citizen/api/ is a function with a `handler`;
answers carry no stack trace and no cache; tests and shared code are never
deployed as functions; the dependency file is pinned with hashes."""
from __future__ import annotations

import io
import json
from pathlib import Path

from conftest import API, CLIENT, NCRP, endpoint, pack

from _lib import web

ENDPOINTS = {"complaints": ("POST",), "session": ("POST",), "my-case": ("GET",), "messages": ("POST",),
             "logout": ("POST",), "payment": ("GET",)}


class Sock:
    def __init__(self, data: bytes):
        self.data, self.out = data, bytearray()

    def makefile(self, mode, *_a, **_k):
        return io.BytesIO(self.data)

    def sendall(self, chunk):
        self.out += chunk


def raw(name: str, request: bytes) -> tuple[str, dict, dict]:
    sock = Sock(request)
    endpoint(name).handler(sock, (CLIENT, 4000), None)
    head, _, body = bytes(sock.out).partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    headers: dict = {}
    for line in lines[1:]:
        k, _, v = line.partition(": ")
        headers.setdefault(k.lower(), []).append(v)
    return lines[0], headers, json.loads(body or b"null")


def post(path: str, body: dict, extra: str = "") -> bytes:
    data = json.dumps(body).encode()
    return (f"POST /api/{path} HTTP/1.1\r\nHost: citizen.example\r\nContent-Type: application/json\r\n"
            f"X-Citizen: 1\r\nContent-Length: {len(data)}\r\n{extra}\r\n").encode() + data


def test_every_endpoint_file_is_a_function_for_its_methods():
    files = {p.stem for p in API.glob("*.py")}
    assert files == set(ENDPOINTS)
    for name, methods in ENDPOINTS.items():
        module = endpoint(name)
        assert module.ENDPOINT.methods == methods and issubclass(module.handler, web.BaseHTTPRequestHandler)


def test_a_complaint_and_sign_in_through_the_real_handler(db):
    status, headers, body = raw("complaints", post("complaints", pack()))
    assert status.startswith("HTTP/1.1 201") or status.startswith("HTTP/1.0 201")
    assert headers["cache-control"] == ["no-store"] and headers["x-content-type-options"] == ["nosniff"]
    assert headers["content-type"][0].startswith("application/json")
    status, headers, _ = raw("session", post("session", {"ncrp": NCRP, "code": body["tracking_code"]}))
    assert " 200" in status
    [cookie] = headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Strict" in cookie


def test_a_crash_answers_plainly_with_no_stack_trace(db, monkeypatch):
    def boom(_req):
        raise RuntimeError("secret detail /var/task/_lib/db.py line 9")
    module = endpoint("complaints")
    monkeypatch.setattr(module.ENDPOINT, "route", boom)
    sock = Sock(post("complaints", pack()))
    module.handler(sock, (CLIENT, 4000), None)
    out = bytes(sock.out).decode()
    assert " 500" in out.split("\r\n")[0]
    assert "secret detail" not in out and "Traceback" not in out and "RuntimeError" not in out
    assert "Something went wrong" in out


def test_a_body_without_a_length_or_over_the_cap_is_not_read(db):
    no_length = b"POST /api/complaints HTTP/1.1\r\nHost: h\r\nX-Citizen: 1\r\nContent-Type: application/json\r\n\r\n{}"
    assert " 411" in raw("complaints", no_length)[0]
    huge = (b"POST /api/messages HTTP/1.1\r\nHost: h\r\nX-Citizen: 1\r\nContent-Type: application/json\r\n"
            b"Content-Length: 99999999\r\n\r\n{}")
    assert " 413" in raw("messages", huge)[0]


def test_the_client_is_the_address_vercel_saw():
    req = web.Request("GET", "/", "", {"x-real-ip": "198.51.100.1", "x-forwarded-for": "203.0.113.5, 10.0.0.1"},
                      b"", "10.0.0.2")
    assert web.client_ip(req) == "198.51.100.1"
    req.headers.pop("x-real-ip")
    assert web.client_ip(req) == "203.0.113.5"
    req.headers.pop("x-forwarded-for")
    assert web.client_ip(req) == "10.0.0.2"


def test_an_ipv6_client_is_counted_by_its_64_block():
    def ip(addr):
        return web.client_ip(web.Request("GET", "/", "", {"x-real-ip": addr}, b"", "10.0.0.2"))
    a, b = ip("2405:201:a:b:1111:2222:3333:4444"), ip("2405:201:a:b:ffff:eeee:dddd:cccc")
    assert a == b == "2405:201:a:b::/64"
    assert ip("2405:201:a:c::1") != a
    assert ip("198.51.100.1") == "198.51.100.1"
    assert ip("::ffff:198.51.100.1") == "198.51.100.1"
    assert ip("not an address") == "not an address"


def test_tests_and_shared_code_are_never_deployed_as_functions():
    ignored = (API.parent / ".vercelignore").read_text().split()
    assert "api/tests" in ignored
    assert all(p.name.startswith("_") for p in API.iterdir() if p.is_dir() and p.name not in ("tests", "__pycache__") and not p.name.startswith("."))
    config = json.loads((API.parent / "vercel.json").read_text())
    [rewrite] = config["rewrites"]
    assert rewrite["source"].startswith("/((?!api/)")
    assert config["regions"] == ["sin1"]


def test_the_dependencies_are_psycopg_alone_pinned_with_hashes():
    lines = (API / "requirements.txt").read_text().splitlines()
    pins = [line.split("==")[0] for line in lines if line and not line.startswith((" ", "#"))]
    assert pins == ["psycopg", "psycopg-binary", "typing-extensions", "tzdata"]
    backend = (API.parents[1] / "backend" / "requirements.txt").read_text()
    for line in lines:
        if "--hash=" in line:
            assert line.strip().rstrip(" \\") in backend
    assert sum("--hash=sha256:" in line for line in lines) >= 4


def test_the_deploy_doc_carries_the_exact_role_sql():
    sql = (API / "citizen_role.sql").read_text()
    doc = (API.parents[1] / "docs" / "citizen-deploy.md").read_text()
    assert sql.strip() in doc
    grants = [line for line in sql.splitlines() if line.upper().startswith("GRANT")]
    tables = {"complaints", "complaint_payments", "complaint_messages", "tracking_codes", "citizen_sessions",
              "citizen_attempts"}
    for line in grants:
        upper = line.upper()
        privileges = {w.strip(",") for w in upper.split(" ON ")[0].split("(")[0].split()[1:]}
        assert privileges <= {"SELECT", "INSERT", "UPDATE", "USAGE"}, line
        if " ON " in upper and "SCHEMA" not in upper:
            named = {t.strip(" ,;").lower() for t in line.split(" ON ", 1)[1].split(" TO ")[0].split(",")}
            named = {t.removeprefix("table ").strip() for t in named}
            assert named <= tables, line
    assert "cases" not in {w.strip(",;").lower() for w in " ".join(grants).split()}


def test_no_file_here_reads_a_key_or_an_e_mail_or_sms_service():
    text = "\n".join(p.read_text() for p in API.rglob("*.py") if "tests" not in p.parts)
    for word in ("API_KEY", "apikey", "TRON-PRO-API-KEY", "smtp", "twilio", "sendgrid"):
        assert word.lower() not in text.lower()
    assert Path(API / "_lib").is_dir()


def test_every_function_file_defines_a_top_level_handler_class():
    """Vercel finds a Python function by reading the file for a top-level
    `class handler(...)` (or `app`). A `handler = ...` assignment works when
    imported, but Vercel's scan skips the file, and the deploy then fails with
    "The pattern api/*.py doesn't match any Serverless Functions"."""
    import ast
    import pathlib
    api = pathlib.Path(__file__).resolve().parent.parent
    files = sorted(p for p in api.glob("*.py") if not p.name.startswith("_"))
    assert files, "no function files found"
    for path in files:
        tree = ast.parse(path.read_text())
        classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        assert "handler" in classes, f"{path.name} has no top-level `class handler`"
