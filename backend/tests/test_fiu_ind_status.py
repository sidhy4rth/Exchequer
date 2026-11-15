"""FIU-IND's published facts about an exchange: the data file, and one dated, sourced note, only with the flag on.

The note is about the exchange's standing with FIU-IND (the 9 Mar 2026 list of
registered VDA service providers in Lok Sabha USQ 5805, and the notices and
penalties FIU-IND announced), never about a customer, and changes nothing else:
with the flag off there is no note (app/fiu_ind_status.py,
data/fiu_ind_status.json). Where the report and letters print it:
test_fiu_ind_note_outputs.py.
"""
from __future__ import annotations

import json
import re

import pytest

from app import config, fiu_ind_status
from app.exchange_matcher import ExchangeMatcher

DOCUMENT = json.loads((config.DATA_DIR / fiu_ind_status.STATUS_FILE).read_text(encoding="utf-8"))
ENTRIES = DOCUMENT["exchanges"]
LS_5805 = "https://sansad.in/getFile/loksabhaquestions/annex/187/AU5805_lMTYNK.pdf?source=pqals"
PIB_DEC_2023 = "https://pib.gov.in/PressReleasePage.aspx?PRID=1991372"
ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


@pytest.fixture(autouse=True)
def _fresh():
    fiu_ind_status.clear_cache()
    yield
    fiu_ind_status.clear_cache()


# -- the data file --------------------------------------------------------------------
def test_the_flag_is_registered_and_off_by_default():
    assert config.FIU_IND_NOTE is False and config.FLAGS["EXCHEQUER_FIU_IND_NOTE"]["on"] is False


def test_the_register_snapshot_is_dated_and_sourced():
    register = DOCUMENT["_meta"]["register"]
    assert register == {"as_of": "2026-03-09", "source": "Lok Sabha USQ 5805, Annexure-I", "url": LS_5805}


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_every_entry_has_dated_sourced_facts_only(name):
    entry = ENTRIES[name]
    assert isinstance(entry["registered"], bool) and entry["named_by_source"]
    assert bool(entry.get("listed_as")) == entry["registered"]  # Annexure-I's entity name for each listed one
    facts = entry["actions"] + entry["penalties"]
    assert facts or entry["registered"]  # an entry says at least one thing a source dates
    for fact in facts:
        assert ISO.fullmatch(fact["date"]) and fact["url"].startswith("https://"), fact
        assert fact["text"] and fact["source"]
        assert not re.search(r"\billegal", fact["text"], re.I)  # FIU's words are not repeated as Exchequer's
    for fine in entry["penalties"]:
        assert re.fullmatch(r"[\d,]+", fine["amount_inr"]) and fine["amount_inr"] in fine["text"]
        assert "Order" in fine["source"] and "fiuindia.gov.in" in fine["url"]


def test_every_name_is_an_exchange_the_label_files_name():
    names = set()
    for chain in config.CHAINS.values():
        names |= {m["exchange"] for _, m in ExchangeMatcher.from_file(chain.labels_path, chain=chain.key).entries()}
    assert set(ENTRIES) <= names  # an entry for an exchange no file names would be a typo


def test_the_four_exchanges_on_both_annexures_are_listed_as_registered():
    registered = {name for name, entry in ENTRIES.items() if entry["registered"]}
    assert {"Binance", "KuCoin", "Bybit", "Coinbase"} <= registered
    assert registered == {"Binance", "KuCoin", "Bybit", "Coinbase", "CoinDCX", "Unocoin", "WazirX", "CoinSwitch"}


# -- flag on: the note for a listed exchange, nothing for any other -----------------------------
@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(config, "FIU_IND_NOTE", True)


def test_the_note_states_the_facts_and_their_sources(on):
    found = fiu_ind_status.note("Kraken")
    assert found == {
        "text": ("Kraken was not on FIU-IND's list of registered VDA service providers as of 9 Mar 2026 "
                 "(Lok Sabha USQ 5805, Annexure-I); on 28 Dec 2023 FIU-IND announced a show-cause notice to it "
                 "under section 13 of the PMLA and that it had written to MeitY to block its URLs "
                 "(PIB release 1991372)."),
        "sources": [LS_5805, PIB_DEC_2023]}
    bybit = fiu_ind_status.note("Bybit")["text"]
    assert bybit.startswith("Bybit, listed as Bybit Fintech Limited, was on FIU-IND's list")
    assert bybit.index("7 May 2024") < bybit.index("31 Jan 2025")  # the facts in date order
    assert "imposed a penalty of Rs 9,27,00,000" in bybit


def test_flag_off_there_is_no_note():
    assert config.FIU_IND_NOTE is False and fiu_ind_status.note("Kraken") is None


@pytest.mark.parametrize("name", ["FTX", "Delta Exchange", "", None])
def test_an_exchange_with_no_entry_gets_no_note(on, name):
    assert fiu_ind_status.note(name) is None


@pytest.mark.parametrize("name", ["Kraken", "kraken", "BitMEX (defunct)", "Huobi / HTX", "CoinEx (winding down)"])
def test_the_note_is_found_by_name_as_closure_is(on, name):
    assert fiu_ind_status.note(name)


def test_a_missing_or_malformed_file_gives_no_note(on, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert fiu_ind_status.note("Kraken") is None
    (tmp_path / fiu_ind_status.STATUS_FILE).write_text('{"exchanges": {}}')
    fiu_ind_status.clear_cache()
    assert fiu_ind_status.note("Kraken") is None  # no register snapshot
    meta = {"register": DOCUMENT["_meta"]["register"]}
    (tmp_path / fiu_ind_status.STATUS_FILE).write_text(json.dumps(
        {"_meta": meta, "exchanges": {"Kraken": {"registered": False, "actions": [{"text": "undated"}]}}}))
    fiu_ind_status.clear_cache()
    assert fiu_ind_status.note("Kraken") is None  # a fact with no date or URL is never shown
