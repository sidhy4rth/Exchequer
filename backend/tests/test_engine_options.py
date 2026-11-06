"""The Postgres engine fails fast and keeps its pool bounded (models.py), and
/health never waits for a worker thread (routes/coverage.py).

A slow or unreachable Neon used to hang each connect for the TCP retry period,
and a pool of 15 shared by 40 request threads made every later request wait
30 s; once the threads were all blocked, even /health stopped answering and
the host restarted the instance."""
from __future__ import annotations

import inspect

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import exc

from app import config, models
from app.main import app
from app.routes import coverage


def test_postgres_engine_fails_fast_and_bounds_its_pool(monkeypatch):
    seen = {}

    def spy(url, **kwargs):
        seen.update(url=url, **kwargs)
        return object()
    monkeypatch.setattr(config, "DATABASE_URL", "postgres://u:p@localhost/x")
    monkeypatch.setattr(models, "create_engine", spy)
    models._make_engine()
    assert seen["url"].startswith("postgresql+psycopg://")
    assert seen["connect_args"]["connect_timeout"] == 5
    assert seen["pool_timeout"] == 10
    assert seen["pool_size"] == 5 and seen["max_overflow"] == 5
    assert seen["pool_pre_ping"] is True and seen["pool_recycle"] == 300


def test_health_never_needs_a_worker_thread():
    assert inspect.iscoroutinefunction(coverage.health)


@pytest.fixture
def busy_pool_route():
    router = APIRouter()

    @router.get("/__test/busy-pool")
    def busy() -> dict:
        raise exc.TimeoutError("QueuePool limit of size 5 overflow 5 reached")
    # Ahead of the app's catch-all page route, which would answer it first.
    app.router.routes.insert(0, router.routes[0])
    yield "/__test/busy-pool"
    app.router.routes.remove(router.routes[0])


def test_an_exhausted_pool_is_a_503_not_a_500(busy_pool_route):
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get(busy_pool_route)
    assert r.status_code == 503 and r.headers["retry-after"]
