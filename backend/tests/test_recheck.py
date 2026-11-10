"""POST /trace/{id}/recheck rereads the transfers a case's route to the
exchange cites from a provider the trace did not use (app/second_provider.py);
GET /trace/{id}/recheck returns the last result kept with the case.

The provider's answers are the real responses tests/test_verify_case.py
replays, served through an httpx MockTransport: no network.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import access, api_budget, audit, config, models, ownership, rate_limit, second_provider, tron_tags
from app.main import app
from app.routes import recheck as route

FIXTURES = Path(__file__).parent / "fixtures" / "verify_case"
OWNER = {ownership.OWNER_HEADER: "o" * 32}
STRANGER = {ownership.OWNER_HEADER: "s" * 32}


def recorded(demo: int) -> dict:
    rows = json.loads((config.DATA_DIR / "recorded_demos.json").read_text(encoding="utf-8"))
    return copy.deepcopy(next(row for row in rows if row["demo"] == demo)["result"])


def answers(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def ethereum_case() -> dict:
    """One ETH hop to an exchange, made of demo 1's first transfer (whose
    recorded node answers are in the fixtures)."""
    first = recorded(1)["transfers"][0]
    return {"address": first["from"], "chain": "ethereum", "chain_name": "Ethereum Mainnet", "asset": "ETH",
            "direction": "outgoing", "exchange": "Binance", "exchange_address": first["to"],
            "trace_path": [{"address": first["from"], "depth": 0}, {"address": first["to"], "depth": 1}],
            "transfers": [first], "follow_ons": []}


class Provider:
    """TronScan and the public Ethereum nodes, answering from the recordings;
    `special` answers a hash some other way."""

    def __init__(self) -> None:
        self.tron = answers("demo_12_tron.json")
        self.eth = answers("demo_1_ethereum.json")
        self.reads = 0
        self.down = False
        self.special: dict = {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.reads += 1
        self.requests.append(request)
        if self.down:
            return httpx.Response(502, text="bad gateway")
        tron = request.url.host == "apilist.tronscanapi.com"
        call = None if tron else json.loads(request.content)
        digest = request.url.params["hash"] if tron else call["params"][0]
        if digest in self.special:
            return self.special[digest]()
        if tron:
            return httpx.Response(200, json=self.tron.get(digest, {}))
        part = "transaction" if call["method"] == "eth_getTransactionByHash" else "receipt"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                         "result": (self.eth.get(digest) or {}).get(part)})


@pytest.fixture
def provider(monkeypatch):
    served = Provider()
    monkeypatch.setattr(second_provider, "TRANSPORT", httpx.MockTransport(served))
    monkeypatch.setattr(second_provider, "_pacer", lambda _provider: api_budget.SharedPacer(0))
    return served


@pytest.fixture
def client(tmp_path, monkeypatch, provider):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True))
    models.init_db()
    mine = ownership.owner_hash(OWNER[ownership.OWNER_HEADER])
    models.save_case("tron-1", recorded(12)["address"], recorded(12), owner_hash=mine)
    models.save_case("eth-1", ethereum_case()["address"], ethereum_case(), owner_hash=mine)
    models.save_case("no-exchange", recorded(1)["address"], recorded(1), owner_hash=mine)
    return TestClient(app)


def recheck(client, case_id="tron-1", headers=OWNER):
    return client.post(f"/trace/{case_id}/recheck", headers=headers)


def statuses(body: dict) -> list[str]:
    return [t["status"] for t in body["transfers"]]


# -- what a recheck says ---------------------------------------------------------------
def test_every_cited_transfer_that_matches_says_so_and_is_kept_with_the_case(client):
    response = recheck(client)
    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "tron-1" and body["provider"] == "TronScan" and body["checked_at"]
    assert statuses(body) == ["matches"] * 5
    assert all(t["differences"] == [] and len(t["hash"]) == 64 for t in body["transfers"])
    assert body["saved"] is True and body["cited"] == body["checked"] == 5
    kept = client.get("/trace/tron-1/recheck", headers=STRANGER).json()
    assert kept["checked_at"] == body["checked_at"] and kept["transfers"] == body["transfers"]


def test_an_ethereum_case_is_reread_from_public_nodes(client):
    body = recheck(client, "eth-1").json()
    assert "public Ethereum nodes" in body["provider"]
    assert statuses(body) == ["matches"]


@pytest.mark.parametrize("field, tamper", [
    ("amount", lambda item: {**item, "amount_str": "1"}),
    ("recipient", lambda item: {**item, "to_address": "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf"}),
])
def test_a_transfer_whose_amount_or_recipient_differs_is_named(client, provider, field, tamper):
    first = recorded(12)["transfers"][0]["hash"]
    answer = provider.tron[first]
    provider.tron[first] = {**answer, "trc20TransferInfo": [tamper(answer["trc20TransferInfo"][0])]}
    body = recheck(client).json()
    changed = next(t for t in body["transfers"] if t["hash"] == first)
    assert changed["status"] == "differs"
    assert [d["field"] for d in changed["differences"]] == [field]
    assert changed["differences"][0]["provider"] != changed["differences"][0]["case"]
    assert sorted(statuses(body)) == ["differs"] + ["matches"] * 4


def test_a_transfer_the_provider_does_not_have_is_not_found(client, provider):
    first = recorded(12)["transfers"][0]["hash"]
    del provider.tron[first]
    body = recheck(client).json()
    assert next(t for t in body["transfers"] if t["hash"] == first)["status"] == "not_found"


def test_a_provider_error_is_an_error_never_a_match(client, provider):
    provider.down = True
    body = recheck(client).json()
    assert statuses(body) == ["error"] * 5
    assert all("could not be read" in t["detail"] for t in body["transfers"])


def dense_case() -> dict:
    """Demo 12 stretched to two hops: 41 transfers to a middle wallet, of which
    the path step lists 20 (as pipeline._trace_path does), 2 from it into the
    exchange, and 30 deposits into the exchange from wallets off the path,
    which its letter lists too (an explorer-tagged wallet): 52 cited."""
    case = recorded(12)
    middle, row = "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf", case["transfers"][0]
    first = [{**row, "hash": f"a{n:063x}", "to": middle} for n in range(41)]
    deposits = [{**row, "hash": f"d{n:063x}", "from": middle} for n in range(2)]
    others = [{**row, "hash": f"e{n:063x}", "from": f"Tother{n}"} for n in range(30)]
    start, end = case["trace_path"]
    case["trace_path"] = [start, {"address": middle, "depth": 1, "tx_hashes": [t["hash"] for t in first[:20]]},
                          {**end, "depth": 2, "tx_hashes": [t["hash"] for t in deposits]}]
    case["transfers"] = first + deposits + others
    return case


def test_past_forty_cited_transfers_the_deposits_into_the_exchange_are_reread_first(client, provider):
    models.save_case("dense", recorded(12)["address"], dense_case(),
                     owner_hash=ownership.owner_hash(OWNER[ownership.OWNER_HEADER]))
    body = recheck(client, "dense").json()
    assert body["cited"] == 52 and body["checked"] == 40 and len(body["transfers"]) == 40
    assert provider.reads == 40
    read = {t["hash"] for t in body["transfers"]}
    assert {f"d{n:063x}" for n in range(2)} <= read  # the hop into the exchange, always
    assert any(h[0] == "a" for h in read) and any(h[0] == "e" for h in read)  # every hop gets a turn
    assert not any(h[0] == "a" and int(h[1:], 16) >= 20 for h in read)  # never one no document cites


def test_a_case_that_reached_no_exchange_cites_nothing_to_recheck(client, provider):
    response = recheck(client, "no-exchange")
    assert response.status_code == 400 and "nothing to recheck" in response.json()["detail"]
    assert provider.reads == 0


def test_a_chain_without_a_second_provider_is_refused_before_any_read(client, provider):
    case = {**ethereum_case(), "chain": "bsc", "chain_name": "BNB Smart Chain", "asset": "BNB"}
    models.save_case("bsc-1", case["address"], case, owner_hash=ownership.owner_hash(OWNER[ownership.OWNER_HEADER]))
    response = recheck(client, "bsc-1")
    assert response.status_code == 400 and "Ethereum and Tron" in response.json()["detail"]
    assert provider.reads == 0


def test_the_recheck_is_audited(client, monkeypatch):
    calls = []
    monkeypatch.setattr(audit, "record", lambda event, **kw: calls.append((event, kw)))
    recheck(client)
    assert calls == [("case.recheck", {"case_id": "tron-1", "detail": {
        "chain": "tron", "checked": 5, "matches": 5, "differs": 0, "not_found": 0, "error": 0, "saved": True}})]


# -- who may recheck -------------------------------------------------------------------
@pytest.mark.parametrize("headers", [STRANGER, {}])
def test_only_the_browser_that_traced_a_case_may_recheck_it(client, provider, headers):
    response = recheck(client, headers=headers)
    assert response.status_code == 403 and "traced this case" in response.json()["detail"]
    assert provider.reads == 0
    assert client.get("/trace/tron-1/recheck").json()["checked_at"] is None


def test_a_recorded_demo_is_rechecked_for_anyone_and_never_stored(client):
    body = recheck(client, "demo-12", headers=STRANGER).json()
    assert statuses(body) == ["matches"] * 5 and body["saved"] is False and body["case_id"] is None
    assert body["recorded_demo"] == 12
    assert client.get("/trace/demo-12/recheck").json()["checked_at"] is None


def test_a_public_demo_case_is_rechecked_for_anyone_and_never_stored(client):
    case = recorded(12)
    assert ownership.is_public(None, case["address"])
    models.save_case("public-12", case["address"], case, owner_hash=None)
    body = recheck(client, "public-12", headers=STRANGER).json()
    assert statuses(body) == ["matches"] * 5 and body["saved"] is False
    assert client.get("/trace/public-12/recheck").json()["checked_at"] is None


def test_a_recheck_that_reads_nothing_keeps_the_last_one_that_did(client, provider):
    assert recheck(client).json()["saved"] is True
    provider.down = True
    failed = recheck(client).json()
    assert statuses(failed) == ["error"] * 5 and failed["saved"] is False
    assert statuses(client.get("/trace/tron-1/recheck").json()) == ["matches"] * 5


def test_a_kept_recheck_counts_towards_the_stores_byte_caps(client):
    before = models.stored_bytes()
    for _ in range(2):  # the second replaces the first: counted once
        recheck(client)
        kept = json.dumps(models.recheck_for("tron-1")[1])
        assert models.stored_bytes() == before + len(kept)


@pytest.mark.parametrize("case_id", ["no-such-case", "demo-99"])
def test_an_unknown_case_is_not_found(client, case_id):
    assert recheck(client, case_id).status_code == 404
    assert client.get(f"/trace/{case_id}/recheck").status_code == (404 if case_id == "no-such-case" else 200)


def test_a_case_not_rechecked_yet_says_so(client):
    body = client.get("/trace/tron-1/recheck").json()
    assert body == {"case_id": "tron-1", "checked_at": None, "transfers": []}


# -- gated like POST /trace ------------------------------------------------------------
def test_a_connection_that_spent_its_share_of_the_allowance_is_refused_before_any_read(client, provider,
                                                                                       monkeypatch):
    monkeypatch.setattr(config, "TRONSCAN_CALLS_PER_DAY", 100)
    monkeypatch.setattr(config, "PROVIDER_CLIENT_SHARE_PERCENT", 7)  # 7 reads for one connection
    assert statuses(recheck(client).json()) == ["matches"] * 5
    assert sorted(statuses(recheck(client).json())) == ["error"] * 3 + ["matches"] * 2
    refused = recheck(client)
    assert refused.status_code == 503 and "This connection" in refused.json()["detail"]
    assert int(refused.headers["retry-after"]) > 0 and provider.reads == 7


def test_one_recheck_runs_at_a_time_per_connection_and_a_few_for_the_site(client, provider, monkeypatch):
    me = rate_limit.client_ip({}, "testclient")
    assert route.take_slot(me) is None
    try:
        refused = recheck(client)
        assert refused.status_code == 429 and "still running" in refused.json()["detail"]
    finally:
        route.release_slot(me)
    monkeypatch.setattr(config, "RECHECKS_RUNNING", 2)
    for other in ("one", "two"):
        assert route.take_slot(other) is None
    try:
        refused = recheck(client)
        assert refused.status_code == 429 and "already running" in refused.json()["detail"]
    finally:
        for other in ("one", "two"):
            route.release_slot(other)
    assert provider.reads == 0
    assert recheck(client).status_code == 200 and not route._running


def test_a_recheck_that_fails_gives_its_slot_back(client, monkeypatch):
    def broken(*_args):
        raise RuntimeError("boom")
    monkeypatch.setattr(second_provider, "recheck", broken)
    with pytest.raises(RuntimeError):
        recheck(client)
    assert not route._running


def test_one_connection_is_limited_per_hour(client, provider, monkeypatch):
    monkeypatch.setattr(rate_limit, "rechecks", rate_limit.SlidingWindowLimiter(1, 3600))
    assert recheck(client).status_code == 200
    refused = recheck(client)
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0
    assert "This connection" in refused.json()["detail"]
    assert provider.reads == 5


def test_the_whole_site_is_limited_per_hour(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "rechecks_total", rate_limit.SlidingWindowLimiter(1, 3600))
    assert recheck(client).status_code == 200
    refused = recheck(client, "eth-1")
    assert refused.status_code == 429 and "This site" in refused.json()["detail"]


def test_the_demo_code_guards_a_recheck_but_not_reading_one(client, provider, monkeypatch):
    monkeypatch.setattr(config, "DEMO_CODE", "river-otter-42")
    assert access.is_guarded("POST", "/trace/tron-1/recheck")
    assert recheck(client).status_code == 403 and provider.reads == 0
    assert recheck(client, headers={**OWNER, access.CODE_HEADER: "river-otter-42"}).status_code == 200
    assert client.get("/trace/tron-1/recheck").status_code == 200


def test_the_providers_daily_allowance_is_respected(client, provider, monkeypatch):
    monkeypatch.setattr(config, "TRONSCAN_CALLS_PER_DAY", 3)
    monkeypatch.setattr(config, "PROVIDER_CLIENT_SHARE_PERCENT", 0)
    body = recheck(client).json()
    assert statuses(body) == ["matches"] * 3 + ["error"] * 2 and provider.reads == 3
    refused = recheck(client)
    assert refused.status_code == 503 and "TronScan" in refused.json()["detail"]
    assert int(refused.headers["retry-after"]) > 0 and provider.reads == 3


def test_after_a_swap_the_route_to_it_and_the_swap_are_cited_in_the_asset_sent():
    seed, wallet, router, exchange = "0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40, "0x" + "4" * 40
    follow = {"chain": "ethereum", "asset": "USDT", "exchange": "Binance", "exchange_address": exchange,
              "trace_path": [{"address": wallet, "depth": 0},
                             {"address": exchange, "depth": 1, "tx_hashes": ["0x04"]}],
              "transfers": [{"hash": "0x04", "from": wallet, "to": exchange, "value_native": 5.0}]}
    case = {"address": seed, "chain": "ethereum", "asset": "ETH", "exchange": None, "trace_path": [],
            "transfers": [{"hash": "0x01", "from": seed, "to": wallet, "value_native": 1.0},
                          {"hash": "0x02", "from": wallet, "to": router, "value_native": 1.0},
                          {"hash": "0x03", "from": seed, "to": "0x" + "5" * 40, "value_native": 1.0}],
            "follow_ons": [{"asset": "USDT", "result": follow,
                            "swap": {"tx": "0x02", "sender": wallet, "asset_in": "ETH"},
                            "route": [{"address": seed, "depth": 0},
                                      {"address": wallet, "depth": 1, "tx_hashes": ["0x01"]}]}]}
    chain, rows = second_provider.cited_transfers(case)
    # The follow-on's hop into the exchange first, then the swap, then the route back to the reported address.
    assert chain == "ethereum"
    assert [(r["hash"], r["asset"]) for r in rows] == [("0x04", "USDT"), ("0x02", "ETH"), ("0x01", "ETH")]


def test_a_hash_cited_twice_is_read_once():
    first = recorded(12)["transfers"][0]
    answer, reads = answers("demo_12_tron.json")[first["hash"]], []

    def read(_chain, digest, _token):
        reads.append(digest)
        return answer

    checks = second_provider.check_transfers("tron", "USDT", [first, {**first, "to": "Telsewhere"}], read)
    assert reads == [first["hash"]] and [c.outcome for c in checks] == ["confirmed", "mismatch"]


def test_native_trx_cannot_be_reread_and_is_refused_before_any_read(client, provider):
    case = {**recorded(12), "asset": "TRX"}
    models.save_case("trx-1", case["address"], case, owner_hash=ownership.owner_hash(OWNER[ownership.OWNER_HEADER]))
    response = recheck(client, "trx-1")
    assert response.status_code == 400 and "native TRX" in response.json()["detail"]
    assert provider.reads == 0


def test_a_transfer_moved_by_a_contract_call_is_skipped_never_an_error(client, provider):
    case = recorded(12)
    case["transfers"][0]["internal"] = True
    models.save_case("internal-1", case["address"], case,
                     owner_hash=ownership.owner_hash(OWNER[ownership.OWNER_HEADER]))
    body = recheck(client, "internal-1").json()
    assert statuses(body) == ["matches"] * 4 and body["skipped"] == 1 and provider.reads == 4


# -- reading safely --------------------------------------------------------------------
def _gzip(data: bytes) -> bytes:
    import zlib
    packer = zlib.compressobj(9, zlib.DEFLATED, 31)
    return packer.compress(data) + packer.flush()


class _Chunks(httpx.SyncByteStream):
    def __init__(self, data: bytes) -> None:
        self.data = data

    def __iter__(self):
        for i in range(0, len(self.data), 16_384):
            yield self.data[i:i + 16_384]


@pytest.mark.parametrize("served", ["oversized", "gzip bomb"])
def test_a_body_past_the_size_cap_is_an_error_and_is_never_read_whole(client, provider, monkeypatch, served):
    monkeypatch.setattr(config, "PROVIDER_MAX_RESPONSE_BYTES", 100_000)
    first = recorded(12)["transfers"][0]["hash"]
    bomb = _gzip(b"0" * 20_000_000)
    provider.special[first] = ((lambda: httpx.Response(200, content=b"0" * 1_000_000)) if served == "oversized"
                               else lambda: httpx.Response(200, stream=_Chunks(bomb),
                                                           headers={"content-encoding": "gzip"}))
    body = recheck(client).json()
    assert next(t for t in body["transfers"] if t["hash"] == first)["status"] == "error"
    assert sorted(statuses(body)) == ["error"] + ["matches"] * 4
    assert {r.headers.get("accept-encoding") for r in provider.requests} == {"identity"}


def test_tronscan_rereads_share_the_pacer_live_traces_use_for_that_key(monkeypatch):
    monkeypatch.setattr(config, "TRONSCAN_API_KEY", "k")
    tags = tron_tags.TronScanTags("k")
    try:
        assert second_provider._pacer("tronscan") is tags._pacer
    finally:
        tags.close()


class CountingPacer(api_budget.SharedPacer):
    def __init__(self) -> None:
        super().__init__(0)
        self.waits = self.penalties = self.rewards = 0

    def wait(self, cost: float = 1.0) -> None:
        self.waits += 1

    def penalize(self) -> float:
        self.penalties += 1
        return 0.0

    def reward(self) -> None:
        self.rewards += 1


def test_every_read_waits_on_the_shared_pacer_and_a_refusal_widens_it(client, provider, monkeypatch):
    pacer = CountingPacer()
    monkeypatch.setattr(second_provider, "_pacer", lambda _provider: pacer)
    first = recorded(12)["transfers"][0]["hash"]
    provider.special[first] = lambda: httpx.Response(429, json={"Error": "too many requests"})
    body = recheck(client).json()
    assert sorted(statuses(body)) == ["error"] + ["matches"] * 4
    assert pacer.waits == provider.reads == 5 and pacer.penalties == 1 and pacer.rewards == 4


def test_no_read_outlasts_the_rechecks_clock(client, provider, monkeypatch):
    monkeypatch.setattr(second_provider, "RECHECK_SECONDS", 3)
    recheck(client)
    assert provider.requests and all(r.extensions["timeout"]["read"] <= 3 for r in provider.requests)




@pytest.mark.parametrize("decimals", [10**9, 18, "6", None, -6])
def test_a_token_decimals_the_case_does_not_use_is_an_error_and_is_never_raised_to_a_power(client, provider,
                                                                                            decimals):
    # TronScan's own "decimals" is never trusted: 10**1_000_000_000 alone would
    # take minutes and hundreds of MB inside the web server.
    first = recorded(12)["transfers"][0]["hash"]
    answer = provider.tron[first]
    provider.tron[first] = {**answer, "trc20TransferInfo": [{**answer["trc20TransferInfo"][0],
                                                              "amount_str": "1", "decimals": decimals}]}
    body = recheck(client).json()
    changed = next(t for t in body["transfers"] if t["hash"] == first)
    assert changed["status"] == "error" and "not in the shape expected" in changed["detail"]
    assert sorted(statuses(body)) == ["error"] + ["matches"] * 4


def test_a_transfer_without_decimals_uses_the_tokens_own(client, provider):
    first = recorded(12)["transfers"][0]["hash"]
    answer = provider.tron[first]
    item = {k: v for k, v in answer["trc20TransferInfo"][0].items() if k != "decimals"}
    provider.tron[first] = {**answer, "trc20TransferInfo": [item]}
    assert statuses(recheck(client).json()) == ["matches"] * 5
