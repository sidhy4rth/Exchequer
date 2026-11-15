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
from datetime import date, timedelta

import pytest

from app import config, fiu_ind_status
from app.exchange_matcher import ExchangeMatcher

DOCUMENT = json.loads((config.DATA_DIR / fiu_ind_status.STATUS_FILE).read_text(encoding="utf-8"))
ENTRIES = DOCUMENT["exchanges"]
LS_5805 = "https://sansad.in/getFile/loksabhaquestions/annex/187/AU5805_lMTYNK.pdf?source=pqals"
PIB_DEC_2023 = "https://pib.gov.in/PressReleasePage.aspx?PRID=1991372"
ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
# The staleness check's clock. It is fixed so CI never starts failing by itself; move it
# forward when you re-check the sources (docs/flag-rollout.md, EXCHEQUER_FIU_IND_NOTE).
TODAY = date(2026, 11, 16)


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
    assert DOCUMENT["_meta"]["checked_on"] == "2026-11-15"  # all 33 entries read against their sources that day


def test_the_sources_were_checked_recently():
    # Fails, with what to do, once checked_on is more than STALE_AFTER_DAYS before TODAY.
    assert fiu_ind_status.staleness(TODAY) is None, fiu_ind_status.staleness(TODAY)


def test_the_staleness_check_fires_after_the_limit():
    checked = date.fromisoformat(DOCUMENT["_meta"]["checked_on"])
    assert fiu_ind_status.staleness(checked + timedelta(days=fiu_ind_status.STALE_AFTER_DAYS)) is None
    late = fiu_ind_status.staleness(checked + timedelta(days=fiu_ind_status.STALE_AFTER_DAYS + 1))
    assert late and "last checked on 2026-11-15" in late and "re-check every entry against its source" in late
    assert "docs/flag-rollout.md" in late and "update _meta.checked_on" in late


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
        "text": ("Kraken, in date order: on 28 Dec 2023 FIU-IND announced a show-cause notice to it under "
                 "section 13 of the PMLA and that it had written to MeitY to block its URLs (PIB release "
                 "1991372); as of 9 Mar 2026 Kraken was not on FIU-IND's list of registered VDA service "
                 "providers (Lok Sabha USQ 5805, Annexure-I). Exchequer last checked the sources on 15 Nov 2026."),
        "sources": [LS_5805, PIB_DEC_2023]}
    bybit = fiu_ind_status.note("Bybit")["text"]
    assert bybit.startswith("Bybit, in date order: on 7 May 2024 FIU-IND issued it a notice")
    assert bybit.index("7 May 2024") < bybit.index("31 Jan 2025") < bybit.index("as of 9 Mar 2026")  # in date order
    assert "imposed a penalty of Rs 9,27,00,000" in bybit
    assert "as of 9 Mar 2026 Bybit, listed as Bybit Fintech Limited, was on FIU-IND's list" in bybit


def test_coinbase_reads_in_date_order_each_clause_with_its_source(on):
    assert fiu_ind_status.note("Coinbase")["text"] == (
        "Coinbase, in date order: on 28 Aug 2024 FIU-IND issued it a notice under section 13 of the PMLA "
        "(FIU-IND Order 16/DIR/FIU-IND/2024); on 6 Mar 2025 FIU-IND issued it a warning under section 13(2)(a) "
        "of the PMLA, with no penalty, in an order that says Coinbase India Private Limited had ceased its "
        "operations in India (FIU-IND Order 16/DIR/FIU-IND/2024); as of 9 Mar 2026 Coinbase, listed as Coinbase "
        "India Private Limited, was on FIU-IND's list of registered VDA service providers (Lok Sabha USQ 5805, "
        "Annexure-I); on 30 Mar 2026 the Government told the Lok Sabha that FIU-IND had directed the takedown "
        "of its apps and URLs (Lok Sabha USQ 5805, Annexure-II). Exchequer last checked the sources on 15 Nov 2026.")


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_every_note_is_in_date_order_and_says_when_the_sources_were_checked(on, name):
    text = fiu_ind_status.note(name)["text"]
    assert text.endswith(". Exchequer last checked the sources on 15 Nov 2026.")
    days = [date.fromisoformat(f["date"]) for f in ENTRIES[name]["actions"] + ENTRIES[name]["penalties"]]
    days.append(date(2026, 3, 9))  # the register snapshot
    said = [f"{d.day} {d:%b %Y}" for d in sorted(days)]
    assert [text.index(d) for d in said] == sorted(text.index(d) for d in said)
    assert text.count("(") >= len(days)  # a source after every clause


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
    meta = {"register": DOCUMENT["_meta"]["register"], "checked_on": DOCUMENT["_meta"]["checked_on"]}
    (tmp_path / fiu_ind_status.STATUS_FILE).write_text(json.dumps(
        {"_meta": meta, "exchanges": {"Kraken": {"registered": False, "actions": [{"text": "undated"}]}}}))
    fiu_ind_status.clear_cache()
    assert fiu_ind_status.note("Kraken") is None  # a fact with no date or URL is never shown
    (tmp_path / fiu_ind_status.STATUS_FILE).write_text(json.dumps(
        {"_meta": {"register": meta["register"]}, "exchanges": {"Kraken": ENTRIES["Kraken"]}}))
    fiu_ind_status.clear_cache()
    assert fiu_ind_status.note("Kraken") is None  # no checked_on: the note could not say when it was checked
    assert "unusable" in fiu_ind_status.staleness(TODAY)


