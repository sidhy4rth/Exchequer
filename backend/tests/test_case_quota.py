"""One browser cannot fill the whole case store (routes/cases.py store_result).

The store has a server-wide cap (MAX_STORED_CASES); once reached, no one's
trace is saved, so there is no report, letter or link for anyone. One owner
key used to be able to fill it alone. Now each owner key keeps at most
MAX_CASES_PER_OWNER cases, and the log warns when the store is 80% full.

Owner keys are free, so rotating them still filled the store (8 Nov check).
Now one connection saves at most MAX_CASES_PER_CLIENT_PER_DAY cases a day,
whatever keys it sends, and a full store makes room by deleting the oldest
cases nobody is using: saved without an owner key, or kept by an owner idle
for CASE_IDLE_DAYS. Demo cases, and cases a freeze request or an active
watch refers to, are never deleted.
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update

from app import config, models, ownership, pipeline
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
    monkeypatch.setattr(config, "MAX_CASES_PER_CLIENT_PER_DAY", 150)
    monkeypatch.setattr(config, "CASE_IDLE_DAYS", 30)


def store_one(owner, client=None):
    return cases.store_result({"address": REQUEST.address}, REQUEST, owner, client=client)


def age(case_ids, days):
    """Make cases look `days` old."""
    stamp = cases._since(days * 86400)
    with models.session() as s:
        s.execute(update(models.Case).where(models.Case.id.in_(case_ids)).values(created_at=stamp))
        s.commit()


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


def test_rotating_owner_keys_from_one_connection_cannot_fill_the_store(monkeypatch):
    """The 8 Nov probe: caps of 6 cases and 2 per owner, one connection with 3
    fresh owner keys saved 6 cases and the officer's next trace was not saved."""
    monkeypatch.setattr(config, "MAX_STORED_CASES", 6)
    monkeypatch.setattr(config, "MAX_CASES_PER_OWNER", 2)
    monkeypatch.setattr(config, "MAX_CASES_PER_CLIENT_PER_DAY", 4)
    saved = [store_one(f"{k:064x}", client="10.0.0.66")["case_id"] for k in range(3) for _ in range(2)]
    assert sum(1 for c in saved if c) == 4
    refused = store_one("e" * 64, client="10.0.0.66")
    assert refused["case_id"] is None and "this connection" in refused["warnings"][-1].lower()
    assert store_one("f" * 64, client="10.0.0.5")["case_id"]  # the officer's is saved


def test_the_probe_over_http(monkeypatch):
    """The same probe through POST /trace, the officer on another connection."""
    monkeypatch.setattr(pipeline, "run_trace", lambda req: {"address": req.address, "chain": "ethereum",
                                                            "warnings": []})
    monkeypatch.setattr(config, "MAX_STORED_CASES", 6)
    monkeypatch.setattr(config, "MAX_CASES_PER_OWNER", 2)
    monkeypatch.setattr(config, "MAX_CASES_PER_CLIENT_PER_DAY", 4)
    from app.main import app
    from app.routes import cases as routes
    monkeypatch.setattr(routes, "_slot_clock", routes.SlotClock())
    with TestClient(app) as c:
        ids = [c.post("/trace", json={"address": "0x" + "1" * 40},
                      headers={ownership.OWNER_HEADER: f"attacker-key-{k}-" + "z" * 30}).json().get("case_id")
               for k in range(3) for _ in range(2)]
        assert sum(1 for i in ids if i) == 4
    with TestClient(app, client=("10.9.9.9", 50000)) as c:
        officer = c.post("/trace", json={"address": "0x" + "2" * 40},
                         headers={ownership.OWNER_HEADER: "officer-key-" + "q" * 30}).json()
    assert officer["case_id"]


def test_a_full_store_makes_room_from_anonymous_cases_first(monkeypatch):
    monkeypatch.setattr(config, "MAX_STORED_CASES", 4)
    anon = [store_one(None, client=f"10.0.1.{i}")["case_id"] for i in range(2)]
    owned = [store_one(ALICE)["case_id"], store_one(BOB)["case_id"]]
    assert all(anon + owned) and models.case_count() == 4
    age([anon[0]], 2)
    age([anon[1]], 1)  # an anonymous case makes room at any age, the oldest first
    first = store_one("c" * 64)
    assert first["case_id"] and models.case_count() == 4
    assert models.get_case(anon[0]) is None  # the oldest anonymous case gave up its place
    assert models.get_case(anon[1]) is not None and all(models.get_case(i) for i in owned)
    assert store_one("d" * 64)["case_id"]
    assert models.get_case(anon[1]) is None
    # Nothing else is unused: the store is full again, and says so.
    full = store_one("e" * 64)
    assert full["case_id"] is None and "case store is full" in full["warnings"][-1]
    assert all(models.get_case(i) for i in owned)


