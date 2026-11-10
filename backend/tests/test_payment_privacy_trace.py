"""A real payment trace, read by someone else, names nothing that leads to the victim's payment.

Before (r2-g2-payment-intake-integrity-5-0 and -5-4, 8 Nov check): the
reported wallet is read from the payment's block onward (R1), and that read
is in the evidence manifest -- "...&startblock=<payment block>" on Etherscan,
"fromBlock": "<payment block in hex>" on NodeReal, "min_timestamp=<payment
time in ms>" on TronGrid. case_privacy hid the payment's hash, block and time
everywhere else, but not there: GET /trace/{id}, the JSON, text and PDF
reports and the letters all gave the block to anyone holding the case id, and
the block (or time) with the reported address names the victim's payment, and
its sender, on any explorer. The privacy tests used a hand-built case whose
evidence had no such read, so they never saw it.

Here each chain's real client runs a payment-mode run_trace over a stubbed
provider (httpx.MockTransport: no network), the case is stored under its
owner's key, and every route is read without that key.
"""
from __future__ import annotations

import hashlib
import io
import json
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine

from app import api_budget, case_privacy, config, models, ownership
from app import pipeline as main
from app import report as report_module
from app.etherscan_client import EtherscanClient
from app.evidence import sha256_hex
from app.main import app
from app.nodereal_client import NoderealClient
from app.pipeline import TraceRequest, run_trace
from app.tron_client import TronClient

from conftest import addr

OWNER_KEY = "o" * 32
OWNER = {ownership.OWNER_HEADER: OWNER_KEY}
OTHER = {ownership.OWNER_HEADER: "x" * 32}
NCRP = "31911250012345"
DAY = 86_400


# -- Ethereum (Etherscan) -------------------------------------------------------------
ETH_SEED, ETH_VICTIM, ETH_CASHOUT = addr("5ca"), addr("71c"), addr("ca50")
ETH_PAID_AT, ETH_BLOCK = 1_699_123_457, 18_498_765
ETH_PAY = "0x9e1f" + "ab" * 28 + "77d2"


def _etherscan_rows() -> list[dict]:
    rows = []

    def row(tx, frm, to, eth, at, block):
        rows.append({"hash": tx, "from": frm, "to": to, "value": str(int(eth * 10**18)), "timeStamp": str(at),
                     "blockNumber": str(block), "isError": "0", "txreceipt_status": "1", "input": "0x"})

    row("0x" + "e1" * 32, addr("0dd"), ETH_SEED, 3.0, ETH_PAID_AT - 9 * DAY, ETH_BLOCK - 64_000)  # older money
    row(ETH_PAY, ETH_VICTIM, ETH_SEED, 10.0, ETH_PAID_AT, ETH_BLOCK)  # the victim's payment
    row("0x" + "e2" * 32, ETH_SEED, ETH_CASHOUT, 9.99, ETH_PAID_AT + 2 * DAY, ETH_BLOCK + 14_400)
    for i in range(240):  # a busy wallet: the cash-out is past the newest page
        row("0x%064x" % (0x1000 + i), addr("%x" % (0x1000 + i)), ETH_SEED, 0.5,
            ETH_PAID_AT + 3 * DAY + i * 60, ETH_BLOCK + 22_000 + i * 5)
    return rows


def _etherscan_source():
    rows = _etherscan_rows()

    def handler(request):
        p = dict(request.url.params)
        if p.get("action") == "balance":
            return httpx.Response(200, json={"status": "1", "message": "OK", "result": "0"})
        if p.get("action") != "txlist":
            return httpx.Response(200, json={"status": "0", "message": "No transactions found", "result": []})
        who, start = p["address"].lower(), int(p.get("startblock", 0))
        end = int(p.get("endblock", 10**9))
        found = [r for r in rows if who in (r["from"], r["to"]) and start <= int(r["blockNumber"]) <= end]
        found.sort(key=lambda r: int(r["blockNumber"]), reverse=p.get("sort") == "desc")
        found = found[:int(p.get("offset", 1000))]
        if not found:
            return httpx.Response(200, json={"status": "0", "message": "No transactions found", "result": []})
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": found})

    @contextmanager
    def open_source(chain, asset):
        yield EtherscanClient(api_key="k-privacy", chain_id=1, min_interval=0.0, include_internal=False,
                              client=httpx.Client(transport=httpx.MockTransport(handler)))
    return open_source


