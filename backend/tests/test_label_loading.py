"""One bad row in a label file is skipped; it never stops the site.

The loaders promised "{} if the file is unusable", but a non-hex 0x key, a
non-string category or `labels` given as a list raised instead. The lifespan
loads every chain's matchers, so one bad row merged into data/ stopped the
service from starting, and every trace on that chain then failed too
(lru_cache does not keep an exception). Audit r1-labels-data-11.
"""
from __future__ import annotations

import json
import logging
import shutil

import pytest
from fastapi.testclient import TestClient

from app import config, exchange_matcher, main, risk_matcher
from app.exchange_matcher import ExchangeMatcher
from app.risk_matcher import RiskMatcher

from conftest import addr

GOOD = addr("900d")


def _write(tmp_path, document, name="labels.json"):
    path = tmp_path / name
    path.write_text(json.dumps(document))
    return path


def _risk(path):
    return RiskMatcher.from_file(path)


def test_a_non_hex_key_is_skipped_not_fatal(tmp_path):
    path = _write(tmp_path, {"labels": {
        "0xZZ00000000000000000000000000000000000001": {"category": "stolen", "entity": "X"},
        GOOD: {"category": "stolen", "entity": "Y"},
    }})
    matcher = _risk(path)
    assert len(matcher) == 1 and matcher.lookup(GOOD)["entity"] == "Y"


def test_a_key_that_is_not_an_address_is_skipped(tmp_path):
    path = _write(tmp_path, {"labels": {"not-an-address": {"category": "stolen", "entity": "X"},
                                        GOOD: {"category": "stolen", "entity": "Y"}}})
    assert len(_risk(path)) == 1


def test_a_non_string_category_is_skipped(tmp_path):
    path = _write(tmp_path, {"labels": {addr("bad"): {"category": 7, "entity": "X"},
                                        GOOD: {"category": "stolen", "entity": "Y"}}})
    assert len(_risk(path)) == 1


def test_a_non_string_entity_is_skipped_and_odd_label_or_source_fall_back(tmp_path):
    path = _write(tmp_path, {"_meta": {"source": "the list"}, "labels": {
        addr("bad"): {"category": "stolen", "entity": ["X"]},
        GOOD: {"category": "stolen", "entity": "Y", "label": 5, "source": {"no": 1}},
    }})
    meta = _risk(path).lookup(GOOD)
    assert meta == {"category": "stolen", "entity": "Y", "label": "Y", "source": "the list", "origin": path.name}


def test_list_shaped_labels_mean_an_unusable_file(tmp_path, caplog):
    path = _write(tmp_path, {"labels": [GOOD]})
    with caplog.at_level(logging.ERROR):
        assert len(_risk(path)) == 0
    assert "not an object" in caplog.text


def test_a_list_at_the_top_is_an_unusable_file(tmp_path):
    assert len(_risk(_write(tmp_path, [GOOD]))) == 0


def test_a_tron_zero_address_is_not_a_wallet(tmp_path):
    path = _write(tmp_path, {"labels": {"T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb": {"category": "frozen", "entity": "X"}}})
    assert len(_risk(path)) == 0


def test_an_exchange_file_with_list_labels_loads_empty(tmp_path):
    assert len(ExchangeMatcher.from_file(_write(tmp_path, {"labels": [GOOD]}))) == 0


def test_an_exchange_key_that_is_not_an_address_is_skipped(tmp_path):
    path = _write(tmp_path, {"labels": {
        "0xZZ00000000000000000000000000000000000001": {"exchange": "Binance"},
        7: "Kraken",
        GOOD: {"exchange": "Binance", "label": "Binance 1", "type": "hot_wallet"},
    }})
    matcher = ExchangeMatcher.from_file(path)
    assert len(matcher) == 1 and matcher.lookup(GOOD)["type"] == "hot_wallet"


def test_an_exchange_entry_with_odd_fields_is_skipped_or_falls_back(tmp_path):
    path = _write(tmp_path, {"labels": {
        addr("bad"): {"exchange": {"x": 1}},
        GOOD: {"exchange": "Binance", "label": None, "type": 3},
    }})
    matcher = ExchangeMatcher.from_file(path)
    assert len(matcher) == 1
    assert matcher.lookup(GOOD) == {"exchange": "Binance", "label": "Binance", "type": "unknown"}


@pytest.fixture
def broken_data(tmp_path, monkeypatch):
    """A copy of data/ with one malformed row in each kind of file."""
    data = tmp_path / "data"
    shutil.copytree(config.DATA_DIR, data, ignore=shutil.ignore_patterns("*.db", "validation"))
    threat = json.loads((data / "threat_labels_bsc.json").read_text())
    threat["labels"]["0xZZ00000000000000000000000000000000000001"] = {"category": "stolen", "entity": "X"}
    (data / "threat_labels_bsc.json").write_text(json.dumps(threat))
    exchange = json.loads((data / "exchange_labels_tron.json").read_text())
    exchange["labels"] = list(exchange["labels"])
    (data / "exchange_labels_tron.json").write_text(json.dumps(exchange))
    monkeypatch.setattr(config, "DATA_DIR", data)
    risk_matcher.clear_label_caches()
    yield data
    monkeypatch.undo()
    risk_matcher.clear_label_caches()