def test_an_idle_owners_cases_make_room_but_an_active_owners_do_not(monkeypatch):
    monkeypatch.setattr(config, "MAX_STORED_CASES", 3)
    old_alice = store_one(ALICE)["case_id"]
    old_bob = store_one(BOB)["case_id"]
    age([old_alice, old_bob], 40)
    store_one(BOB)  # Bob is still using the site: his old case stays
    carol = store_one("c" * 64)
    assert carol["case_id"]
    assert models.get_case(old_alice) is None and models.get_case(old_bob) is not None


def test_demo_cases_and_cases_in_use_never_make_room(monkeypatch):
    from app import freeze_requests, watchlist
    monkeypatch.setattr(config, "MAX_STORED_CASES", 3)
    demo = sorted(ownership.demo_addresses())[0]
    models.save_case("demo-1", demo, {"address": demo})  # no owner: a public demo case
    requested = store_one(None)["case_id"]
    watched = store_one(None)["case_id"]
    age(["demo-1", requested, watched], 400)
    freeze_requests.create(ALICE, requested, "Binance", "exchange")
    with models.session() as s:
        s.add(models.Watch(id="w1", owner_hash=ALICE, chain="ethereum", asset="ETH", address="0x" + "7" * 40,
                           case_id=watched, created_at=models.utc_now_iso(), active=True))
        s.commit()
    assert watchlist  # imported for its table
    full = store_one("d" * 64)
    assert full["case_id"] is None
    assert all(models.get_case(i) for i in ("demo-1", requested, watched))


def test_a_deleted_case_is_gone_from_the_case_cache_too(monkeypatch):
    monkeypatch.setattr(config, "MAX_STORED_CASES", 1)
    anon = store_one(None)["case_id"]
    assert models.get_case(anon) is not None  # now cached
    assert store_one(ALICE)["case_id"]
    assert models.get_case(anon) is None


# -- the store's size in bytes (r1-trace-engine-5) ------------------------------
def store_sized(owner, nbytes, client=None):
    payload = {"address": REQUEST.address, "pad": "x" * nbytes}
    return cases.store_result(payload, REQUEST, owner, client=client)


def test_the_store_never_holds_more_bytes_than_its_bound(monkeypatch):
    """The 8 Nov check: the cap counted cases, so ~340 dense cases of 1.5 MB
    filled Neon's 0.5 GB long before 5,000 cases. Now the bytes are bounded too."""
    monkeypatch.setattr(config, "MAX_STORED_BYTES", 10_000)
    saved = [store_sized(f"{k:064x}", 3_000)["case_id"] for k in range(5)]
    assert sum(1 for c in saved if c) == 3
    refused = store_sized("e" * 64, 3_000)
    assert refused["case_id"] is None and "case store is full" in refused["warnings"][-1]
    assert "MB" in refused["warnings"][-1]
    assert models.stored_bytes() <= 10_000
    assert store_sized("f" * 64, 100)["case_id"]  # a small one still fits


def test_a_large_case_makes_room_from_several_unused_ones(monkeypatch):
    monkeypatch.setattr(config, "MAX_STORED_BYTES", 10_000)
    anon = [store_sized(None, 2_000)["case_id"] for _ in range(4)]
    for n, case_id in enumerate(anon):
        age([case_id], 10 - n)
    kept = store_sized(ALICE, 1_000)["case_id"]
    big = store_sized(BOB, 6_000)
    assert big["case_id"]
    assert models.stored_bytes() <= 10_000
    gone = [i for i in anon if models.get_case(i) is None]
    assert gone == anon[:len(gone)] and len(gone) >= 2  # the oldest first
    assert models.get_case(kept) is not None


def test_sizes_are_recorded_and_summed():
    first = store_sized(ALICE, 500)["case_id"]
    second = store_sized(BOB, 1500)["case_id"]
    assert models.stored_bytes() == sum(len(models.get_case(i).result_json) for i in (first, second))


