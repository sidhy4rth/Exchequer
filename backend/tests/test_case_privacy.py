"""A case link opens the case; the complaint's particulars stay with the
browser that traced it (app/case_privacy.py).

The case id is printed in every letter and report, which go to exchanges and
to Tether, and holding it is what opens the case. That must keep working --
a letter's reference has to lead back to the evidence. But a payment-mode
case also holds the victim's NCRP acknowledgement number and the wallet they
paid from, and those were returned to anyone with the id. Now only the
owner's browser gets them; everyone else gets the same case with those two
fields empty and a note saying so -- and, since a payment's transaction hash,
block or time names its sender on any block explorer, without those either.

Throwaway SQLite file and a stub pipeline: no network.
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import jobs, models, ownership, pipeline
from app.main import app

OWNER_KEY = "o" * 32
OWNER = {ownership.OWNER_HEADER: OWNER_KEY}
OTHER = {ownership.OWNER_HEADER: "x" * 32}
NCRP = "31911250012345"
PAYER = "0x71c0" + "ab" * 16 + "9f3e"
SCAMMER = "0x" + "5" * 40
PAYMENT_CASE = {
    "address": SCAMMER, "chain": "ethereum", "exchange": "Binance", "exchange_address": "0x" + "e" * 40,
    "intake": {"mode": "payment", "ncrp_ack": NCRP,
               "payments": [{"tx_hash": "0x" + "c" * 64, "from": PAYER, "amount": 1.5, "timestamp": 1}]},
}
ADDRESS_CASE = {"address": SCAMMER, "chain": "ethereum", "exchange": "Binance"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'p.db'}", future=True))
    with TestClient(app) as c:
        owner_hash = hashlib.sha256(OWNER_KEY.encode()).hexdigest()
        models.save_case("pay-case", SCAMMER, PAYMENT_CASE, owner_hash=owner_hash)
        models.save_case("addr-case", SCAMMER, ADDRESS_CASE, owner_hash=owner_hash)
        yield c


@pytest.mark.parametrize("headers", [{}, OTHER])
def test_a_case_link_still_opens_but_without_the_particulars(client, headers):
    response = client.get("/trace/pay-case", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["exchange"] == "Binance"  # the letter's reference still leads to the evidence
    assert body["intake"]["ncrp_ack"] is None
    assert all(p["from"] is None for p in body["intake"]["payments"])
    assert body["intake"]["payments"][0]["amount"] == 1.5
    assert body["redacted"][:3] == ["intake.ncrp_ack", "intake.victim_address", "intake.payments[].from"]
    assert "intake.payments[].tx_hash" in body["redacted"]
    assert NCRP not in response.text and PAYER not in response.text


def test_the_owner_still_sees_everything(client):
    body = client.get("/trace/pay-case", headers=OWNER).json()
    assert body["intake"]["ncrp_ack"] == NCRP
    assert body["intake"]["payments"][0]["from"] == PAYER
    assert "redacted" not in body


def test_an_address_case_is_returned_as_stored_to_anyone(client):
    body = client.get("/trace/addr-case").json()
    assert body.pop("victim_flow")["status"] == "unavailable"  # built on read; this case has no graph
    assert body == ADDRESS_CASE


def test_the_stored_case_is_never_changed(client):
    client.get("/trace/pay-case")
    assert models.get_case("pay-case").result["intake"]["ncrp_ack"] == NCRP


@pytest.mark.parametrize("path", [
    "/trace/pay-case/report?format=json", "/trace/pay-case/report?format=text",
    "/trace/pay-case/graph?format=csv", "/trace/pay-case/graph?format=graphml",
    "/trace/pay-case/letter?to=exchange",
])
def test_exports_never_carry_the_ncrp_number(client, path):
    response = client.get(path)
    assert NCRP not in response.text


def test_a_finished_job_is_redacted_for_anyone_but_its_owner(client, monkeypatch):
    monkeypatch.setattr(pipeline, "run_trace", lambda request: dict(PAYMENT_CASE))
    started = client.post("/trace/jobs", json={"address": SCAMMER}, headers=OWNER).json()
    for _ in range(200):
        mine = client.get(f"/trace/jobs/{started['job_id']}", headers=OWNER).json()
        if mine["status"] != jobs.RUNNING:
            break
    assert mine["status"] == "done"
    assert mine["result"]["intake"]["ncrp_ack"] == NCRP
    for headers in ({}, OTHER):
        theirs = client.get(f"/trace/jobs/{started['job_id']}", headers=headers)
        assert theirs.json()["result"]["intake"]["ncrp_ack"] is None
        assert NCRP not in theirs.text and PAYER not in theirs.text


def test_the_victims_own_wallet_is_a_particular_too():
    # The complaint may give the victim's own paying wallet (intake.victim_address,
    # to check each payment's sender); it is as personal as the payer.
    from app.case_privacy import for_reader
    case = {**PAYMENT_CASE, "intake": {**PAYMENT_CASE["intake"], "victim_address": PAYER}}
    seen = for_reader(case, "owner-hash", "someone-else")
    assert seen["intake"]["victim_address"] is None and PAYER not in str(seen)
    assert for_reader(case, "owner-hash", "owner-hash")["intake"]["victim_address"] == PAYER


# -- the payments' hashes, blocks and times are particulars too (r2-g2-payment-intake-integrity-5-4) ----
# A transaction hash names its sender on any block explorer, and so does the
# block and second it landed in next to the reported address. So a reader
# who is not the owner gets none of them, from any route that serves the case.
from test_report import full_result  # noqa: E402

from app import report as report_module  # noqa: E402
from app.routes import evidence  # noqa: E402

PAID_AT = 1_699_123_457
SECOND_AT = PAID_AT + 9 * 86_400
PAY_HASH = "0x9e1f" + "ab" * 28 + "77d2"
PAY_HASH_2 = "0x4c08" + "cd" * 28 + "e51b"
PAY_BLOCK, PAY_BLOCK_2 = 18_498_765, 18_563_021
STRANGER = "0x" + "6" * 40


def _payment(tx_hash, amount, block, when):
    return {"tx_hash": tx_hash, "chain": "ethereum", "asset": "ETH", "amount": amount, "from": PAYER,
            "to": SCAMMER, "block": block, "timestamp": when, "found_by": "victim",
            "payer_label": None, "payer_is_victim": False}


def rich_payment_case():
    """A payment case as a real trace stores it: the payments, the wallet
    statement (whose credits list the same transfers), the seed's time
    window, and warnings that quote the hashes and the first payment's date."""
    result = full_result()
    result["address"] = SCAMMER
    result["intake"] = {"mode": "payment", "ncrp_ack": NCRP, "victim_address": PAYER,
                        "payments": [_payment(PAY_HASH, 1.5, PAY_BLOCK, PAID_AT),
                                     _payment(PAY_HASH_2, 0.5, PAY_BLOCK_2, SECOND_AT)]}
    result["reported_amount"] = 2.0
    result["graph"]["nodes"][0] = {"id": SCAMMER, "depth": 0, "window_start": PAID_AT}
    result["statement"] = {
        "debits": [{"tx": "0x" + "d1" * 32, "time": PAID_AT - 60, "amount": 5.0, "counterparty": STRANGER,
                    "before_window": True},
                   {"tx": "0xaaa", "time": 1_700_000_000, "amount": 4.5, "counterparty": "0x" + "2" * 40,
                    "before_window": False}],
        "credits": [{"tx": PAY_HASH, "time": PAID_AT, "amount": 1.5, "counterparty": PAYER,
                     "lookalike": False, "before_window": False},
                    {"tx": PAY_HASH_2, "time": SECOND_AT, "amount": 0.5, "counterparty": PAYER,
                     "lookalike": False, "before_window": False}],
        "poisoning": [], "rows_per_side": 25, "lookalikes": 0, "window_start": PAID_AT,
    }
    result["warnings"] = [
        "Payment 0x9e1f…77d2 was not sent from the victim's wallet entered with the complaint. "
        "Check it is the victim's payment before relying on the time window.",
        "The first payment (4 Nov 2023) is 9 days before the next; the trace reads the wallet from the "
        "first. Check it belongs to this complaint.",
        "Some unrelated warning stays as it is.",
    ]
    return result