# -- BSC (NodeReal) -------------------------------------------------------------------
BSC_SEED, BSC_VICTIM, BSC_EARLIER, BSC_CASHOUT = addr("b5ca"), addr("b71c"), addr("b07e"), addr("bca5")
BSC_BLOCK = 37_801_234
BSC_PAY = "0x4c08" + "cd" * 28 + "e51b"
BSC_TIP = BSC_BLOCK + 2_000_000  # paid before NodeReal's recent window: read from the payment's block


def _bsc_time(block: int) -> int:
    return 1_700_000_000 + (block - 37_000_000) * 3


BSC_PAID_AT = _bsc_time(BSC_BLOCK)


def _nodereal_source():
    rows = [
        ("0x" + "b1" * 32, BSC_EARLIER, BSC_SEED, 3.0, BSC_BLOCK - 90_000),   # someone else's money, earlier
        (BSC_PAY, BSC_VICTIM, BSC_SEED, 10.0, BSC_BLOCK),                     # the victim's payment
        ("0x" + "b2" * 32, BSC_SEED, BSC_CASHOUT, 9.9, BSC_BLOCK + 60_000),   # the victim's money, on
    ]

    def handler(request):
        body = json.loads(request.content)
        method, params = body["method"], body["params"]

        def answer(result):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})
        if method == "eth_blockNumber":
            return answer(hex(BSC_TIP))
        if method == "eth_getTransactionCount":
            who, block = params[0], int(params[1], 16)
            return answer(hex(sum(1 for r in rows if r[1] == who and r[4] <= block)))
        if method == "eth_getBlockByNumber":
            return answer({"timestamp": hex(_bsc_time(int(params[0], 16)))})
        if method != "nr_getAssetTransfers":
            return answer("0x0")
        q = params[0]
        lo, hi = int(q["fromBlock"], 16), int(q["toBlock"], 16)
        found = [r for r in rows if lo <= r[4] <= hi and (q.get("fromAddress") == r[1] or q.get("toAddress") == r[2])]
        found.sort(key=lambda r: r[4], reverse=q.get("order", "desc") == "desc")
        return answer({"transfers": [
            {"hash": r[0], "from": r[1], "to": r[2], "value": hex(int(r[3] * 10**18)), "decimal": 18,
             "blockNum": hex(r[4]), "blockTimeStamp": _bsc_time(r[4]), "asset": "BNB", "receiptsStatus": 1}
            for r in found][:int(q["maxCount"], 16)]})

    @contextmanager
    def open_source(chain, asset):
        yield NoderealClient(api_key="k-privacy", min_interval=0, max_retries=0,
                             client=httpx.Client(transport=httpx.MockTransport(handler)))
    return open_source


# -- Tron (TronGrid, USDT) --------------------------------------------------------------
USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRON_SEED, TRON_VICTIM = "THWYhwUQnBcKpwSxaXjqv18RPtSoK4C5Ph", "TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G"
TRON_EARLIER, TRON_CASHOUT = "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7", "TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts"
TRON_PAID_AT = 1_699_555_123
TRON_PAY = "7a" * 4 + "31" * 28


