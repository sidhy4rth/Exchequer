"""The citizen site's tables (app/complaints.py): the main app owns their
schema and reads the queue; the citizen functions (citizen/api/) write it.

A complaint whose paid wallet is a stored case's reported address is tagged
for officers only (wallet_match); the citizen site never reads that column
back to a citizen (citizen/api/tests/test_my_case.py)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

from app import complaints, models

TRON = "TJ" + "a" * 32
EVM = "0x" + "ab" * 20


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    return engine


def complaint(engine, cid: str, wallet: str, match: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO complaints (id, reference, ncrp, status, details_json, wallet_match, "
                          "created_at, updated_at) VALUES (:i, :r, '12345678901234', 'received', '{}', :m, 't', 't')"),
                     {"i": cid, "r": "R-" + cid, "m": match})
        conn.execute(text("INSERT INTO complaint_payments (id, complaint_id, tx_hash, amount, token, network, "
                          "paid_at, wallet) VALUES (:p, :i, '', '', '', '', '', :w)"), {"p": "p-" + cid, "i": cid, "w": wallet})


def tags(engine, cid: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(text("SELECT wallet_match FROM complaints WHERE id = :i"), {"i": cid}).scalar()


def test_the_citizen_tables_exist_with_the_officer_only_flag(store):
    names = set(inspect(store).get_table_names())
    assert {"complaints", "complaint_payments", "complaint_messages", "tracking_codes",
            "citizen_sessions", "citizen_attempts"} <= names
    assert "wallet_match" in {c["name"] for c in inspect(store).get_columns("complaints")}


def test_a_complaint_paying_a_stored_cases_wallet_is_tagged_case(store):
    models.save_case("c1", EVM, {"chain": "ethereum"})
    models.save_case("c2", TRON, {"chain": "tron"})
    complaint(store, "a", EVM.upper().replace("0X", "0x"))  # the citizen API stores 0x wallets lowercased
    complaint(store, "b", TRON, match="complaint")
    complaint(store, "c", "T" + "z" * 33)
    with store.begin() as conn:
        conn.execute(text("UPDATE complaint_payments SET wallet = :w WHERE complaint_id = 'a'"), {"w": EVM})
    assert complaints.flag_case_matches() == 2
    assert tags(store, "a") == "case"
    assert tags(store, "b") == "case,complaint"
    assert tags(store, "c") is None
    assert complaints.flag_case_matches() == 0  # already tagged: nothing changes twice
    assert tags(store, "b") == "case,complaint"


def test_merge_tags_keeps_them_sorted_and_unique():
    assert complaints.merge_tags(None, "case") == "case"
    assert complaints.merge_tags("complaint", "case") == "case,complaint"
    assert complaints.merge_tags("case,complaint", "case") == "case,complaint"


def test_the_citizen_functions_run_on_the_migrated_store(store, tmp_path, monkeypatch):
    # CI runs the same flow on Postgres as the citizen role (scripts/check_citizen_role.py).
    import importlib.util
    for name in ("CITIZEN_DATABASE_URL", "CITIZEN_SECRET"):  # put back after the run sets them
        monkeypatch.setenv(name, "")

    from app import config
    spec = importlib.util.spec_from_file_location("check_citizen_role",
                                                  config.BACKEND_DIR / "scripts" / "check_citizen_role.py")
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    check.flow(f"sqlite:///{tmp_path / 'c.db'}")


def test_opening_the_store_tags_complaints_that_pay_a_cases_wallet(store):
    from app import main
    models.save_case("c1", TRON, {"chain": "tron"})
    complaint(store, "a", TRON)
    assert main._open_store()
    assert tags(store, "a") == "case"


def test_case_matches_are_tagged_again_on_a_schedule_and_a_failure_does_not_stop_it(monkeypatch):
    import threading
    runs, done = [], threading.Event()

    def flag():
        runs.append(1)
        if len(runs) == 2:
            raise RuntimeError("store away")
        if len(runs) >= 3:
            done.set()
        return 0
    monkeypatch.setattr(complaints, "flag_case_matches", flag)
    complaints.stop_matching()  # one a site start left running
    assert complaints.start_matching(every=0.01)
    try:
        assert done.wait(5) and len(runs) >= 3
        assert not complaints.start_matching(every=0.01)  # one schedule at a time
    finally:
        complaints.stop_matching()


def test_the_site_starts_the_case_match_schedule(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    started = []
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))
    monkeypatch.setattr(complaints, "start_matching", lambda *a, **k: started.append(1) or True)
    stopped = []
    monkeypatch.setattr(complaints, "stop_matching", lambda: stopped.append(1))
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
    assert started == stopped == [1]  # and it stops with the site
