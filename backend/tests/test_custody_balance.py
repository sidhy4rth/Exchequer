"""Custody balance check (app/custody_balance.py, routes/custody.py): suite feature 9, part 2.

Each custody address of a case is read on chain through the provider client the
trace engine uses (Etherscan, NodeReal, TronGrid) and compared with what the
asset register records as held there. The clients here are the real ones, on an
httpx.MockTransport: their request path, allowance and evidence log run as in
production and nothing reaches the network. The balances below are test values.
"""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import accounts, assets, config, custody, custody_balance, models, ownership, rate_limit
from app.auth import User
from app.chain_data import ProviderNotConfiguredError
from app.etherscan_client import EtherscanClient
from app.main import app
from app.nodereal_client import NoderealClient
from app.tron_client import TronClient

ALICE, BOB = "a" * 32, "b" * 32
TX = "ab" * 32
CUSTODY = "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU"  # the custody address test_assets.py uses
EVM = "0x" + "ab" * 20  # a well-formed test address, not anyone's wallet
USDT_TRON = config.CHAINS["tron"].find_token("USDT").address
USDT_ETH = config.CHAINS["ethereum"].find_token("USDT").address
USDT_BSC = config.CHAINS["bsc"].find_token("USDT").address
TODAY = date(2026, 11, 16)


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'b.db'}", future=True))
    monkeypatch.setattr(custody, "_today", lambda: TODAY)
    monkeypatch.setattr(assets, "_today", lambda: TODAY)
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})


def viewer(key=ALICE):
    return User(id="officer-1", role="officer", unit=None, owner_hash=ownership.owner_hash(key), demo=False,
                officer_id=1, unit_id=None)


def held(amount="635", asset="USDT", chain="tron", held_at=CUSTODY, who=None, holder="custody"):
    who = who or viewer()
    return assets.create(who.owner_hash, "case-1", {
        "holder": holder, "asset": asset, "amount": amount, "chain": chain, "held_at": held_at,
        "tx_hash": TX if holder == "custody" else "", "seized_on": "2026-11-01"}, who)["asset_id"]


def transport(answer):
    """An httpx client whose every request is answered by `answer(request)` -> (status, json body)."""
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = answer(request)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handle)), seen


def tron(trc20=None, balance=None, data=True, status=200, **fields):
    account = {"address": "41", "trc20": [{USDT_TRON: v} for v in ([trc20] if trc20 is not None else [])], **fields}
    if balance is not None:
        account["balance"] = balance
    client, seen = transport(lambda r: (status, {"data": [account] if data else [], "success": True, "meta": {}}))
    return TronClient(api_key="", client=client, min_interval=0), seen


def check(*clients, who=None):
    by_chain = {}
    for c in clients:
        key = {TronClient: "tron", EtherscanClient: "ethereum", NoderealClient: "bsc"}[type(c[0])]
        by_chain[key] = c[0]
    return custody_balance.read_all(who or viewer(), "case-1", opener=lambda chain: by_chain[chain.key])


def stored(c, who=None):
    return custody_balance.run(who or viewer(), "case-1", opener=lambda chain: c[0])


# -- what is compared ------------------------------------------------------------------------------
def test_a_tron_usdt_balance_equal_to_the_register_is_a_match_with_its_evidence():
    held()
    client, seen = tron(trc20="635000000")  # 6 decimals, from config
    out = check((client, seen))
    [r] = out
    assert (r["status"], r["chain_amount"], r["register_amount"], r["difference"]) == ("match", "635", "635", "0")
    assert r["reason"] == "The chain shows 635 USDT, as the register records."
    assert str(seen[0].url).endswith(f"/v1/accounts/{CUSTODY}")
    [ev] = r["evidence"]
    assert ev["provider"] == "trongrid" and len(ev["sha256"]) == 64 and CUSTODY in ev["request"]
    assert custody_balance.counts(out) == {"match": 1, "mismatch": 0, "unchecked": 0}


def test_less_on_chain_than_the_register_is_a_mismatch_said_in_words():
    held()
    [r] = check(tron(trc20="600000000"))
    assert r["status"] == "mismatch" and r["difference"] == "-35"
    assert r["reason"].startswith("Mismatch: the chain shows 600 USDT, 35 USDT less than the 635 USDT")