def _tron_source():
    rows = [
        ("5e" * 32, TRON_EARLIER, TRON_SEED, 300.0, TRON_PAID_AT - 9 * DAY),
        (TRON_PAY, TRON_VICTIM, TRON_SEED, 1_000.0, TRON_PAID_AT),
        ("6f" * 32, TRON_SEED, TRON_CASHOUT, 990.0, TRON_PAID_AT + 2 * DAY),
    ]
    # A busy wallet: its newest page of sends holds only later ones, so it is
    # read again from the payment's time.
    rows += [("%064x" % (0x7000 + i), TRON_SEED, TRON_EARLIER, 2.0, TRON_PAID_AT + 3 * DAY + i * 60)
             for i in range(240)]

    def handler(request):
        path, p = request.url.path, dict(request.url.params)
        if not path.endswith("/transactions/trc20"):
            return httpx.Response(200, content=json.dumps({"data": [], "meta": {}, "success": True}))
        who = path.split("/v1/accounts/", 1)[1].split("/", 1)[0]
        lo = int(p.get("min_timestamp", 0)) // 1000
        hi = int(p.get("max_timestamp", 10**13)) // 1000
        found = [r for r in rows if lo <= r[4] <= hi
                 and ((p.get("only_to") == "true" and r[2] == who) or (p.get("only_from") == "true" and r[1] == who)
                      or ("only_to" not in p and "only_from" not in p and who in (r[1], r[2])))]
        found.sort(key=lambda r: r[4], reverse=p.get("order_by", "").endswith("desc"))
        data = [{"transaction_id": r[0], "from": r[1], "to": r[2], "value": str(int(r[3] * 10**6)),
                 "block_timestamp": r[4] * 1000, "type": "Transfer",
                 "token_info": {"address": USDT, "decimals": 6, "symbol": "USDT"}} for r in found]
        start, size = int(p.get("fingerprint", 0)), int(p.get("limit", 200))
        meta = {"fingerprint": str(start + size)} if start + size < len(data) else {}  # TronGrid's cursor
        return httpx.Response(200, content=json.dumps({"data": data[start:start + size], "meta": meta,
                                                       "success": True}))

    @contextmanager
    def open_source(chain, asset):
        yield TronClient(api_key="k-privacy", contract_address=USDT, asset_symbol="USDT", token_decimals=6,
                         min_interval=0, max_retries=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    return open_source


def _day(ts: int) -> list[str]:
    moment = datetime.fromtimestamp(ts, tz=timezone.utc)
    return [f"{moment:%d %b %Y}", f"{moment.day} {moment:%b %Y}"]


# chain, asset, seed, victim, payment hash, (block, block as the request writes it), time, source
SCENARIOS = {
    "ethereum": ("ethereum", "ETH", ETH_SEED, ETH_VICTIM, ETH_PAY, [str(ETH_BLOCK)], ETH_PAID_AT,
                 _etherscan_source, f"startblock={ETH_BLOCK}"),
    "bsc": ("bsc", "BNB", BSC_SEED, BSC_VICTIM, BSC_PAY, [str(BSC_BLOCK), hex(BSC_BLOCK)], BSC_PAID_AT,
            _nodereal_source, f'"fromBlock": "{hex(BSC_BLOCK)}"'),
    "tron": ("tron", "USDT", TRON_SEED, TRON_VICTIM, TRON_PAY, [], TRON_PAID_AT,
             _tron_source, f"min_timestamp={TRON_PAID_AT * 1000}"),
}


def _needles(scenario: tuple) -> list[str]:
    _, _, _, victim, pay, blocks, paid_at, _, _ = scenario
    return [pay, pay.removeprefix("0x"), pay[:6], victim, victim.removeprefix("0x"), NCRP, *blocks,
            str(paid_at), str(paid_at * 1000), str((paid_at + 1) * 1000), report_module._when(paid_at),
            *_day(paid_at)]


def leaks(text: str, scenario: tuple) -> list[str]:
    return [n for n in _needles(scenario) if n.lower() in text.lower()]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'p.db'}", future=True))
    monkeypatch.setattr(config, "TX_INTAKE", True)
    monkeypatch.setattr(config, "TRONSCAN_API_KEY", "")
    monkeypatch.setattr(main, "detect_swaps", lambda *a, **k: [])
    with TestClient(app) as c:
        yield c


CASHOUTS = {"ethereum": ETH_CASHOUT, "bsc": BSC_CASHOUT, "tron": TRON_CASHOUT}


