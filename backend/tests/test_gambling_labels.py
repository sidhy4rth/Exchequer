"""Tests for the gambling-platform label.

A gambling platform's wallet is not a sanctions hit and must never read like
one. It is closer to an exchange: a regulated or unregulated business that
holds the account behind the deposit, so the useful next step for an
investigator is a lawful request to the platform. What matters here:

  * the category loads from its own file and is screened like the others;
  * the sentence it produces names the platform and the KYC request, and does
    not accuse anyone;
  * it does NOT stop the trace (a deposit address sweeps onward to the
    platform's hot wallet, and that hop is part of the evidence).
"""
from __future__ import annotations

import json

import pytest

from app import config
from app.risk_matcher import CATEGORIES, GAMBLING, TERMINAL_CATEGORIES, RiskMatch, RiskMatcher

from conftest import addr

DEPOSIT = addr("de9051")
HOT = addr("40711")


@pytest.fixture
def gambling_file(tmp_path):
    path = tmp_path / "gambling.json"
    path.write_text(json.dumps({
        "_meta": {"source": "test list"},
        "labels": {
            HOT: {"category": "gambling", "entity": "Stake.com", "label": "Stake.com hot wallet",
                  "source": "Etherscan gambling tag"},
            DEPOSIT: {"category": "gambling", "entity": "Stake.com", "label": "Stake.com deposit address",
                      "source": "deposit-address expansion"},
        },
    }))
    return path


def test_gambling_is_a_known_category():
    assert GAMBLING == "gambling"
    assert GAMBLING in CATEGORIES


def test_gambling_does_not_end_a_trace():
    assert GAMBLING not in TERMINAL_CATEGORIES


def test_gambling_entries_load_and_match(gambling_file):
    matcher = RiskMatcher.from_file(gambling_file)
    assert len(matcher) == 2
    assert matcher.is_flagged(DEPOSIT)
    assert matcher.lookup(HOT)["category"] == GAMBLING
    assert not matcher.is_terminal(DEPOSIT)
    assert matcher.counts_by_category()[GAMBLING] == 2


def test_gambling_sentence_names_the_platform_and_the_request_without_accusing():
    match = RiskMatch(address=DEPOSIT, category=GAMBLING, entity="Stake.com",
                      label="Stake.com deposit address", source="deposit-address expansion",
                      depth=2, value_received_native=150.0)
    text = match.describe("USDT")
    assert text.startswith("Gambling platform:")
    assert "Stake.com" in text
    assert "account holder" in text
    assert "not a finding" in text
    assert "Sanctioned" not in text and "sanctioned" not in text
    assert match.to_dict()["is_terminal"] is False


@pytest.mark.parametrize("chain_key", ["ethereum", "bsc", "polygon", "arbitrum", "tron"])
def test_every_traceable_chain_has_a_gambling_file_configured(chain_key):
    chain = config.get_chain(chain_key)
    assert chain.gambling_labels_path is not None
    assert chain.gambling_labels_path.name.startswith("gambling_labels")


@pytest.mark.parametrize("chain_key", ["ethereum", "bsc", "polygon", "arbitrum", "tron"])
def test_no_gambling_label_sits_on_an_exchange_wallet_or_a_router(chain_key):
    """A router or an exchange wallet carries every user's money, so a few users
    sweeping into a casino through it must not label it a casino deposit (the
    1inch v4 router once read "Stake.com deposit address")."""
    from app.exchange_matcher import get_matcher, get_router_matcher

    chain = config.get_chain(chain_key)
    if chain.gambling_labels_path is None or not chain.gambling_labels_path.exists():
        pytest.skip("no gambling file for this chain")
    raw = json.loads(chain.gambling_labels_path.read_text())
    gambling = {k.lower() if k.startswith("0x") else k for k in raw.get("labels", raw) if not k.startswith("_")}
    services = {a for a, _ in get_matcher(chain_key).entries()} | {a for a, _ in get_router_matcher(chain_key).entries()}
    assert not gambling & services
