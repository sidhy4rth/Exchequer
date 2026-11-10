"""CI, on Postgres after `alembic upgrade head`: the citizen role
(citizen/api/citizen_role.sql) can do what the citizen functions do -- send
a complaint, sign in, read it back, reply, sign out -- and nothing else.

Usage: DATABASE_URL=postgresql://owner@host/db python scripts/check_citizen_role.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import errors

REPO = Path(__file__).resolve().parents[2]
API = REPO / "citizen" / "api"
PASSWORD = "ci-only-citizen-password"
REFUSED = [
    "SELECT id FROM cases", "SELECT id FROM watches", "SELECT version_num FROM alembic_version",
    "INSERT INTO cases (id, address, created_at, result_json) VALUES ('x', 'x', 't', '{}')",
    "DELETE FROM complaints", "DELETE FROM citizen_sessions", "UPDATE complaints SET status = 'closed'",
    "UPDATE tracking_codes SET code_hash = 'x'", "TRUNCATE citizen_attempts", "CREATE TABLE ci_probe (i int)",
]


def flow(url: str) -> None:
    """The citizen functions themselves, end to end, on `url`."""
    os.environ.update(CITIZEN_DATABASE_URL=url, CITIZEN_SECRET="ci-" + "s" * 40)
    if str(API) not in sys.path:
        sys.path.insert(0, str(API))
    from _lib import db, routes, web

    def call(route, method="POST", body=b"", cookie=""):
        headers = {"x-citizen": "1", "content-type": "application/json", "host": "ci", "cookie": cookie}
        return web.dispatch(web.Endpoint(route, (method,), 24_576),
                            web.Request(method, "/", "", headers, body, "192.0.2.1"))

    pay = b'"payments": [{"wallet": "TJ' + b"a" * 32 + b'", "network": "Tron (TRC20)"}]'
    sent = [call(routes.complaints, body=b'{"ncrp": "%s", "story": "ci", %s}' % (n, pay)) for n in
            (b"31234567890123", b"39999999999999")]
    assert all(r.status == 201 for r in sent), [r.body for r in sent]
    code = sent[0].body["tracking_code"].encode()
    assert call(routes.session, body=b'{"ncrp": "31234567890123", "code": "2222-2222-2222"}').status == 401
    signed = call(routes.session, body=b'{"ncrp": "31234567890123", "code": "%s"}' % code)
    assert signed.status == 200, signed.body
    cookie = signed.cookies[0].split(";")[0]
    assert call(routes.messages, body=b'{"body": "hello"}', cookie=cookie).status == 201
    case = call(routes.my_case, "GET", cookie=cookie)
    assert case.status == 200 and case.body["messages"][0]["body"] == "hello", case.body
    assert "wallet_match" not in str(case.body)
    assert call(routes.logout, cookie=cookie).status == 200
    assert call(routes.my_case, "GET", cookie=cookie).status == 401
    with db.connect() as conn:
        flags = [r["wallet_match"] for r in conn.all("SELECT wallet_match FROM complaints")]
    assert flags == ["complaint", "complaint"], flags


def main() -> int:
    owner = os.environ["DATABASE_URL"]
    with psycopg.connect(owner, autocommit=True) as conn:
        conn.execute((API / "citizen_role.sql").read_text())
        conn.execute(f"ALTER ROLE exchequer_citizen PASSWORD '{PASSWORD}'")
    parts = urlsplit(owner)
    citizen = urlunsplit(parts._replace(netloc=f"exchequer_citizen:{PASSWORD}@{parts.hostname}:{parts.port or 5432}"))
    flow(citizen)
    with psycopg.connect(citizen, autocommit=True) as conn:
        for statement in REFUSED:
            try:
                conn.execute(statement)
            except errors.InsufficientPrivilege:
                continue
            raise AssertionError(f"the citizen role may run: {statement}")
    print(f"citizen role: the full flow works and {len(REFUSED)} other statements are refused")
    return 0


if __name__ == "__main__":
    sys.exit(main())