def test_more_on_chain_than_the_register_is_a_mismatch_too_and_says_why_it_might_be():
    held()
    [r] = check(tron(trc20="635000001"))
    assert r["status"] == "mismatch" and r["difference"] == "0.000001"
    assert "0.000001 USDT more than" in r["reason"] and "another case's money" in r["reason"]


def test_rows_at_one_address_are_summed_and_a_linked_wallet_gives_the_address():
    held(amount="600")
    unnamed = held(amount="35", held_at="", chain="")
    w = custody.create(viewer().owner_hash, "case-1", {
        "chain": "tron", "address": CUSTODY, "scheme": "Tron multi-sign permission", "threshold": 2,
        "signers": [{"name": "Insp. Rao"}, {"name": "SI Iyer"}], "set_up_by": "Insp. Rao",
        "set_up_on": "2026-11-10", "asset_ids": [unnamed]}, viewer())
    [r] = check(tron(trc20="635000000"))
    assert (r["status"], r["register_amount"], len(r["asset_ids"]), r["wallet_id"]) == ("match", "635", 2, w["wallet_id"])


def test_rows_no_longer_held_or_held_elsewhere_are_not_counted():
    held()
    gone = held(amount="100")
    assets.update(gone, {"status": "released_to_victim", "outcome_tx": TX}, viewer())
    held(amount="50", holder="exchange", held_at="An exchange")
    [r] = check(tron(trc20="635000000"))
    assert r["status"] == "match" and r["register_amount"] == "635"


def test_native_trx_is_read_in_sun_and_an_account_without_a_balance_field_holds_none():
    held(amount="12.5", asset="TRX")
    assert check(tron(balance=12_500_000))[0]["status"] == "match"
    [r] = check(tron())
    assert (r["status"], r["chain_amount"]) == ("mismatch", "0")


def test_staked_trx_is_counted_with_the_free_balance_and_the_result_says_how_much():
    held(amount="100", asset="TRX")
    # Field names from TRON's account schema (developers.tron.network, get-account-info-by-address);
    # the amounts are test values in sun.
    client, seen = tron(balance=10_000_000, frozenV2=[{"amount": 50_000_000}, {"type": "ENERGY", "amount": 20_000_000},
                                                      {"type": "TRON_POWER"}],
                        unfrozenV2=[{"unfreeze_amount": 5_000_000, "unfreeze_expire_time": 1}],
                        delegated_frozenV2_balance_for_bandwidth=10_000_000,
                        account_resource={"delegated_frozenV2_balance_for_energy": 5_000_000,
                                          "acquired_delegated_frozenV2_balance_for_energy": 999_000_000},
                        acquired_delegated_frozenV2_balance_for_bandwidth=999_000_000)
    [r] = check((client, seen))
    assert (r["status"], r["chain_amount"], r["staked_amount"]) == ("match", "100", "90")
    assert "90 TRX is staked, delegated or being unstaked" in r["reason"]  # stake others lent it is not its own
    held(amount="1", asset="TRX")
    [r] = check(tron(balance=1_000_000, frozen=[{"frozen_balance": 1_000_000, "expire_time": 1}],
                     account_resource={"frozen_balance_for_energy": {"frozen_balance": 99_000_000}}))
    assert (r["status"], r["chain_amount"], r["staked_amount"]) == ("match", "101", "100")  # Stake 1.0 too


def test_usdt_on_tron_ignores_staked_trx_and_a_bad_stake_field_is_unreadable():
    held()
    [r] = check(tron(trc20="635000000", frozenV2=[{"amount": 50_000_000}]))
    assert r["status"] == "match" and "staked_amount" not in r
    held(amount="1", asset="TRX")
    out = check(tron(trc20="635000000", balance=1_000_000, frozenV2=[{"amount": "lots"}]))
    trx = next(x for x in out if x["asset"] == "TRX")
    assert trx["status"] == "unchecked" and "not a whole-number balance" in trx["reason"]


def test_a_register_amount_finer_than_the_asset_allows_is_said_plainly_not_called_a_mismatch():
    held(amount="635.1234567")  # USDT on Tron has 6 decimal places
    [r] = check(tron(trc20="635123456"))
    assert r["status"] == "unchecked" and r["difference"] is None and r["chain_amount"] == "635.123456"
    assert r["reason"].startswith("The recorded amount, 635.1234567 USDT, has more decimal places than USDT "
                                  "allows (6), so no balance can equal it")
    assert "Mismatch" not in r["reason"]


