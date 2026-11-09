"""Stored cases are read from memory after the first time (models.get_case).

A stored case never changes, but every read pulled its whole result (it can be
megabytes) from the database again. In production that database is a metered
free tier: a loop of reads of one case spends its monthly transfer, and the
store is suspended. Reads now come from a small cache bounded in bytes.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event

from app import models


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    statements = []
    event.listen(engine, "before_cursor_execute", lambda conn, cursor, sql, *a: statements.append(sql))
    return statements


def big(n: int) -> dict:
    return {"address": "0xseed", "pad": "x" * n}


def test_a_case_read_twice_is_fetched_once(db):
    models.save_case("case-1", "0xseed", big(1000))
    db.clear()
    first = models.get_case("case-1")
    second = models.get_case("case-1")
    assert first.result == second.result == big(1000)
    assert len([s for s in db if "result_json" in s]) == 1


def test_a_missing_case_is_still_missing_and_found_once_saved(db):
    assert models.get_case("later") is None
    models.save_case("later", "0xseed", big(10))
    assert models.get_case("later").result == big(10)


def test_the_cache_is_bounded_in_bytes(db, monkeypatch):
    monkeypatch.setattr(models, "CASE_CACHE_BYTES", 5_000)
    for i in range(10):
        models.save_case(f"c{i}", "0xseed", big(1_000))
        models.get_case(f"c{i}")
    assert models._case_cache.size <= 5_000
    # The newest stay; the oldest were dropped and come from the database again.
    db.clear()
    models.get_case("c9")
    assert not [s for s in db if "result_json" in s]
    models.get_case("c0")
    assert [s for s in db if "result_json" in s]


def test_a_case_larger_than_a_quarter_of_the_cache_is_not_kept(db, monkeypatch):
    monkeypatch.setattr(models, "CASE_CACHE_BYTES", 4_000)
    models.save_case("huge", "0xseed", big(2_000))
    models.get_case("huge")
    assert models._case_cache.size == 0


def test_a_new_database_starts_with_an_empty_cache(tmp_path, monkeypatch):
    # Tests (and a re-pointed store) swap the engine; a case id from the old
    # store must never be answered from memory for the new one.
    for name, pad in (("a", 10), ("b", 20)):
        monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / (name + '.db')}", future=True))
        models.init_db()
        models.save_case("same-id", "0xseed", big(pad))
        assert models.get_case("same-id").result == big(pad)