def test_the_app_starts_when_a_label_file_is_malformed(broken_data):
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
    assert len(risk_matcher.get_risk_matcher("bsc")) > 0
    assert len(exchange_matcher.get_matcher("tron")) == 0


@pytest.mark.parametrize("path", sorted(config.DATA_DIR.glob("*_labels*.json"))
                         + sorted(config.DATA_DIR.glob("intl_sanctions*.json")), ids=lambda p: p.name)
def test_every_shipped_label_file_loads_without_a_warning(path, caplog):
    with caplog.at_level(logging.WARNING):
        if path.name.startswith(("exchange_labels", "router_labels")):
            ExchangeMatcher.from_file(path)
        else:
            RiskMatcher.from_file(path)
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


# Loaders added on the trace path by later fixes (never_flag, the store's
# pinned mixers) had no shape checks: a never_flag_tokens.json that is a list
# made every store lookup that found a row raise AttributeError, and so did
# a list-shaped threat file or mixer_pools.json for every store mixer row
# (r1-labels-data-11, 8 Nov check). Each now logs once and treats the bad
# part as empty, like _read_labels.

@pytest.fixture
def data_copy(tmp_path, monkeypatch):
    from app import label_store, never_flag
    data = tmp_path / "data"
    shutil.copytree(config.DATA_DIR, data, ignore=shutil.ignore_patterns("*.db", "validation"))
    monkeypatch.setattr(config, "DATA_DIR", data)

    def clear():
        never_flag.clear_cache()
        label_store.pinned_mixers.cache_clear()
    clear()
    yield data
    monkeypatch.undo()
    clear()


@pytest.mark.parametrize("document", [[], ["0x" + "1" * 40], "tokens", 5,
                                      {"tokens": {"a": 1}, "allow": ["0x" + "1" * 40]},
                                      {"tokens": [5, None], "allow": {"x": 1}}])
def test_a_badly_shaped_never_flag_file_counts_as_empty(data_copy, caplog, document):
    from app import never_flag
    (data_copy / never_flag.NEVER_FLAG_FILE).write_text(json.dumps(document))
    with caplog.at_level(logging.WARNING):
        listed, allow = never_flag._file()
        assert isinstance(listed, frozenset) and isinstance(allow, dict)
        assert never_flag.tokens("ethereum")  # the configured tokens still count
    if not isinstance(document, dict):
        assert any("never_flag_tokens.json" in r.getMessage() for r in caplog.records)


def test_a_list_shaped_never_flag_file_does_not_break_store_lookups(data_copy):
    from app import never_flag
    (data_copy / never_flag.NEVER_FLAG_FILE).write_text(json.dumps([]))
    usdt = "0xdac17f958d2ee523a2206206994597c13d831ec7"
    never_flag.kind("ethereum", usdt)  # used to raise AttributeError
    assert never_flag.tokens("ethereum")