def test_trailing_zeros_past_the_assets_decimals_are_not_extra_places():
    held(amount="635.00000000")
    [r] = check(tron(trc20="635000000"))
    assert r["status"] == "match"


def test_ethereum_native_and_usdt_are_read_through_etherscan_with_the_configured_decimals():
    held(amount="1.5", asset="ETH", chain="ethereum", held_at=EVM)
    held(amount="20", asset="USDT", chain="ethereum", held_at=EVM)

    def answer(request):
        action = request.url.params["action"]
        result = "1500000000000000000" if action == "balance" else "19000000"
        return 200, {"status": "1", "message": "OK", "result": result}

    http, seen = transport(answer)
    client = EtherscanClient(api_key="test-key", chain_id=1, client=http, min_interval=0)
    eth, usdt = check((client, seen))
    assert (eth["asset"], eth["status"]) == ("ETH", "match")
    assert (usdt["status"], usdt["chain_amount"]) == ("mismatch", "19")
    token_read = next(r for r in seen if r.url.params["action"] == "tokenbalance")
    assert token_read.url.params["contractaddress"] == USDT_ETH and token_read.url.params["tag"] == "latest"
    assert all("test-key" not in e["request"] for e in eth["evidence"] + usdt["evidence"])


def test_bsc_usdt_is_read_through_nodereal_at_a_fixed_block_without_the_key_in_the_evidence():
    held(amount="7", asset="USDT", chain="bsc", held_at=EVM)
    calls = []

    def answer(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["method"] == "eth_blockNumber":
            return 200, {"jsonrpc": "2.0", "id": 1, "result": hex(1000)}
        return 200, {"jsonrpc": "2.0", "id": 1, "result": hex(7 * 10**18)}  # 18 decimals on BSC, from config

    http, seen = transport(answer)
    client = NoderealClient(api_key="node-key", client=http, min_interval=0)
    [r] = check((client, seen))
    assert (r["status"], r["chain_amount"], r["read_from"]) == ("match", "7", "block 968")
    call = calls[-1]
    assert call["method"] == "eth_call" and call["params"][0]["to"] == USDT_BSC
    assert call["params"][0]["data"] == "0x70a08231" + EVM[2:].rjust(64, "0") and call["params"][1] == hex(968)
    assert r["evidence"] and all("node-key" not in e["request"] for e in r["evidence"])


# -- what cannot be told ------------------------------------------------------------------------
def test_an_asset_not_read_on_that_chain_or_a_row_with_no_address_is_unchecked_and_reads_nothing():
    held(asset="DAI")
    held(amount="5", held_at="the unit's wallet", chain="tron")
    client, seen = tron(trc20="0")
    dai, nowhere = check((client, seen))
    assert dai["status"] == "unchecked" and "DAI is not an asset Exchequer reads on Tron" in dai["reason"]
    assert nowhere["status"] == "unchecked" and "names no custody address" in nowhere["reason"]
    assert seen == []


def test_a_provider_not_configured_failing_or_with_no_account_record_leaves_it_unchecked():
    held()

    def missing(chain):
        raise ProviderNotConfiguredError("ETHERSCAN_API_KEY is not set")

    [r] = custody_balance.read_all(viewer(), "case-1", opener=missing)
    assert (r["status"], r["chain_amount"]) == ("unchecked", None) and "no data provider configured" in r["reason"]
    [r] = check(tron(status=500))
    assert r["status"] == "unchecked" and "TronGrid did not give a usable answer" in r["reason"]
    [r] = check(tron(data=False))
    assert r["status"] == "unchecked" and "no account record" in r["reason"]


def test_one_run_reads_at_most_max_reads_pairs(monkeypatch):
    monkeypatch.setattr(custody_balance, "MAX_READS", 1)
    held()
    held(amount="1", asset="TRX")
    client, seen = tron(trc20="635000000", balance=1_000_000)
    first, second = check((client, seen))
    assert first["status"] == "match" and second["status"] == "unchecked" and "at most 1" in second["reason"]
    assert len(seen) == 1


def test_a_run_is_stored_and_only_its_owner_reads_the_newest_one():
    held()
    first = stored(tron(trc20="1"))
    second = stored(tron(trc20="635000000"))
    assert first["check_id"] != second["check_id"]
    assert custody_balance.latest(viewer(), "case-1")["check_id"] == second["check_id"]
    assert custody_balance.latest(viewer(BOB), "case-1") is None
    with models.session() as s:
        assert len(s.scalars(select(models.CustodyBalanceCheck)).all()) == 2


def test_the_newest_run_is_the_last_one_kept_even_within_the_same_second(monkeypatch):
    # Two runs in one second (a second click, two officers of a unit): the one kept last is the newest,
    # and the time shown is still to the second.
    times = iter(["2026-11-16T10:00:00.000001+00:00", "2026-11-16T10:00:00.000002+00:00"])
    monkeypatch.setattr(custody_balance, "_checked_at", lambda: next(times))
    held()
    stored(tron(trc20="1"))
    second = stored(tron(trc20="635000000"))
    newest = custody_balance.latest(viewer(), "case-1")
    assert newest["check_id"] == second["check_id"] and newest["counts"]["match"] == 1
    assert newest["checked_at"] == second["checked_at"] == "2026-11-16T10:00:00+00:00"


# -- routes ---------------------------------------------------------------------------------------
H = {ownership.OWNER_HEADER: ALICE}
PW = "officer-password-long-2"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**4)
    for limiter in rate_limit.LOGIN_LIMITS:
        limiter.reset()
    rate_limit.request_writes.reset()
    unit = accounts.create_unit("Cyber Cell North")
    accounts.create_officer("officer@example.org", "Om Officer", unit.id, "officer", password=PW)
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/auth/login", json={"email": "officer@example.org", "password": PW},
                  headers={accounts.CSRF_HEADER: "1"}).status_code == 200
    return c