@pytest.mark.parametrize("listed_as", [None, "", "  ", 7])
def test_a_registered_entry_without_its_listed_name_gives_no_note(on, tmp_path, monkeypatch, listed_as):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    entry = {"registered": True, "actions": [], "penalties": [],
             **({} if listed_as is None else {"listed_as": listed_as})}
    (tmp_path / fiu_ind_status.STATUS_FILE).write_text(json.dumps(
        {"_meta": {"register": DOCUMENT["_meta"]["register"], "checked_on": DOCUMENT["_meta"]["checked_on"]},
         "exchanges": {"Binance": entry, "Kraken": ENTRIES["Kraken"]}}))
    fiu_ind_status.clear_cache()
    assert fiu_ind_status.note("Binance") is None  # never "listed as None"
    assert fiu_ind_status.note("Kraken")  # the other entries still read


@pytest.mark.parametrize("day", ["2026-02-30", "2026-13-01", "2026-11-00"])
def test_an_impossible_day_is_caught_when_the_file_is_read(on, tmp_path, monkeypatch, day):
    # The pattern matches, but there is no such day: note() would raise while a letter is drafted.
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    register = DOCUMENT["_meta"]["register"]

    def read(meta, exchanges):
        (tmp_path / fiu_ind_status.STATUS_FILE).write_text(json.dumps({"_meta": meta, "exchanges": exchanges}))
        fiu_ind_status.clear_cache()

    read({"register": register, "checked_on": day}, {"Kraken": ENTRIES["Kraken"]})
    assert fiu_ind_status.note("Kraken") is None  # the file is unusable, as with no checked_on
    assert "unusable" in fiu_ind_status.staleness(TODAY)
    read({"register": {**register, "as_of": day}, "checked_on": DOCUMENT["_meta"]["checked_on"]},
         {"Kraken": ENTRIES["Kraken"]})
    assert fiu_ind_status.note("Kraken") is None
    fact = {**ENTRIES["Kraken"]["actions"][0], "date": day}
    read({"register": register, "checked_on": DOCUMENT["_meta"]["checked_on"]},
         {"Kraken": {**ENTRIES["Kraken"], "actions": [fact]}, "Bitstamp": ENTRIES["Bitstamp"]})
    assert fiu_ind_status.note("Kraken") is None  # that entry is skipped
    assert fiu_ind_status.note("Bitstamp")  # the others still read


# -- scripts/check_fiu_staleness.py: the same rule by the real date, warning only -----------------
def test_the_script_is_quiet_while_the_sources_are_recent(capsys, monkeypatch):
    from scripts import check_fiu_staleness

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert check_fiu_staleness.main(TODAY) == 0
    out = capsys.readouterr().out
    assert "WARNING" not in out and "::warning" not in out


def test_the_script_warns_with_what_to_do_once_due_and_still_exits_0(capsys, monkeypatch):
    from scripts import check_fiu_staleness

    late = date.fromisoformat(DOCUMENT["_meta"]["checked_on"]) + timedelta(days=fiu_ind_status.STALE_AFTER_DAYS + 1)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert check_fiu_staleness.main(late) == 0
    out = capsys.readouterr().out
    assert out.startswith("WARNING: ") and "docs/flag-rollout.md" in out and "update _meta.checked_on" in out
    assert "::warning" not in out
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert check_fiu_staleness.main(late) == 0
    assert "::warning title=FIU-IND sources due a re-check::" in capsys.readouterr().out


def test_the_script_warns_on_an_unusable_file_and_still_exits_0(capsys, tmp_path, monkeypatch):
    from scripts import check_fiu_staleness

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert check_fiu_staleness.main(TODAY) == 0
    assert "unusable" in capsys.readouterr().out