def _trace(monkeypatch, name: str) -> dict:
    from app.exchange_matcher import ExchangeMatcher

    chain, asset, seed, victim, pay, _, _, source, _ = SCENARIOS[name]
    monkeypatch.setattr(main, "open_source", source())
    # The cash-out is a labelled Binance deposit address, so the letters are written too.
    labels = {CASHOUTS[name]: {"exchange": "Binance", "label": "Binance deposit", "type": "deposit_wallet"}}
    monkeypatch.setattr(main, "get_matcher", lambda key: ExchangeMatcher(labels, chain=key))
    api_budget.reset()
    try:
        return run_trace(TraceRequest(address=seed, chain=chain, asset=asset, max_depth=2, follow_swaps=False,
                                      payments=[{"tx_hash": pay}], victim_address=victim, ncrp_ack=NCRP))
    finally:
        api_budget.reset()


@pytest.fixture(params=sorted(SCENARIOS))
def traced(request, client, monkeypatch):
    name = request.param
    result = _trace(monkeypatch, name)
    owner_hash = hashlib.sha256(OWNER_KEY.encode()).hexdigest()
    models.save_case(f"{name}-case", SCENARIOS[name][2], result, owner_hash=owner_hash)
    return client, name, result


def test_the_trace_really_reads_the_wallet_from_the_payment(traced):
    # Without this the rest proves nothing: the stored case holds the anchored
    # read, and the trace followed the victim's money to the cash-out.
    _, name, result = traced
    requests = [r["request"] for r in result["evidence"]["records"]]
    assert any(SCENARIOS[name][8] in r for r in requests), requests
    assert result["exchange"] == "Binance" and result["exchange_address"] == CASHOUTS[name]


ROUTES = [
    "/trace/{id}", "/trace/{id}/report?format=json", "/trace/{id}/report?format=text",
    "/trace/{id}/graph?format=csv", "/trace/{id}/graph?format=graphml",
    "/trace/{id}/letters", "/trace/{id}/letter?to=exchange", "/trace/{id}/requests",
    "/cases", "/cases/correlate", "/cases/correlate?case_id={id}",
]


@pytest.mark.parametrize("headers", [{}, OTHER], ids=["anonymous", "another-browser"])
def test_no_route_gives_a_stranger_the_payments_block_time_or_hash(traced, headers):
    client, name, _ = traced
    scenario = SCENARIOS[name]
    # Every letter the case offers, the urgent freeze letters among them.
    offered = [letter["to"] for letter in client.get(f"/trace/{name}-case/letters", headers=headers).json()["letters"]]
    assert "exchange-freeze" in offered and ("tether-freeze" in offered) == (name == "tron")
    for route in ROUTES + [f"/trace/{{id}}/letter?to={to}" for to in offered]:
        response = client.get(route.format(id=f"{name}-case"), headers=headers)
        assert response.status_code == 200, (route, response.text[:200])
        assert leaks(response.text, scenario) == [], route
    pdf = client.get(f"/trace/{name}-case/report?format=pdf", headers=headers)
    reader = PdfReader(io.BytesIO(pdf.content))
    pages = "".join(page.extract_text() for page in reader.pages)
    attached = "".join(d.decode() for ds in reader.attachments.values() for d in ds)
    assert leaks(pages + attached, scenario) == []


def test_the_redacted_copy_names_nothing_either(traced):
    # What the job route and every export are built from.
    _, name, result = traced
    seen = case_privacy.for_reader(result, "owner-hash", None)
    assert leaks(json.dumps(seen), SCENARIOS[name]) == []
    assert any("evidence" in field for field in seen["redacted"])


def test_the_owner_still_gets_the_reads_as_made(traced):
    client, name, result = traced
    body = client.get(f"/trace/{name}-case", headers=OWNER).json()
    assert body["evidence"] == result["evidence"]
    text = client.get(f"/trace/{name}-case/report?format=text", headers=OWNER).text
    assert SCENARIOS[name][8] in text and result["evidence"]["manifest_sha256"] in text