def test_switched_off_the_check_says_so_and_refuses_to_run(client, monkeypatch):
    monkeypatch.setattr(config, "CUSTODY_BALANCE_CHECK", False)
    assert client.get("/trace/case-1/custody-balance", headers=H).json() == {
        "case_id": "case-1", "enabled": False, "check": None}
    assert client.post("/trace/case-1/custody-balance", headers=H).status_code == 403


def test_an_officer_runs_a_check_the_demo_caller_cannot_and_the_audit_holds_counts_only(client, monkeypatch):
    monkeypatch.setattr(config, "CUSTODY_BALANCE_CHECK", True)
    tron_client, _ = tron(trc20="600000000")
    monkeypatch.setattr(custody_balance, "open_source", lambda chain: tron_client)
    assert client.post("/trace/case-1/assets", json={
        "holder": "custody", "asset": "USDT", "amount": "635", "chain": "tron", "held_at": CUSTODY,
        "tx_hash": TX, "seized_on": "2026-11-01"}, headers=H).status_code == 201
    demo = TestClient(app)
    refused = demo.post("/trace/case-1/custody-balance", headers=H)
    assert refused.status_code == 403 and "Sign in as an officer" in refused.json()["detail"]
    offered = demo.get("/trace/case-1/custody-balance", headers=H).json()  # so the panel offers no button
    assert offered["can_check"] is False and offered["check_note"].startswith("Sign in as an officer")
    ran = client.post("/trace/case-1/custody-balance", headers=H)
    assert ran.status_code == 201 and ran.json()["results"][0]["status"] == "mismatch"
    assert client.post("/trace/no-such-case/custody-balance", headers=H).status_code == 404
    shown = client.get("/trace/case-1/custody-balance", headers=H).json()
    assert shown["enabled"] is True and shown["check"]["check_id"] == ran.json()["check_id"]
    assert shown["can_check"] is True and shown["check_note"] == ""
    with models.session() as s:
        rows = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "custody.balance.check")).all()
    assert [json.loads(r.detail) for r in rows] == [
        {"check_id": ran.json()["check_id"], "match": 0, "mismatch": 1, "unchecked": 0}]


def test_g7_custody_3_goes_down_and_up_again_keeping_the_cases():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    held()
    stored(tron(trc20="635000000"))
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with models._engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.downgrade(settings, "g7_statements_2")
    assert "custody_balance_checks" not in set(inspect(models._engine).get_table_names())
    assert models.get_case("case-1") is not None
    models.init_db()
    assert "custody_balance_checks" in set(inspect(models._engine).get_table_names())
