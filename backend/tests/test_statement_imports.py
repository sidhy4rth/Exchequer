"""Statement rows kept with a case (app/statement_imports.py, routes/statements.py): suite feature 5.

The officer reads a bank or exchange statement in the browser and keeps only the
rows they confirmed. Every row here is synthetic: made-up narrations, a test
account number 9999000011112222 that no bank issues, references shaped like a
bank's but invented for the test. Exchange names are the repository's own label
names. Throwaway SQLite, no network.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from app import config, models, ownership, statement_imports
from app.auth import User
from app.statement_imports import StatementError

ALICE, BOB = "a" * 32, "b" * 32
H = {ownership.OWNER_HEADER: ALICE}
SEED = "abandon ability able about above absent absorb abstract absurd abuse access accident"
ACCOUNT = "9999000011112222"  # synthetic: a test account number, in narrations only

UTR_ROW = {"date": "2026-03-12", "direction": "debit", "amount": "250000.00",
           "reference": "SBINN26071000001", "narration": f"NEFT/SBINN26071000001/TEST PAYEE/A/C {ACCOUNT}",
           "counterparty": "TEST PAYEE", "reasons": ["amount_date", "utr"]}
EXCHANGE_ROW = {"date": "2026-03-13", "direction": "debit", "amount": "15000",
                "narration": "UPI/607200000001/COINDCX TEST/okaxis", "reasons": ["exchange"], "exchange": "CoinDCX"}


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))
    monkeypatch.setattr(config, "STATEMENT_IMPORT", True)
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    models.save_case("case-2", "0xother", {"address": "0xother"})


def viewer(key=ALICE, unit=None, officer=None):
    return User(id=f"officer-{officer}" if officer else "demo", role="officer", unit="Cyber Cell" if unit else None,
                owner_hash=ownership.owner_hash(key), demo=officer is None, officer_id=officer, unit_id=unit)


def save(rows, who=None, case="case-1", **more):
    who = who or viewer()
    fields = {"source": "bank", "currency": "INR", "rows": rows, **more}
    return statement_imports.create(who.owner_hash, case, fields, who)


# -- exchange names --------------------------------------------------------------------------
def test_the_names_are_the_label_files_own_less_ordinary_words():
    names = statement_imports.exchange_names()
    assert {"Binance", "CoinDCX", "Crypto.com", "Gate.io"} <= set(names)
    assert not {"Liquid", "Gemini", "Bullish", "Uphold"} & set(names)


def test_a_name_matches_only_as_a_whole_word_ignoring_case():
    names = ["CoinDCX", "Gate.io", "OKX"]
    assert statement_imports.names_in("UPI/607200000001/COINDCX TEST", names) == ["CoinDCX"]
    assert statement_imports.names_in("IMPS to gate.io account", names) == ["Gate.io"]
    # Silent on a name inside another word, a misspelling and an ordinary narration.
    assert statement_imports.names_in("NEFT/TEST/BOOKXPRESS", names) == []
    assert statement_imports.names_in("UPI/COINDXC/TEST", names) == []
    assert statement_imports.names_in("ATM WDL TEST BRANCH", names) == []


def test_a_row_naming_an_exchange_keeps_the_canonical_name():
    made = save([EXCHANGE_ROW])
    assert made["rows"][0]["exchange"] == "CoinDCX" and made["rows"][0]["reasons"] == ["exchange"]


@pytest.mark.parametrize("claim, narration", [
    ("Binanse", "UPI/607200000001/BINANSE TEST"),  # not a name the label files have
    ("CoinDCX", "UPI/607200000001/TEST SHOP"),  # a real name, but the narration does not give it
    ("Liquid", "HDFC LIQUID FUND TEST PURCHASE"),  # an ordinary word, never matched
])
def test_an_exchange_claim_is_refused_unless_the_row_names_a_canonical_exchange(claim, narration):
    with pytest.raises(StatementError, match="known exchange"):
        save([{**EXCHANGE_ROW, "exchange": claim, "narration": narration}])


# -- the rows ----------------------------------------------------------------------------------
def test_a_row_is_kept_as_given_with_its_reasons_in_a_fixed_order():
    made = save([{**UTR_ROW, "reasons": ["utr", "amount_date"]}], title="Victim's statement (synthetic)")
    row = made["rows"][0]
    assert row["amount"] == "250000" and row["reference"] == "SBINN26071000001"
    assert row["reasons"] == ["amount_date", "utr"] and made["row_count"] == 1


def test_a_transaction_hash_is_a_reference_though_it_is_64_hex():
    tx = "0x" + "ab" * 32  # shaped like a hash, as an exchange statement prints one; refers to nothing
    made = save([{"date": "2026-03-12", "time": "14:05", "direction": "credit", "amount": "1000.5",
                  "reference": tx.upper().replace("0X", "0x"), "reasons": ["tx_hash"]}], source="exchange", currency="usdt")
    assert made["rows"][0]["reference"] == tx and made["currency"] == "USDT"


@pytest.mark.parametrize("change, message", [
    ({"date": "12/03/2026"}, "YYYY-MM-DD"),
    ({"date": "2026-02-30"}, "YYYY-MM-DD"),
    ({"time": "25:00"}, "HH:MM"),
    ({"direction": "both"}, "debit or a credit"),
    ({"amount": "0"}, "above zero"),
    ({"amount": "2,50,000"}, "as a number"),
    ({"amount": True}, "as a number"),
    ({"reasons": []}, "why it is kept"),
    ({"reasons": ["hunch"]}, "why it is kept"),
    ({"reference": "", "reasons": ["utr"]}, "no reference"),
    ({"reasons": ["tx_hash"]}, "not one"),
    ({"reference": "SBIN N 2607"}, "up to 40 letters"),
    ({"narration": SEED}, "seed phrase"),
    ({"counterparty": "x" * 121}, "longer than 120"),
])
def test_a_bad_row_is_refused_with_its_number(change, message):
    with pytest.raises(StatementError, match=message):
        save([UTR_ROW, {**UTR_ROW, **change}])
    try:
        save([UTR_ROW, {**UTR_ROW, **change}])
    except StatementError as exc:
        assert str(exc).startswith("Row 2")


def test_the_statement_itself_is_checked():
    with pytest.raises(StatementError, match="what the statement is"):
        save([UTR_ROW], source="phone")
    with pytest.raises(StatementError, match="currency"):
        save([UTR_ROW], currency="rupees!")
    with pytest.raises(StatementError, match="at least one"):
        save([])
    with pytest.raises(StatementError, match="at most"):
        save([UTR_ROW] * (statement_imports.ROWS_MAX + 1))
    with pytest.raises(StatementError, match="No case"):
        save([UTR_ROW], case="nope")
    with pytest.raises(StatementError, match="seed phrase"):
        save([UTR_ROW], title=SEED)


def test_imports_are_read_by_their_browser_and_unit_only():
    save([UTR_ROW], who=viewer(ALICE, unit=7, officer=1))
    assert len(statement_imports.list_for(viewer(BOB, unit=7, officer=2), "case-1")) == 1
    assert statement_imports.list_for(viewer(BOB), "case-1") == []
    assert statement_imports.list_for(viewer(ALICE), "case-2") == []


def test_g7_statements_1_goes_down_and_up_again_keeping_the_cases():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    save([UTR_ROW])
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with models._engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.downgrade(settings, "g7_domain_lookups_1")
    assert "statement_imports" not in set(inspect(models._engine).get_table_names())
    assert models.get_case("case-1") is not None
    models.init_db()
    assert "statement_imports" in set(inspect(models._engine).get_table_names())


@pytest.mark.parametrize("reasons", [[["utr"]], [{"utr": 1}], 5, "utr", None])
def test_reasons_of_the_wrong_shape_are_refused_not_a_server_error(reasons):
    with pytest.raises(StatementError, match="Row 2: say why it is kept"):
        save([UTR_ROW, {**UTR_ROW, "reasons": reasons}])
