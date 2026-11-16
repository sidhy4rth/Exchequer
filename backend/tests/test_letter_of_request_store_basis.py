"""The letter of request prints a label-store exchange row's basis (ADR-0011, ADR-0012; #348).

What matters here:
  * the lines are the report's and the exchange letter's (report.basis_lines), word for word, in the
    Statement of Facts right after the claim, which already says "own published address list, below";
  * a deposit row says it is an inference from public records that only the exchange can confirm;
  * no basis (every case today: the field is set only with EXCHEQUER_STORE_EXCHANGE_ROWS on) leaves the
    letter byte for byte what it was before this change.

Fixture values only: no real list, address or transaction.
"""
from __future__ import annotations

import hashlib

import pytest

from app import letters_of_request
from app.letters_of_request import draft
from app.report import basis_lines

from test_letters_of_request import DETAILS, flat
from test_request_letters import DEPOSIT, case

SOURCE = ("por:example:2026-11: Binance's own published address list (test fixture, no real list), published "
          "2026-11-01, retrieved 2026-11-02, SHA-256 " + "0" * 64)
OWN_ROW = {"kind": "exchange's own published list (PoR)", "source": SOURCE}
DEPOSIT_ROW = {**OWN_ROW, "deposit": {"sweeps_to": "0x" + "a1" * 20, "sweeps_to_label": "Binance 1",
                                      "sweep_tx": "0x" + "b2" * 32, "checked_on": "2026-11-15"}}
# The draft of case() with DETAILS, on main before #348 (date and signing-key lines fixed below).
BEFORE_SHA256 = "d1c3f71aa06e6a6c51df121eb0dfe316e8ae37b96e38b28c08e09e04d4fc5f7f"


@pytest.fixture
def steady(monkeypatch):
    """The date and the signing key's lines fixed, so two runs of a draft are comparable byte for byte."""
    monkeypatch.setattr(letters_of_request, "_today", lambda: "16 November 2026")
    monkeypatch.setattr(letters_of_request, "_verify_lines", lambda: ["Check the attached report (fixed)."])


def listed(basis, **over):
    return case(matches=[{"address": DEPOSIT, "label": "Binance Dep: 0xde9…", "attribution_basis": basis}], **over)


@pytest.mark.parametrize("result", [
    case(),
    case(matches=[{"address": DEPOSIT, "label": "Binance Dep: 0xde9…"}]),
    listed({"kind": "exchange's own published list (PoR)"}),  # no source: not a basis (report.store_basis)
    case(matches=[{"address": "0x" + "c3" * 20, "attribution_basis": OWN_ROW}]),  # another address's row
], ids=["no_matches", "no_basis", "no_source", "other_address"])
def test_without_a_basis_the_letter_is_byte_for_byte_as_before(steady, result):
    text = draft("case-1", result, DETAILS)
    assert hashlib.sha256(text.encode()).hexdigest() == BEFORE_SHA256
    assert "Listed by" not in text and "Sent funds to" not in text


def test_an_own_wallet_row_prints_the_reports_line_after_the_claim(steady):
    text = draft("case-1", listed(OWN_ROW), DETAILS)
    [line] = basis_lines(OWN_ROW, "Binance")
    assert flat(line) in flat(text) and flat(text).count("Listed by Binance") == 1
    facts = flat(text.split("Statement of Facts", 1)[1].split("(c) How the account was used", 1)[0])
    assert facts.index("own published address list, below).") < facts.index(flat(line))
    assert "Sent funds to" not in text
    # Never a hash split across lines: each must be copied whole.
    assert any("0" * 64 in ln for ln in text.splitlines())


def test_a_deposit_row_prints_the_sweep_as_an_inference_only_the_exchange_can_confirm(steady):
    text = draft("case-1", listed(DEPOSIT_ROW, attribution_inferred=True), DETAILS)
    lines = basis_lines(DEPOSIT_ROW, "Binance")
    assert len(lines) == 2 and all(flat(line) in flat(text) for line in lines)
    assert "This is an inference from public records, which only Binance can confirm." in flat(text)
    assert any("0x" + "b2" * 32 in ln for ln in text.splitlines())
    assert "which only Binance can confirm" in flat(text.split("(c) How the account was used", 1)[0])