def test_a_strangers_manifest_is_over_what_it_prints_and_says_so(traced):
    client, name, result = traced
    report = client.get(f"/trace/{name}-case/report?format=json").json()
    evidence = report["evidence"]
    withheld = [r for r in evidence["records"] if r.get("withheld")]
    assert withheld and evidence["withheld"] == len(withheld)
    assert all("withheld" in r["request"] and r["sha256"] == "withheld" for r in withheld)
    # Anyone can recompute the manifest hash from the lines the copy prints...
    lines = sorted(f"{r['sha256']}  {r['provider']}  {r['request']}" for r in evidence["records"])
    assert evidence["manifest_sha256"] == sha256_hex("\n".join(lines))
    # ...which is not the owner's (that one covers the requests as made).
    assert evidence["manifest_sha256"] != result["evidence"]["manifest_sha256"]
    text = " ".join(client.get(f"/trace/{name}-case/report?format=text").text.split())
    assert f"withholds the block, time and page parameters of {len(withheld)}" in text
    assert evidence["manifest_sha256"] in text


@pytest.mark.parametrize("headers", [{}, OTHER, OWNER], ids=["anonymous", "another-browser", "owner"])
def test_every_readers_pdf_of_a_real_payment_trace_verifies(traced, headers):
    client, name, _ = traced
    pdf = client.get(f"/trace/{name}-case/report?format=pdf", headers=headers)
    checked = client.post("/verify", content=pdf.content, headers={"Content-Type": "application/pdf"}).json()
    assert checked["status"] == "genuine", checked
    assert checked["pdf"]["pages_match"] is True, checked["pdf"]["problems"]



@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_a_finished_payment_job_hides_the_anchored_reads_from_strangers(client, monkeypatch, name):
    # r2-g2-payment-intake-integrity-5-4: the job route returns the result
    # while the trace's browser waits for it; anyone else polling the job id
    # gets the redacted copy, evidence included.
    from app import jobs
    from app import pipeline

    result = _trace(monkeypatch, name)
    monkeypatch.setattr(pipeline, "run_trace", lambda request: result)
    chain, asset, seed = SCENARIOS[name][:3]
    started = client.post("/trace/jobs", json={"address": seed, "chain": chain, "asset": asset}, headers=OWNER).json()
    for _ in range(200):
        mine = client.get(f"/trace/jobs/{started['job_id']}", headers=OWNER)
        if mine.json()["status"] != jobs.RUNNING:
            break
    assert mine.json()["result"]["evidence"] == result["evidence"]  # the owner's browser gets the reads as made
    for headers in ({}, OTHER):
        assert leaks(client.get(f"/trace/jobs/{started['job_id']}", headers=headers).text, SCENARIOS[name]) == []


def test_a_message_dated_by_the_payment_is_not_given_to_strangers(client, monkeypatch):
    # "... sent no BNB since <day>": the day is how far back NodeReal searched,
    # which starts at the payment's block when it is older than the recent
    # window. Not reached by the scenarios above (their wallets moved the money
    # on), so the stored message is set to that wording here.
    result = _trace(monkeypatch, "bsc")
    day = _day(BSC_PAID_AT)[0]
    result["message"] = (f"This address sent no BNB since {day} — try one of the tokens. Exchequer "
                         "searched from the first payment's block.")
    models.save_case("quiet-case", BSC_SEED, result, owner_hash=hashlib.sha256(OWNER_KEY.encode()).hexdigest())
    for headers in ({}, OTHER):
        for route in ("/trace/quiet-case", "/trace/quiet-case/report?format=text",
                      "/trace/quiet-case/report?format=json"):
            assert leaks(client.get(route, headers=headers).text, SCENARIOS["bsc"]) == [], route
        assert "since the first payment" in client.get("/trace/quiet-case", headers=headers).json()["message"]
    assert client.get("/trace/quiet-case", headers=OWNER).json()["message"] == result["message"]
