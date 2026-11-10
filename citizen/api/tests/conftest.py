"""The citizen functions under test, on a throwaway SQLite file migrated by
the main app's own migrations (backend/migrations): the schema they write is
the one the officer side reads. Nothing here touches the network."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import urllib.request
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
for path in (API, REPO / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _lib import web  # noqa: E402

SECRET = "test-secret-" + "s" * 40
NCRP = "31234567890123"
CLIENT = "203.0.113.7"


@pytest.fixture(scope="session")
def migrated(tmp_path_factory) -> Path:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    path = tmp_path_factory.mktemp("schema") / "citizen.db"
    engine = create_engine(f"sqlite:///{path}", future=True)
    settings = Config(str(REPO / "backend" / "alembic.ini"))
    with engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.upgrade(settings, "head")
    engine.dispose()
    return path


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("a test tried to reach the network")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def db(migrated, tmp_path, monkeypatch) -> Path:
    path = tmp_path / "citizen.db"
    shutil.copy(migrated, path)
    monkeypatch.setenv("CITIZEN_DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setenv("CITIZEN_SECRET", SECRET)
    return path


def endpoint(name: str):
    """An endpoint file (citizen/api/<name>.py), loaded the way Vercel loads it: by path."""
    spec = importlib.util.spec_from_file_location(f"citizen_api_{name.replace('-', '_')}", API / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(name: str, method: str = "POST", body=None, *, query: str = "", cookie: str | None = None,
         headers: dict | None = None, client: str = CLIENT, raw: bytes | None = None) -> web.Response:
    sent = {"x-citizen": "1", "content-type": "application/json", "host": "citizen.example"}
    if cookie:
        sent["cookie"] = cookie
    sent.update({k.lower(): v for k, v in (headers or {}).items()})
    sent = {k: v for k, v in sent.items() if v is not None}
    data = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
    req = web.Request(method=method, path=f"/api/{name}", query=query, headers=sent, body=data,
                      client=client)
    return web.dispatch(endpoint(name).ENDPOINT, req)


def pack(**extra) -> dict:
    body = {
        "ncrp": NCRP, "name": "A. Citizen", "mobile": "9876543210", "started": "2026-11-01",
        "app": "QuickTrade Pro", "link": "https://quicktrade.example", "contacts": "@trader on Telegram",
        "upi": "", "story": "They said my money would double.",
        "payments": [{"hash": "ab" * 32, "amount": "9,890.50", "token": "USDT", "network": "Tron (TRC20)",
                      "paidAt": "2026-11-02 14:05", "wallet": "TJ" + "a" * 32}],
    }
    body.update(extra)
    return body


def submit(**extra) -> dict:
    res = call("complaints", body=pack(**extra))
    assert res.status == 201, res.body
    return res.body


def sign_in(ncrp: str, code: str, client: str = CLIENT) -> str:
    res = call("session", body={"ncrp": ncrp, "code": code}, client=client)
    assert res.status == 200, res.body
    return res.cookies[0].split(";")[0]
