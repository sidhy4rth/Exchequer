"""Listing the cases never reads their stored results (routes/casebook.py
GET /cases, models.list_summaries; r2-g2-postgres-prod-divergence-6-0).

GET /cases needs no code, and read the whole stored result of every visible
case, uncached, from a database whose transfer is metered: on a store holding
each of 13 demos three times at 150 KB, one anonymous request pulled about
5.85 MB to list 13 rows (8 Nov check). Each case now stores the summary the
list shows; demo copies are told apart in SQL; the answer for a caller with
no owner key is kept for a short while; and a connection may list only so
many times a minute.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text

from app import models, ownership
from app.main import app
from app.routes import casebook

PAD = "x" * 150_000
ALICE = "alice-key-" + "a" * 22


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'l.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute",
                 lambda conn, cursor, stmt, *a: statements.append(stmt))
    with TestClient(app) as c:
        c.statements = statements
        yield c


def seed_demos(copies=3):
    demos = sorted(ownership.demo_addresses())
    for k in range(copies):
        for i, a in enumerate(demos):
            models.save_case(f"d{k}-{i:02d}", a, {"chain": "ethereum", "address": a, "pad": PAD,
                                                   "exchange": "Binance", "graph": {"nodes": [{"id": a}]}},
                             created_at=f"2026-11-0{k + 1}T00:00:{i:02d}+00:00")
    return demos


def reads_results(statements) -> bool:
    return any("result_json" in s and s.lstrip().upper().startswith("SELECT") for s in statements)


def test_the_list_reads_no_stored_result(store):
    demos = seed_demos()
    store.statements.clear()
    body = store.get("/cases?limit=500").json()
    assert body["count"] == len(demos)
    assert not reads_results(store.statements)
    # The newest copy of each demo, with what the list always showed.
    assert all(c["case_id"].startswith("d2-") and c["demo"] for c in body["cases"])
    assert {c["exchange"] for c in body["cases"]} == {"Binance"}
    assert all(c["node_count"] == 1 and c["chain"] == "ethereum" for c in body["cases"])


def test_the_anonymous_list_is_kept_for_a_while(store):
    seed_demos(1)
    store.get("/cases?limit=500")
    store.statements.clear()
    for _ in range(20):
        assert store.get("/cases?limit=500").status_code == 200
    assert store.statements == []  # answered from the kept list
    models.save_case("new", "0x" + "1" * 40, {"address": "0x" + "1" * 40}, owner_hash="h" * 64)
    store.get("/cases?limit=500")
    assert store.statements  # a save changes the store: read again


def test_a_connection_may_list_only_so_often(store, monkeypatch):
    monkeypatch.setattr(casebook, "case_lists", casebook.rate_limit.SlidingWindowLimiter(5, 60))
    codes = [store.get("/cases", headers={ownership.OWNER_HEADER: ALICE}).status_code for _ in range(7)]
    assert codes == [200] * 5 + [429, 429]


def test_an_owners_list_is_their_own_cases_and_the_demos(store):
    demos = seed_demos(1)
    mine = "0x" + "2" * 40
    models.save_case("mine", mine, {"address": mine, "direction": "incoming"},
                     owner_hash=ownership.owner_hash(ALICE))
    models.save_case("theirs", mine, {"address": mine}, owner_hash="b" * 64)
    body = store.get("/cases?limit=500", headers={ownership.OWNER_HEADER: ALICE}).json()
    ids = [c["case_id"] for c in body["cases"]]
    assert ids[0] == "mine" and "theirs" not in ids and len(ids) == len(demos) + 1
    assert body["cases"][0]["direction"] == "incoming" and body["cases"][0]["demo"] is False


def test_a_row_without_a_stored_summary_is_still_listed(store):
    demos = seed_demos(1)
    with models.session() as s:
        s.execute(text("UPDATE cases SET summary_json = NULL WHERE id = 'd0-00'"))
        s.commit()
    body = store.get("/cases?limit=500").json()
    row = next(c for c in body["cases"] if c["case_id"] == "d0-00")
    assert row["exchange"] == "Binance" and body["count"] == len(demos)


def test_the_migration_fills_summaries_for_stored_cases(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    from app import config
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.upgrade(settings, "sec7_cap_3")
        conn.execute(text("INSERT INTO cases (id, address, created_at, result_json) VALUES "
                          "('a', '0x1', 't', :good), ('b', '0x2', 't', 'not json')"),
                     {"good": '{"direction": "incoming", "exchange": "OKX", "graph": {"nodes": [1, 2]}}'})
        command.upgrade(settings, "head")
        rows = dict(conn.execute(text("SELECT id, direction FROM cases")).all())
        summary = conn.execute(text("SELECT summary_json FROM cases WHERE id = 'a'")).scalar()
    assert rows == {"a": "incoming", "b": None}
    assert '"node_count": 2' in summary and '"exchange": "OKX"' in summary
