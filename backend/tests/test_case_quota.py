"""One browser cannot fill the whole case store (routes/cases.py store_result).

The store has a server-wide cap (MAX_STORED_CASES); once reached, no one's
trace is saved, so there is no report, letter or link for anyone. One owner
key used to be able to fill it alone. Now each owner key keeps at most
MAX_CASES_PER_OWNER cases, and the log warns when the store is 80% full.
"""
from __future__ import annotations

import logging

import pytest
from sqlalchemy import create_engine

from app import config, models
from app.pipeline import TraceRequest
from app.routes import cases

ALICE, BOB = "a" * 64, "b" * 64
REQUEST = TraceRequest(address="0x" + "1" * 40)


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'q.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(config, "MAX_STORED_CASES", 100)
    monkeypatch.setattr(config, "MAX_CASES_PER_OWNER", 3)


def store_one(owner):
    return cases.store_result({"address": REQUEST.address}, REQUEST, owner)


def test_an_owner_at_its_quota_is_not_saved_but_others_are():
    assert all(store_one(ALICE)["case_id"] for _ in range(3))
    full = store_one(ALICE)
    assert full["case_id"] is None
    assert any("this browser" in w.lower() for w in full["warnings"])
    assert store_one(BOB)["case_id"]


def test_the_log_warns_as_the_store_fills(caplog):
    with caplog.at_level(logging.WARNING, logger="app.routes.cases"):
        for i in range(80):
            store_one(f"{i:064x}")
    assert any("80%" in r.getMessage() for r in caplog.records)
