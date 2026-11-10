"""The citizen tables (backend/app/complaints.py; the main app's migrations
own them), on Postgres as the citizen role (CITIZEN_DATABASE_URL), or on a
SQLite file (sqlite:///path) for local runs and tests.

SQL here is written once, with ? placeholders, in SQL both databases take.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator


class Unavailable(Exception):
    """No database is set up, or it cannot be reached."""


class DB:
    def __init__(self, conn: Any, postgres: bool):
        self.conn, self.postgres = conn, postgres

    def _run(self, sql: str, params: tuple):
        cur = self.conn.cursor()
        cur.execute(sql.replace("?", "%s") if self.postgres else sql, params)
        return cur

    def all(self, sql: str, *params: Any) -> list[dict]:
        cur = self._run(sql, params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]

    def one(self, sql: str, *params: Any) -> dict | None:
        rows = self.all(sql, *params)
        return rows[0] if rows else None

    def run(self, sql: str, *params: Any) -> int:
        return self._run(sql, params).rowcount


def ipv4_hostaddr(url: str, resolve: Any = None) -> dict:
    """{"hostaddr": <IPv4>} for the URL's host, or {} (see the main app's
    models.prefer_ipv4): a host that answers IPv6 first must not leave the
    functions unable to connect. CITIZEN_DB_PREFER_IPV4=0 turns it off."""
    import ipaddress
    import socket
    if os.environ.get("CITIZEN_DB_PREFER_IPV4", "1").strip() == "0":
        return {}
    from psycopg.conninfo import conninfo_to_dict
    try:
        info = conninfo_to_dict(url)
    except Exception:  # noqa: BLE001 -- a URL the driver will reject anyway
        return {}
    host = str(info.get("host") or "")
    if info.get("hostaddr") or not host or "," in host or host.startswith("/"):
        return {}
    try:
        ipaddress.ip_address(host)
        return {}
    except ValueError:
        pass
    try:
        infos = (resolve or socket.getaddrinfo)(host, int(info.get("port") or 5432), socket.AF_INET, socket.SOCK_STREAM)
    except (OSError, ValueError):
        return {}
    return {"hostaddr": infos[0][4][0]} if infos else {}


@contextmanager
def connect() -> Iterator[DB]:
    """One transaction: committed when the block ends, rolled back on an error."""
    url = os.environ.get("CITIZEN_DATABASE_URL", "").strip()
    try:
        if url.startswith("sqlite:///"):
            conn, postgres = sqlite3.connect(url[len("sqlite:///"):], timeout=10), False
        elif url.startswith(("postgres://", "postgresql://")):
            import psycopg
            # No prepared statements: Neon's pooled address runs PgBouncer.
            conn, postgres = psycopg.connect(url, connect_timeout=5, prepare_threshold=None,
                                              **ipv4_hostaddr(url)), True
        else:
            raise Unavailable("CITIZEN_DATABASE_URL is not set")
    except Unavailable:
        raise
    except Exception as exc:  # the driver's own errors name the host; keep only the kind
        raise Unavailable(type(exc).__name__) from None
    try:
        yield DB(conn, postgres)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
