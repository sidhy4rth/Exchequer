"""The crypto summary in the CFCFRMS SOP's 9.4 terms (app/sop_summary.py and
routes/sop_summary.py, flag EXCHEQUER_SOP_SUMMARY).

What must hold: with the flag off nothing answers; the summary holds only
what the case holds (the contract fixtures are real recorded traces); the
officer's CFCFRMS answer picks which SOP paragraph is quoted and is stored
nowhere but as one of three words in the audit row; and no NCRP number is
ever filled in, logged or audited."""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import config, models, ownership, sop_summary
from app.main import app

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contract"
OWNER = {ownership.OWNER_HEADER: "a" * 32}
NCRP = "31234567890123"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_an_exchange_wallet_case_names_the_address_how_it_was_attributed_and_the_hashes_into_it():
    case = fixture("exchange_wallet")
    text = sop_summary.summary("case-1", case, "unknown")
    att = case["attribution"]
    assert f"Exchange: {att['exchange']}" in text
    assert f"Exchange address (wallet ID): {att['address']}" in text
    assert f'wallet Binance operates itself (label: "{att["label"]}"); it belongs to no one customer' in text
    into = [t for t in case["transfers"] if t["to"] == att["address"]]
    assert into and all(t["hash"] in text for t in into[:sop_summary.LISTED])
    assert "not a person: only the exchange can say" in text
    assert "Reported paid by the victim: not given" in text  # an address-only trace states no amount paid
    assert "Estimated to have reached the exchange" in text and "26,405.277104 USDT" in text


def test_an_inferred_deposit_says_it_is_inferred_and_a_live_tag_says_it_is_unconfirmed():
    inferred = sop_summary.summary("c", fixture("deposit_inferred"), "unknown")
    assert "inferred, not confirmed" in inferred and "0xa79f7f7c92979d1139b66913fac2603295ec7866" in inferred
    tagged = sop_summary.summary("c", fixture("exchange_wallet.live_tag"), "unknown")
    assert "Exchequer has not confirmed it" in tagged and "Flipster" in tagged


def test_a_case_that_reached_no_exchange_says_so_and_names_none():
    text = sop_summary.summary("c", fixture("no_attribution"), "no")
    assert "Exchange (VASP) reached: none" in text and "Exchange address" not in text


def test_an_incoming_trace_never_says_the_money_reached_the_exchange_it_came_from():
    # An incoming trace follows where the reported address's money came from
    # (report.py: "Part of the money came from"): its exchange sent money.
    case = fixture("exchange_wallet")
    case["direction"] = "incoming"
    text = sop_summary.summary("c", case, "unknown")
    assert "Exchange (VASP) reached: none" in text and "where the reported address's money came from" in text
    assert "Estimated to have reached the exchange" not in text and "Transfers into the exchange address" not in text


@pytest.mark.parametrize("answer, quoted, not_quoted", [
    ("yes", ["SOP 9.4(ii)"], ["SOP 9.4(iv)"]),
    ("no", ["SOP 9.4(iv)", "Sahyog Portal", "Section 106(1) of BNSS"], ["SOP 9.4(ii)"]),
    ("unknown", ["SOP 9.4(ii)", "SOP 9.4(iv)"], []),
])
def test_the_officers_answer_picks_the_sop_paragraph_quoted(answer, quoted, not_quoted):
    text = sop_summary.summary("c", fixture("exchange_wallet"), answer)
    assert f"Is this exchange on CFCFRMS? {sop_summary.ANSWERS[answer]} (the officer's answer" in text
    assert "quoted, not applied" in text and "no legal advice" in text and sop_summary.SOURCE in text
    for q in quoted:
        assert q in text
    for q in not_quoted:
        assert q not in text


def test_the_ncrp_number_is_a_blank_even_when_the_case_holds_one():
    case = fixture("exchange_wallet")
    case["intake"]["ncrp_ack"] = NCRP
    text = sop_summary.summary("c", case, "unknown")
    assert sop_summary.NCRP_BLANK in text and NCRP not in text


def test_a_payment_case_lists_the_payments_and_withholds_what_the_reader_may_not_see():
    case = fixture("exchange_wallet")
    pay = {"tx_hash": "ab" * 32, "chain": "tron", "asset": "USDT", "amount": 500.0, "from": None,
           "to": case["address"], "timestamp": 1708700000}
    case["intake"] = {"mode": "payment", "payments": [pay], "ncrp_ack": None}
    case["reported_amount"] = 500.0
    text = sop_summary.summary("c", case, "unknown")
    assert "Reported paid by the victim: 500 USDT" in text and f"- {'ab' * 32}  500 USDT" in text
    hidden = copy.deepcopy(case)
    hidden["intake"]["payments"][0].update(tx_hash=None, timestamp=None)
    assert f"- {sop_summary.WITHHELD}  500 USDT  {sop_summary.WITHHELD}" in sop_summary.summary("c", hidden, "no")


# -- the routes ----------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))
    models.init_db()
    case = fixture("exchange_wallet")
    case["intake"]["ncrp_ack"] = NCRP
    models.save_case("case-1", case["address"], case)
    return TestClient(app)


def test_with_the_flag_off_nothing_answers(client, monkeypatch):
    monkeypatch.setattr(config, "SOP_SUMMARY", False)
    assert client.get("/sop-summary").status_code == 404
    assert client.post("/trace/case-1/sop-summary", json={"on_cfcfrms": "yes"}, headers=OWNER).status_code == 404
    with models.session() as s:
        assert not s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "case.sop_summary_copy")).all()


def test_the_flag_is_off_by_default():
    # The test run sets no EXCHEQUER_ variables, so this is the shipped default.
    assert config.FLAGS["EXCHEQUER_SOP_SUMMARY"]["on"] is False
    assert config.FLAGS["EXCHEQUER_SOP_SUMMARY"]["about"].startswith("Feature 8")


def test_with_the_flag_on_the_summary_is_plain_text_and_audited_without_free_text(client, monkeypatch, caplog):
    monkeypatch.setattr(config, "SOP_SUMMARY", True)
    caplog.set_level(logging.DEBUG)
    assert client.get("/sop-summary").json() == {"enabled": True}
    r = client.post("/trace/case-1/sop-summary", json={"on_cfcfrms": "no"}, headers=OWNER)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert r.headers["cache-control"] == "no-store"
    assert "SOP 9.4(iv)" in r.text and NCRP not in r.text
    with models.session() as s:
        rows = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "case.sop_summary_copy")).all()
    assert [(row.case_id, json.loads(row.detail)) for row in rows] == [("case-1", {"on_cfcfrms": "no"})]
    assert NCRP not in caplog.text


def test_the_route_refuses_another_answer_free_text_and_an_unknown_case(client, monkeypatch):
    monkeypatch.setattr(config, "SOP_SUMMARY", True)
    assert client.post("/trace/case-1/sop-summary", json={"on_cfcfrms": "maybe"}, headers=OWNER).status_code == 422
    assert client.post("/trace/case-1/sop-summary", json={"ncrp": NCRP}, headers=OWNER).status_code == 422
    assert client.post("/trace/nope/sop-summary", json={}, headers=OWNER).status_code == 404


def test_the_case_page_fills_the_same_ncrp_blank_the_server_writes():
    # CryptoSummary.jsx replaces this exact line with the number the officer
    # types; if the two drifted, a typed number would silently be left out.
    page = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "case" / "CryptoSummary.jsx"
    assert f"export const NCRP_BLANK = '{sop_summary.NCRP_BLANK}'" in page.read_text()