@pytest.mark.parametrize("labels", [[1, 2], ["0x" + "1" * 40], "x"])
def test_a_list_shaped_threat_file_leaves_the_pinned_mixers_of_mixer_pools(data_copy, caplog, labels):
    from app import label_store
    pools = json.loads((data_copy / label_store.MIXER_POOLS_FILE).read_text())
    path = config.get_chain("ethereum").threat_labels_path
    path.write_text(json.dumps({"_meta": {}, "labels": labels}))
    with caplog.at_level(logging.WARNING):
        found = label_store.pinned_mixers("ethereum")
    expected = {a for a in pools.get("ethereum") or {} if not a.startswith("_")}
    assert len(found) == len(expected) and any(path.name in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("pools", [[], [1, 2], {"ethereum": [1, None]}, {"ethereum": "x"}, "x"])
def test_a_badly_shaped_mixer_pools_file_leaves_the_threat_files_mixers(data_copy, pools):
    from app import label_store
    label_store.pinned_mixers.cache_clear()
    before = label_store.pinned_mixers("ethereum")
    (data_copy / label_store.MIXER_POOLS_FILE).write_text(json.dumps(pools))
    label_store.pinned_mixers.cache_clear()
    after = label_store.pinned_mixers("ethereum")
    assert isinstance(after, frozenset) and after <= before


def test_a_threat_file_that_is_a_list_at_the_top_is_unusable_not_fatal(data_copy):
    from app import label_store
    config.get_chain("ethereum").threat_labels_path.write_text(json.dumps([1, 2]))
    assert isinstance(label_store.pinned_mixers("ethereum"), frozenset)


@pytest.mark.parametrize("labels", [[1, None, {"a": 1}], [5, "0x" + "2" * 40], "x", 7])
def test_a_badly_shaped_gambling_file_is_skipped_entry_by_entry(data_copy, labels):
    from app import never_flag
    path = config.get_chain("ethereum").gambling_labels_path
    path.write_text(json.dumps({"labels": labels}))
    found = never_flag.gambling("ethereum")
    assert isinstance(found, frozenset)
    if isinstance(labels, list) and "0x" + "2" * 40 in labels:
        assert len(found) == 1


# -- the plain-text token list and the remaining loaders (8 Nov re-check, p8_malformed) ----
# never_flag.read_list did Path.read_text() with no error handling, so one
# non-UTF-8 byte in data/never_flag_tokens.txt (a file meant to have outside
# token lists appended) raised UnicodeDecodeError from every store-row lookup
# on every chain. A bad line is now skipped with one log line, and the other
# loaders on the trace path fail soft the same way.
GOOD_TOKEN = "0x" + "ab" * 20


def _lookups_still_work():
    from app import never_flag
    never_flag.clear_cache()
    risk_matcher.clear_label_caches()
    for chain in ("ethereum", "bsc", "tron"):
        assert never_flag.tokens(chain) is not None
        never_flag.kind(chain, GOOD_TOKEN if chain != "tron" else "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
        risk_matcher.get_risk_matcher(chain).lookup(GOOD_TOKEN)


def test_a_non_utf8_byte_in_the_token_list_skips_that_line_only(data_copy, caplog):
    from app import never_flag
    (data_copy / "never_flag_tokens.txt").write_bytes(
        b"# list\n\xff\xfe0x" + b"cd" * 20 + b"\n" + GOOD_TOKEN.encode() + b"\n")
    with caplog.at_level(logging.WARNING):
        _lookups_still_work()
        found = never_flag.tokens("ethereum")
    assert never_flag._raw("ethereum", GOOD_TOKEN, hex_as_tron=False) in found  # the good line still counts
    assert never_flag._raw("ethereum", "0x" + "cd" * 20, hex_as_tron=False) not in found
    assert sum("never_flag_tokens.txt" in r.getMessage() for r in caplog.records) == 1


def test_an_unreadable_token_list_counts_as_empty(data_copy, caplog):
    path = data_copy / "never_flag_tokens.txt"
    path.unlink()
    path.mkdir()  # a directory where the file should be: read_text raises IsADirectoryError
    with caplog.at_level(logging.WARNING):
        _lookups_still_work()
    assert any("never_flag_tokens.txt" in r.getMessage() for r in caplog.records)


def test_read_list_given_a_bad_line_keeps_the_rest(tmp_path):
    from app import never_flag
    listed = tmp_path / "listed.txt"
    listed.write_bytes(b"\x80\x81 junk\n" + GOOD_TOKEN.encode() + b"\n")
    assert never_flag.read_list(listed, "ethereum") == {never_flag._raw("ethereum", GOOD_TOKEN, hex_as_tron=False)}


@pytest.mark.parametrize("attribute", ["risk_labels_path", "labels_path", "router_labels_path", "threat_labels_path",
                                       "frozen_labels_path"])
def test_a_label_file_that_cannot_be_opened_is_skipped_not_fatal(data_copy, attribute):
    path = getattr(config.get_chain("ethereum"), attribute)
    assert path is not None and str(path).startswith(str(data_copy))  # the copy, never the shipped file
    if path.exists():
        path.unlink()
    path.mkdir()  # a directory where the file should be: opening it raises IsADirectoryError
    _lookups_still_work()


@pytest.mark.parametrize("meta", [[1, 2], "x", {"counts": [1]}, {"counts": {"by_authority": 5}},
                                  {"counts": {"by_authority": [1, None]}}, {"last_reviewed": {"a": 1}}])
def test_a_badly_shaped_list_meta_does_not_break_the_freshness_report(data_copy, meta):
    from datetime import date
    path = config.get_chain("ethereum").risk_labels_path
    assert str(path).startswith(str(data_copy))
    path.write_text(json.dumps({"_meta": meta, "labels": {}}))
    risk_matcher.clear_label_caches()
    report = risk_matcher.list_freshness("ethereum", date(2026, 11, 8))
    assert isinstance(report["lists"], list)
    from app import provenance
    provenance._list_entry(path)


@pytest.mark.parametrize("document", [{"a": 1}, [1, "x", {"address": 5}, {"no": 1}], "x"])
def test_a_badly_shaped_demo_list_means_no_demos_not_a_crash(tmp_path, monkeypatch, document):
    from app import ownership
    backend = tmp_path / "backend"
    (backend / "data").mkdir(parents=True)
    (backend / "data" / "demo_traces.json").write_text(json.dumps(document))
    monkeypatch.setattr(config, "BACKEND_DIR", backend)
    ownership.demo_addresses.cache_clear()
    try:
        assert isinstance(ownership.demo_addresses(), frozenset)
        assert ownership.is_public(None, GOOD_TOKEN) is False
    finally:
        monkeypatch.undo()
        ownership.demo_addresses.cache_clear()
