"""Tests for what the threat importer accepts from explorer tags and scam lists.

The mistakes that matter are the ones that would call the wrong wallet a
thief's or a mixer: a charity with "hack" in its name, the victim of a hack,
or a mixer's governance contract. Each must be left out.
"""
from __future__ import annotations

from app.risk_matcher import MIXER, STOLEN
from scripts.import_threat_labels import classify, scam_entity


def test_a_thief_tag_names_the_incident():
    assert classify("WazirX Exploiter 14") == (STOLEN, "WazirX exploit")
    assert classify("Kucoin Hacker") == (STOLEN, "Kucoin hack")
    assert classify("CPIMP Attacker 2") == (STOLEN, "CPIMP attack")


def test_a_phishing_flag_is_stolen_funds():
    assert classify("Fake_Phishing4939") == (STOLEN, "Phishing wallet")


def test_words_that_only_contain_hack_are_not_thieves():
    assert classify("Endaoment: Tampa Hackerspace") is None
    assert classify("DreamHacker: AVS Operator") is None
    assert classify("Sorbet Finance: Hack Alert") is None


def test_the_victim_of_a_hack_is_not_its_perpetrator():
    assert classify("Compromised: 0x0e8...864") is None


def test_only_pools_and_entrypoints_count_as_a_mixer():
    assert classify("Tornado.Cash: 100 ETH") == (MIXER, "Tornado Cash")
    assert classify("Tornado.Cash: 10,000 DAI 2") == (MIXER, "Tornado Cash")
    assert classify("Tornado.Cash: Router") == (MIXER, "Tornado Cash")
    assert classify("Typhoon Network: 0.1 BNB") == (MIXER, "Typhoon Network")
    for not_a_pool in ("Tornado.Cash: Governance", "Tornado.Cash: TORN Token",
                       "Tornado.Cash: Team 1 Vesting", "Tornado.Cash: Withdraw Verifier"):
        assert classify(not_a_pool) is None


def test_a_scam_list_entry_without_a_tag_is_named_generically():
    assert scam_entity("") == ("Reported phishing / scam wallet", "Reported phishing / scam wallet")
    assert scam_entity("Akropolis Hacker 1") == ("Akropolis hack", "Akropolis Hacker 1")