# -- bytes per connection and per owner (r2-g2-documented-claims-vs-code-7-0, 8 Nov re-check) --
# The per-connection quota counted cases, not bytes, while the store is
# bounded at MAX_STORED_BYTES and an active owner's cases are never evicted:
# one connection with one owner key filled the store with dense cases in
# hours to two days (p_bytes_fill). Now one connection saves at most
# MAX_BYTES_PER_CLIENT_PER_DAY bytes of cases a day and one owner key keeps
# at most MAX_BYTES_PER_OWNER, whatever the counts say.

def test_the_rechecks_probe_one_connection_cannot_fill_the_store_by_bytes(monkeypatch):
    # p_bytes_fill, scaled 1:10: a 30 MB store, cases of 0.39 MB, a 3 MB daily byte quota.
    monkeypatch.setattr(config, "MAX_STORED_CASES", 5000)
    monkeypatch.setattr(config, "MAX_CASES_PER_OWNER", 200)
    monkeypatch.setattr(config, "MAX_STORED_BYTES", 30_000_000)
    monkeypatch.setattr(config, "MAX_BYTES_PER_CLIENT_PER_DAY", 3_000_000)
    monkeypatch.setattr(config, "MAX_BYTES_PER_OWNER", 5_000_000)
    attacker = "z" * 64
    saved = 0
    for _ in range(150):
        result = store_sized(attacker, 390_000, client="203.0.113.66")
        if not result["case_id"]:
            assert "last 24 hours" in result["warnings"][-1] and "MB" in result["warnings"][-1]
            break
        saved += 1
    assert saved == 7  # 7 x 0.39 MB fit in 3 MB; the 8th would not
    assert models.stored_bytes() <= 3_000_000
    # A fresh owner key from the same connection does not get round it.
    assert store_sized("y" * 64, 390_000, client="203.0.113.66")["case_id"] is None
    # The officer's case from another connection is saved.
    assert store_sized("q" * 64, 3_200, client="198.51.100.5")["case_id"]


def test_the_daily_byte_quota_frees_up_after_a_day(monkeypatch):
    monkeypatch.setattr(config, "MAX_BYTES_PER_CLIENT_PER_DAY", 5_000)
    first = store_sized(ALICE, 3_000, client="10.0.0.7")["case_id"]
    assert store_sized(BOB, 3_000, client="10.0.0.7")["case_id"] is None
    age([first], 2)
    assert store_sized(BOB, 3_000, client="10.0.0.7")["case_id"]


def test_one_owner_key_keeps_at_most_its_bytes(monkeypatch):
    monkeypatch.setattr(config, "MAX_BYTES_PER_OWNER", 5_000)
    assert store_sized(ALICE, 3_000, client="10.0.0.1")["case_id"]
    refused = store_sized(ALICE, 3_000, client="10.0.0.2")  # another connection, the same key
    assert refused["case_id"] is None and "this browser" in refused["warnings"][-1].lower()
    assert "MB" in refused["warnings"][-1]
    assert store_sized(BOB, 3_000, client="10.0.0.2")["case_id"]
    assert store_sized(ALICE, 500, client="10.0.0.1")["case_id"]  # a small one still fits


def test_the_byte_quotas_are_configurable_and_documented():
    from pathlib import Path
    assert config.MAX_BYTES_PER_CLIENT_PER_DAY == 30 * 1000 * 1000
    assert config.MAX_BYTES_PER_OWNER > 0
    operations = (config.BACKEND_DIR.parent / "docs" / "operations.md").read_text()
    for name in ("EXCHEQUER_MAX_BYTES_PER_CLIENT_PER_DAY", "EXCHEQUER_MAX_BYTES_PER_OWNER"):
        assert name in operations and name in Path(config.__file__).read_text()


def test_byte_quotas_of_zero_mean_no_quota(monkeypatch):
    monkeypatch.setattr(config, "MAX_BYTES_PER_CLIENT_PER_DAY", 0)
    monkeypatch.setattr(config, "MAX_BYTES_PER_OWNER", 0)
    monkeypatch.setattr(config, "MAX_CASES_PER_OWNER", 10)
    assert all(store_sized(ALICE, 3_000, client="10.0.0.9")["case_id"] for _ in range(5))