# Everything a block explorer could turn back into the victim's wallet.
LINKS = [PAY_HASH, PAY_HASH_2, PAY_HASH[2:], PAY_HASH[:6], "77d2", PAY_HASH_2[:6], str(PAY_BLOCK),
         str(PAY_BLOCK_2), str(PAID_AT), str(SECOND_AT), report_module._when(PAID_AT),
         report_module._when(SECOND_AT), "4 Nov 2023", NCRP, PAYER, PAYER[2:]]


@pytest.fixture
def rich(client):
    owner_hash = hashlib.sha256(OWNER_KEY.encode()).hexdigest()
    models.save_case("rich-case", SCAMMER, rich_payment_case(), owner_hash=owner_hash)
    return client


def leaks(text):
    return [needle for needle in LINKS if needle.lower() in text.lower()]


@pytest.mark.parametrize("path", [
    "/trace/rich-case",
    "/trace/rich-case/report?format=json", "/trace/rich-case/report?format=text",
    "/trace/rich-case/graph?format=csv", "/trace/rich-case/graph?format=graphml",
    "/trace/rich-case/letters", "/trace/rich-case/letter?to=exchange",
    "/trace/rich-case/letter?to=exchange-freeze",
    "/trace/rich-case/requests", "/cases", "/cases/correlate", "/cases/correlate?case_id=rich-case",
])
@pytest.mark.parametrize("headers", [{}, OTHER], ids=["anonymous", "another-browser"])
def test_no_route_gives_a_non_owner_anything_that_leads_to_the_victims_wallet(rich, path, headers):
    response = rich.get(path, headers=headers)
    assert response.status_code == 200, response.text
    assert leaks(response.text) == []


