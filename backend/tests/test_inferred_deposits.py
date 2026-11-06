"""Deposit addresses that stored cases inferred, as watch alerts use them.

Watch alerts call a counterparty "probable X deposit address" when a stored
trace inferred it. That used to be a map rebuilt from every owner's cases --
up to 2,000 full results loaded and parsed after every save (r1-dos-cost-7),
built from other browsers' traces too, so a planted trace could label
someone else's alert (r1-authz-routes-8), and stamped with a version read
after the load, so a case saved meanwhile was missed (r2-g2-background-
threads-failure-4-7). Now each saved case writes its inferences to an indexed
table in the same transaction, and a check asks only of the cases its owner
may see.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select

from app import models, ownership, watchlist
from test_watchlist import ALICE, BOB, WALLET, FakeChain, owner, tx


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'd.db'}", future=True))
    models.init_db()


@pytest.fixture
def chain(store):
    return FakeChain()


DEPOSIT = "0x" + "d" * 40
DEMO_SEED = sorted(ownership.demo_addresses())[0]


def infer(case_id, deposit=DEPOSIT, exchange="OKX", key=None, seed=WALLET):
    models.save_case(case_id, seed, {"address": seed, "chain": "ethereum",
                                     "inferred_deposits": [{"address": deposit.upper().replace("0X", "0x"),
                                                            "exchange": exchange}]},
                     owner_hash=owner(key) if key else None)


def watched(chain, key=ALICE):
    w = watchlist.create_watch(owner(key), WALLET, "ethereum", "ETH")
    watchlist.check_watch(w.id, source=chain)  # baseline
    return w


def test_saving_a_case_writes_its_inferred_deposits(store):
    infer("c1", key=ALICE)
    with models.session() as s:
        (row,) = s.scalars(select(models.InferredDeposit))
    assert (row.case_id, row.chain, row.address, row.exchange) == ("c1", "ethereum", DEPOSIT, "OKX")
    assert row.owner_hash == owner(ALICE) and row.seed_address == WALLET


def test_checks_and_alert_lists_never_load_whole_cases(chain, monkeypatch):
    infer("c1", key=ALICE)
    w = watched(chain)

    def refuse(*a, **k):
        raise AssertionError("loaded whole cases")
    for name in ("all_cases", "list_cases", "get_case"):
        monkeypatch.setattr(models, name, refuse)
    chain.transfers = [tx(7, DEPOSIT, 2.0)]
    (alert,) = watchlist.check_watch(w.id, source=chain)
    assert alert["kind"] == "exchange" and alert["exchange"] == "OKX"
    assert watchlist.list_alerts(owner(ALICE))[0]["exchange"] == "OKX"


def test_your_own_inference_is_an_exchange(chain):
    infer("c1", key=ALICE)
    w = watched(chain)
    chain.transfers = [tx(7, DEPOSIT, 2.0)]
    (alert,) = watchlist.check_watch(w.id, source=chain)
    assert alert["kind"] == "exchange" and "probable OKX deposit address (inferred)" in alert["message"]


def test_another_owners_inference_is_not_an_exchange(chain):
    infer("bobs", key=BOB, exchange="Binance")  # Bob's trace, perhaps planted
    w = watched(chain)
    chain.transfers = [tx(7, DEPOSIT, 2.0)]
    (alert,) = watchlist.check_watch(w.id, source=chain)
    assert alert["kind"] == "moved" and alert["exchange"] is None
    assert "Binance" not in alert["message"] and "Binance" not in alert["counterparty_label"]


def test_a_demo_inference_says_so(chain):
    infer("demo", seed=DEMO_SEED, key=None, exchange="Kraken")  # public demo case
    w = watched(chain)
    chain.transfers = [tx(7, DEPOSIT, 2.0)]
    (alert,) = watchlist.check_watch(w.id, source=chain)
    assert alert["kind"] == "exchange" and "inferred in a demo case" in alert["message"]


def test_an_unowned_case_that_is_not_a_demo_labels_nothing(chain):
    infer("legacy", seed="0x" + "5" * 40, key=None)  # stored before ownership, not public
    w = watched(chain)
    chain.transfers = [tx(7, DEPOSIT, 2.0)]
    assert watchlist.check_watch(w.id, source=chain)[0]["kind"] == "moved"


def test_alert_listing_does_not_name_another_owners_exchange(chain):
    infer("mine", key=ALICE)
    w = watched(chain)
    chain.transfers = [tx(7, DEPOSIT, 2.0)]
    watchlist.check_watch(w.id, source=chain)
    # Bob watches the same wallet; his stored alert to the deposit was labelled
    # by a case of Alice's only in the old code. Listing it must not name OKX.
    with models.session() as s:
        alice_alert = s.scalars(select(models.Alert)).one()
        s.add(models.Alert(id="bobs-alert", watch_id=w.id, owner_hash=owner(BOB), created_at=alice_alert.created_at,
                           kind="exchange", message="m", tx_hash="0x1", tx_time=1, value=1.0, asset="ETH",
                           counterparty=DEPOSIT, counterparty_label="probable OKX deposit address (inferred)"))
        s.commit()
    assert watchlist.list_alerts(owner(ALICE))[0]["exchange"] == "OKX"
    assert watchlist.list_alerts(owner(BOB))[0]["exchange"] is None


def test_a_case_saved_while_the_map_was_being_read_is_seen_next_time(chain, monkeypatch):
    # The old map loaded every case, then stamped itself with the store
    # version read *after* the load: a case saved during the load was never
    # in it, yet the map looked current. Lookups are now live queries.
    w = watched(chain)
    saved = []
    real_all_cases = models.all_cases

    def save_during_the_load(*a, **k):
        cases = real_all_cases(*a, **k)
        if not saved:
            infer("late", key=ALICE)
            saved.append(True)
        return cases
    monkeypatch.setattr(models, "all_cases", save_during_the_load)
    chain.transfers = [tx(7, "0x" + "6" * 40)]
    watchlist.check_watch(w.id, source=chain)
    if not saved:
        infer("late", key=ALICE)  # the same save, between two checks
    chain.transfers = [tx(7, "0x" + "6" * 40), tx(8, DEPOSIT, 2.0)]
    (alert,) = watchlist.check_watch(w.id, source=chain)
    assert alert["kind"] == "exchange" and alert["exchange"] == "OKX"
