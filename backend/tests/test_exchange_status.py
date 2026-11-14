"""Closed exchanges keep their labels, marked, and no letter is addressed to one as if it could answer.

A trace that ends at an FTX wallet did end at FTX, so the label stays. But FTX
has been in Chapter 11 since November 2022: the letter must go to whoever now
holds its records, and say why (app/exchange_status.py, data/exchange_status.json).
"""
from __future__ import annotations

import copy
import json
import re

import pytest

from app import config, exchange_status
from app.exchange_matcher import ExchangeMatcher
from app.request_letters import EXCHANGE, EXCHANGE_FREEZE, available, draft
from scripts import mark_exchange_status

from test_letter_kinds import labelled

STATUS = json.loads((config.DATA_DIR / exchange_status.STATUS_FILE).read_text(encoding="utf-8"))["exchanges"]
CHAINS = sorted(config.CHAINS)


@pytest.fixture(autouse=True)
def _fresh():
    exchange_status.clear_cache()
    yield
    exchange_status.clear_cache()


@pytest.mark.parametrize("name", sorted(STATUS))
def test_every_entry_says_what_happened_and_cites_a_source(name):
    entry = STATUS[name]
    assert entry["status"] in exchange_status.SUFFIX
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["since"])
    assert entry["what"] and entry["source_kind"] in {"notice", "court", "news", "tracker"}
    assert all(s.strip().startswith("https://") for s in entry["source"].split(";"))
    if entry["status"] == exchange_status.WINDING_DOWN:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["until"])


@pytest.mark.parametrize("chain_key", CHAINS)
def test_every_label_of_a_listed_exchange_is_marked_and_no_other_is(chain_key):
    chain = config.get_chain(chain_key)
    for address, meta in ExchangeMatcher.from_file(chain.labels_path, chain=chain.key).entries():
        found = exchange_status.status(meta["exchange"])
        suffix = exchange_status.SUFFIX[found["status"]] if found else None
        if suffix:
            assert meta["label"].endswith(suffix), (address, meta)
        else:
            assert not any(meta["label"].endswith(s) for s in exchange_status.SUFFIX.values()), (address, meta)


def test_the_files_name_each_listed_exchange():
    names = set()
    for chain in config.CHAINS.values():
        names |= {m["exchange"] for _, m in ExchangeMatcher.from_file(chain.labels_path, chain=chain.key).entries()}
    assert set(STATUS) <= names  # an entry for an exchange no file names would be a typo


@pytest.mark.parametrize("name, status", [("FTX", "defunct"), ("ftx", "defunct"), ("FTX (defunct)", "defunct"),
                                          ("CoinEx", "winding_down"), ("Binance", None), ("", None), (None, None)])
def test_the_status_is_read_by_name(name, status):
    found = exchange_status.status(name)
    assert (found["status"] if found else None) == status


def test_a_missing_or_malformed_file_marks_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert exchange_status.status("FTX") is None
    (tmp_path / exchange_status.STATUS_FILE).write_text('{"exchanges": ["FTX"]}')
    exchange_status.clear_cache()
    assert exchange_status.status("FTX") is None
    (tmp_path / exchange_status.STATUS_FILE).write_text('{"exchanges": {"FTX": {"status": "sleeping"}}}')
    exchange_status.clear_cache()
    assert exchange_status.status("FTX") is None


@pytest.mark.parametrize("label, exchange, marked", [
    ("FTX 12", "FTX", "FTX 12 (defunct)"), ("FTX 12 (defunct)", "FTX", "FTX 12 (defunct)"),
    ("CoinEx 3", "CoinEx", "CoinEx 3 (winding down)"), ("Binance 14", "Binance", "Binance 14"),
    ("Binance 14 (defunct)", "Binance", "Binance 14"),  # an exchange taken off the list loses the mark
])
def test_marking_is_once_and_follows_the_list(label, exchange, marked):
    assert exchange_status.marked(label, exchange) == marked


def test_the_marker_changes_nothing_the_second_time():
    document = {"_meta": {}, "labels": {"0x" + "1" * 40: {"exchange": "Hotbit", "label": "Hotbit 3", "type": "hot_wallet"},
                                        "0x" + "2" * 40: {"exchange": "Binance", "label": "Binance 14", "type": "hot_wallet"}}}
    assert mark_exchange_status.mark(document) == {"Hotbit": 1}
    again = copy.deepcopy(document)
    assert not mark_exchange_status.mark(again) and again == document


# -- the letters ----------------------------------------------------------------------
def _at(exchange, label):
    return labelled("hot_wallet", label=label, exchange=exchange, exchange_label=label)


@pytest.mark.parametrize("label", ["FTX 12 (defunct)", "FTX 12"])  # the second: a case stored before the mark
def test_a_defunct_exchange_is_not_offered_a_letter_as_if_it_could_answer(label):
    offered = {o["to"]: o for o in available(_at("FTX", label))}
    for to in (EXCHANGE, EXCHANGE_FREEZE):
        assert "FTX's administrator or successor (FTX closed 2022-11-11)" in offered[to]["title"]
        assert offered[to]["exchange_status"] == "defunct"
        text = draft("case-1", _at("FTX", label), to)
        to_line = next(line for line in text.splitlines() if line.startswith("To "))
        assert "administrator, liquidator or successor of FTX" in to_line
        assert "Law Enforcement / Compliance team" not in to_line
        assert "FTX has closed, so it cannot answer this letter itself" in text
        assert "https://restructuring.ra.kroll.com/FTX/" in text and "do not send it" in text


def test_a_closing_exchange_is_written_to_with_its_closing_date():
    offered = {o["to"]: o for o in available(_at("CoinEx", "CoinEx 3 (winding down)"))}
    assert offered[EXCHANGE]["title"] == "Request to CoinEx (closing 2026-12-22)"
    text = draft("case-1", _at("CoinEx", "CoinEx 3 (winding down)"), EXCHANGE)
    assert "CoinEx — Law Enforcement / Compliance team" in text
    assert "Send this before 2026-12-22" in text


def test_an_open_exchange_letter_says_nothing_about_closing():
    offered = {o["to"]: o for o in available(_at("Binance", "Binance 14"))}
    assert offered[EXCHANGE] == {"to": EXCHANGE, "title": "Request to Binance"}
    for to in (EXCHANGE, EXCHANGE_FREEZE):
        text = draft("case-1", _at("Binance", "Binance 14"), to)
        assert "NOTE:" not in text and "Binance — Law Enforcement / Compliance team" in text
