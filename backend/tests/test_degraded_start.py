"""The site starts without its database (main.py lifespan).

The lifespan ran the schema upgrade and a batch clean-up against the case
store with no fallback, so a database outage at boot (a suspended free-tier
Neon, a network failure) took down everything at the next wake -- the UI,
/health, the recorded demos, /verify -- none of which needs the store. Now a
store that cannot be reached is retried briefly, the site starts anyway, the
store's routes answer 503, and a background retry brings the store back.
"""
from __future__ import annotations

import threading

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
    # The lifespan hands the store to a background retry thread that runs
    # until the store opens. Started here, it outlived this test: it woke up
    # during later tests and ran the schema upgrade on the store they had
    # just set up, at the same moment they did. Alembic keeps one migration
    # context per process, so two upgrades at once fail (KeyError: 'script')
    # or run on each other's connection. Record that the retry is scheduled
    # instead; test_the_background_retry_opens_the_store runs the loop itself.
    retries: list[bool] = []
    monkeypatch.setattr(main, "_retry_store_in_background", lambda: retries.append(True))
    return retries


def test_the_site_starts_and_serves_what_needs_no_store(unreachable):
    with TestClient(app := main.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/signing-key").status_code == 200
        assert client.post("/verify", content=b"not a report").status_code == 200
        assert client.get("/demos/recorded").status_code == 200
        r = client.get("/cases")
        assert r.status_code == 503 and "case store" in r.json()["detail"].lower()
    assert app is main.app
    assert unreachable == [True]  # the store is retried in the background


def test_the_background_retry_opens_the_store(monkeypatch):
    attempts: list[threading.Thread] = []
    back = threading.Event()

    def open_store():
        attempts.append(threading.current_thread())
        if len(attempts) == 2:  # down once, then back
            back.set()
            return True
        return False
    monkeypatch.setattr(main, "_open_store", open_store)
    monkeypatch.setattr(main, "DB_RETRY_SECONDS", 0.0)
    main._retry_store_in_background()
    assert back.wait(timeout=5)
    retry = attempts[0]
    retry.join(timeout=5)
    assert retry.name == "store-retry" and not retry.is_alive() and len(attempts) == 2


def test_a_failing_batch_clean_up_does_not_stop_the_start(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))

    def boom():
        raise RuntimeError("write refused")
    monkeypatch.setattr(batches, "mark_interrupted", boom)
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/cases").status_code == 200
