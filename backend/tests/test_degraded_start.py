"""The site starts without its database (main.py lifespan).

The lifespan ran the schema upgrade and a batch clean-up against the case
store with no fallback, so a database outage at boot (a suspended free-tier
Neon, a network failure) took down everything at the next wake -- the UI,
/health, the recorded demos, /verify -- none of which needs the store. Now a
store that cannot be reached is retried briefly, the site starts anyway, the
store's routes answer 503, and a background retry brings the store back.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import batches, main, models


@pytest.fixture
def unreachable(monkeypatch):
    # Nothing listens on port 1: connections are refused at once, no network used.
    monkeypatch.setattr(models, "_engine", create_engine("postgresql+psycopg://u:p@127.0.0.1:1/db", future=True))
    monkeypatch.setattr(main, "DB_STARTUP_DELAYS", (0.0, 0.0))
    monkeypatch.setattr(main, "DB_RETRY_SECONDS", 3600.0)


def test_the_site_starts_and_serves_what_needs_no_store(unreachable):
    with TestClient(app := main.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/signing-key").status_code == 200
        assert client.post("/verify", content=b"not a report").status_code == 200
        assert client.get("/demos/recorded").status_code == 200
        r = client.get("/cases")
        assert r.status_code == 503 and "case store" in r.json()["detail"].lower()
    assert app is main.app


def test_a_failing_batch_clean_up_does_not_stop_the_start(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))

    def boom():
        raise RuntimeError("write refused")
    monkeypatch.setattr(batches, "mark_interrupted", boom)
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/cases").status_code == 200
