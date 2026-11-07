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