def test_the_pdf_is_made_from_the_redacted_report_for_a_non_owner(rich, monkeypatch):
    seen = []
    monkeypatch.setattr(evidence, "render_pdf", lambda built, text: seen.append((built, text)) or b"%PDF-")
    for headers in ({}, OTHER):
        assert rich.get("/trace/rich-case/report?format=pdf", headers=headers).status_code == 200
    assert seen and all(leaks(repr(built) + text) == [] for built, text in seen)


def test_a_non_owner_still_sees_how_much_was_paid_and_why_it_is_withheld(rich):
    body = rich.get("/trace/rich-case", headers=OTHER).json()
    payments = body["intake"]["payments"]
    assert [p["amount"] for p in payments] == [1.5, 0.5] and body["reported_amount"] == 2.0
    assert all(p["tx_hash"] is None and p["block"] is None and p["timestamp"] is None for p in payments)
    for field in ("intake.payments[].tx_hash", "intake.payments[].block", "intake.payments[].timestamp"):
        assert field in body["redacted"]
    assert body["statement"]["debits"] and body["statement"]["credits"] == []
    assert "Some unrelated warning stays as it is." in body["warnings"]
    text = rich.get("/trace/rich-case/report?format=text", headers=OTHER).text
    assert "VICTIM'S PAYMENTS" in text and "withheld" in text
    letter = rich.get("/trace/rich-case/letter?to=exchange", headers=OTHER).text
    assert "2 transfers" in letter and "withheld" in letter


def test_the_owner_still_gets_the_hashes_blocks_and_times_everywhere(rich):
    body = rich.get("/trace/rich-case", headers=OWNER).json()
    body.pop("victim_flow")  # built on read (tests/test_victim_flow_read.py)
    assert body == rich_payment_case()
    text = rich.get("/trace/rich-case/report?format=text", headers=OWNER).text
    assert PAY_HASH in text and report_module._when(PAID_AT) in text
    letter = rich.get("/trace/rich-case/letter?to=exchange", headers=OWNER).text
    assert PAY_HASH in letter and PAY_HASH_2 in letter


def test_the_owner_and_a_stranger_get_different_reports_from_the_cache(rich):
    stranger = rich.get("/trace/rich-case/report?format=text").text
    owner = rich.get("/trace/rich-case/report?format=text", headers=OWNER).text
    again = rich.get("/trace/rich-case/report?format=text").text
    assert PAY_HASH in owner and PAY_HASH not in stranger and again == stranger


def test_a_finished_payment_job_hides_the_hashes_from_a_non_owner(client, monkeypatch):
    monkeypatch.setattr(pipeline, "run_trace", lambda request: rich_payment_case())
    started = client.post("/trace/jobs", json={"address": SCAMMER}, headers=OWNER).json()
    for _ in range(200):
        mine = client.get(f"/trace/jobs/{started['job_id']}", headers=OWNER)
        if mine.json()["status"] != jobs.RUNNING:
            break
    assert PAY_HASH in mine.text
    for headers in ({}, OTHER):
        assert leaks(client.get(f"/trace/jobs/{started['job_id']}", headers=headers).text) == []


def test_the_redacted_copy_still_meets_the_case_contract():
    from app.case_privacy import for_reader
    from app.contracts import read_case
    seen = read_case(for_reader(rich_payment_case(), "owner-hash", "someone-else"))
    assert [p.tx_hash for p in seen.intake.payments] == [None, None]


@pytest.mark.parametrize("headers", [{}, OTHER, OWNER], ids=["anonymous", "another-browser", "owner"])
def test_every_readers_pdf_of_a_payment_case_verifies_with_matching_pages(rich, headers):
    """The redacted copy a stranger downloads is signed as it is printed, so /verify
    calls it genuine and its page 1 matches; the owner's full copy too."""
    pdf = rich.get("/trace/rich-case/report?format=pdf", headers=headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    checked = rich.post("/verify", content=pdf.content, headers={"Content-Type": "application/pdf"}).json()
    assert checked["status"] == "genuine", checked
    assert checked["pdf"]["pages_match"] is True, checked["pdf"]["problems"]
    if headers is not OWNER:
        assert leaks(repr(checked)) == []
