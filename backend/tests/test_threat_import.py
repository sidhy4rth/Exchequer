"""Tests for what the threat importer accepts from explorer tags and scam lists.

The mistakes that matter are the ones that would call the wrong wallet a
thief's or a mixer: a charity with "hack" in its name, the victim of a hack,
or a mixer's governance contract. Each must be left out.
"""
from __future__ import annotations

import json

import pytest

import scripts.import_threat_labels as threat
from app import config
from app.nodereal_client import NoderealError
from app.risk_matcher import MIXER, SCAM, STOLEN
from scripts.import_threat_labels import account_used_on_bsc, classify, refile, scam_entity


def test_a_thief_tag_names_the_incident():
    assert classify("WazirX Exploiter 14") == (STOLEN, "WazirX exploit")
    assert classify("Kucoin Hacker") == (STOLEN, "Kucoin hack")
    assert classify("CPIMP Attacker 2") == (STOLEN, "CPIMP attack")


def test_a_phishing_flag_is_a_scam():
    """A phishing report is not a named theft (audit r1-labels-data-6)."""
    assert classify("Fake_Phishing4939") == (SCAM, "Phishing wallet")


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
    assert scam_entity("") == (SCAM, "Reported phishing / scam wallet", "Reported phishing / scam wallet")


def test_a_scam_list_only_entry_is_filed_as_scam():
    assert scam_entity("Fake_Phishing5143") == (SCAM, "Phishing wallet", "Fake_Phishing5143")
    assert scam_entity("Spam Token") == (SCAM, "Reported phishing / scam wallet", "Spam Token")


def test_a_named_exploiter_on_a_scam_list_stays_stolen():
    assert scam_entity("Akropolis Hacker 1") == (STOLEN, "Akropolis hack", "Akropolis Hacker 1")


def test_a_whitehat_exploiter_is_not_a_thief():
    assert classify("Multichain Exploiter 4 (Whitehat)") is None
    assert scam_entity("Multichain Exploiter 4 (Whitehat)") is None


@pytest.mark.parametrize("tag", ["Uniswap V2: BOT", "RigoBlock Whitehat", "Funds Rescue 2", "MEV Bot: 0x6b7"])
def test_bot_and_whitehat_tags_are_not_listed(tag):
    assert scam_entity(tag) is None


# -- re-filing the held files offline (r1-labels-data-6) ---------------------------
@pytest.mark.parametrize("entry, category", [
    ({"category": STOLEN, "entity": "Phishing wallet", "label": "Fake_Phishing5143"}, SCAM),
    ({"category": STOLEN, "entity": "Reported phishing / scam wallet", "label": "Reported phishing / scam wallet"}, SCAM),
    ({"category": STOLEN, "entity": "WazirX exploit", "label": "WazirX Exploiter 3"}, STOLEN),
    ({"category": MIXER, "entity": "Tornado Cash", "label": "Tornado.Cash: 100 ETH"}, MIXER),
])
def test_refile_keeps_named_thefts_and_mixers_and_makes_list_reports_scams(entry, category):
    assert refile({**entry, "source": "x"})["category"] == category


def test_refile_removes_a_whitehat_or_bot_entry():
    assert refile({"category": STOLEN, "entity": "x", "label": "Uniswap V2: BOT", "source": "x"}) is None


@pytest.fixture
def threat_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    def no_network(*_a, **_k):
        raise AssertionError("an offline mode must not touch the network")
    monkeypatch.setattr(threat.urllib.request, "urlopen", no_network)
    eth = {"_meta": {"counts": {}}, "labels": {
        "0x" + "1" * 40: {"category": STOLEN, "entity": "Phishing wallet", "label": "Fake_Phishing1", "source": "ScamSniffer"},
        "0x" + "2" * 40: {"category": STOLEN, "entity": "Multichain exploit", "label": "Multichain Exploiter 4 (Whitehat)",
                          "source": "Etherscan Phish/Hack label"},
        "0x" + "3" * 40: {"category": STOLEN, "entity": "WazirX exploit", "label": "WazirX Exploiter 3", "source": "dawsbot"},
    }}
    bsc = {"_meta": {"counts": {}}, "labels": {
        "0x" + "4" * 40: {"category": STOLEN, "entity": "Reported phishing / scam wallet",
                          "label": "Reported phishing / scam wallet", "source": "ScamSniffer address blacklist @ 753310a5c8"},
        "0x" + "5" * 40: {"category": STOLEN, "entity": "Reported phishing / scam wallet",
                          "label": "Reported phishing / scam wallet", "source": "ScamSniffer address blacklist @ 753310a5c8"},
        "0x" + "6" * 40: {"category": MIXER, "entity": "Typhoon Network", "label": "Typhoon Network: 0.1 BNB",
                          "source": "BscScan address tag"},
    }}
    (tmp_path / "threat_labels.json").write_text(json.dumps(eth))
    (tmp_path / "threat_labels_bsc.json").write_text(json.dumps(bsc))
    return tmp_path


def test_recategorise_is_offline_and_idempotent(threat_files):
    assert threat.recategorise(dry_run=False) == 0
    first = json.loads((threat_files / "threat_labels.json").read_text())
    assert first["_meta"]["counts"] == {STOLEN: 1, SCAM: 1, MIXER: 0}
    assert first["_meta"]["recategorised"]["removed"] == {"0x" + "2" * 40: "Multichain Exploiter 4 (Whitehat)"}
    assert threat.recategorise(dry_run=False) == 0
    again = json.loads((threat_files / "threat_labels.json").read_text())
    assert again["labels"] == first["labels"]


# -- BSC copies of ScamSniffer addresses (r1-labels-data-14) -----------------------
class StubRpc:
    def __init__(self, nonce="0x0", code="0x", balance="0x0"):
        self.answers = {"eth_getTransactionCount": nonce, "eth_getCode": code, "eth_getBalance": balance}

    def _rpc(self, method, params):
        return self.answers[method]


def test_dust_on_an_unused_bsc_address_is_not_copied():
    assert account_used_on_bsc(StubRpc(nonce="0x0", balance="0x1"), "0x" + "1" * 40) is False


def test_a_contract_on_bsc_is_not_copied():
    assert account_used_on_bsc(StubRpc(nonce="0x5", code="0x6080604052"), "0x" + "1" * 40) is False


def test_an_account_that_sent_on_bsc_is_copied():
    assert account_used_on_bsc(StubRpc(nonce="0x1"), "0x" + "1" * 40) is True


def test_a_missing_rpc_result_is_an_error_not_a_no():
    with pytest.raises(NoderealError):
        account_used_on_bsc(StubRpc(nonce=None), "0x" + "1" * 40)


def test_recheck_removes_entries_that_fail_the_account_rule(threat_files):
    class PerAddress:
        def _rpc(self, method, params):
            used = params[0] == "0x" + "4" * 40
            return {"eth_getTransactionCount": "0x3" if used else "0x0", "eth_getCode": "0x"}[method]
    assert threat.recheck_bsc(PerAddress(), dry_run=False) == 0
    bsc = json.loads((threat_files / "threat_labels_bsc.json").read_text())
    assert set(bsc["labels"]) == {"0x" + "4" * 40, "0x" + "6" * 40}  # the mixer is not ScamSniffer's
    assert bsc["_meta"]["scam_lists_bsc_recheck"]["removed"] == 1


def test_recheck_keeps_an_entry_whose_check_failed(threat_files):
    class Down:
        def _rpc(self, method, params):
            raise NoderealError("quota")
    assert threat.recheck_bsc(Down(), dry_run=False) == 1
    assert len(json.loads((threat_files / "threat_labels_bsc.json").read_text())["labels"]) == 3


def test_import_scam_lists_files_reports_as_scams_and_copies_only_used_accounts_to_bsc(threat_files, monkeypatch, tmp_path):
    used, dusted, whitehat = "0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40
    monkeypatch.setattr(threat, "scam_candidates", lambda: {
        used: {"tag": "", "sources": ["ScamSniffer address blacklist @ 753310a5c8"], "etherscan": False},
        dusted: {"tag": "", "sources": ["ScamSniffer address blacklist @ 753310a5c8"], "etherscan": False},
        whitehat: {"tag": "RigoBlock Whitehat", "sources": ["Etherscan Phish/Hack label"], "etherscan": True},
    })

    class Eth:
        def __init__(self, **_):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    class Bsc:
        def __init__(self, **_):
            pass
        def _rpc(self, method, params):
            if method == "eth_getTransactionCount":
                return "0x2" if params[0] == used else "0x0"
            return {"eth_getCode": "0x", "eth_getBalance": "0x1"}[method]
        def close(self):
            pass

    import scripts.import_eth_labels as eth_labels
    monkeypatch.setattr(threat, "EtherscanClient", Eth)
    monkeypatch.setattr(threat, "NoderealClient", Bsc)
    monkeypatch.setattr(config, "NODEREAL_API_KEY", "stub")
    monkeypatch.setattr(eth_labels, "has_any_activity", lambda client, address: True)
    assert threat.import_scam_lists(tmp_path / "check.jsonl", dry_run=False) == 0

    eth = json.loads((threat_files / "threat_labels.json").read_text())["labels"]
    bsc = json.loads((threat_files / "threat_labels_bsc.json").read_text())["labels"]
    assert eth[used]["category"] == SCAM and eth[dusted]["category"] == SCAM
    assert whitehat not in eth
    assert used in bsc and dusted not in bsc  # a 1-wei balance is not use


def test_a_scam_list_never_labels_an_exchange_router_or_token(monkeypatch, tmp_path, capsys):
    """r1-labels-data-1: the scam-list import skips infrastructure before it spends a call."""
    import contextlib

    from app import config
    from scripts import import_eth_labels, import_threat_labels

    binance_14, usdt, fresh = ("0x28c6c06298d514db089934071355e5743bf21d60",
                               "0xdac17f958d2ee523a2206206994597c13d831ec7", "0x" + "5c" * 20)
    monkeypatch.setattr(import_threat_labels, "scam_candidates", lambda: {
        a: {"tag": "", "sources": ["ScamSniffer"], "etherscan": True} for a in (binance_14, usdt, fresh)})
    checked = []
    monkeypatch.setattr(import_eth_labels, "has_any_activity", lambda _c, a: checked.append(a) or True)
    monkeypatch.setattr(import_threat_labels, "EtherscanClient", lambda **_k: contextlib.nullcontext(object()))
    monkeypatch.setattr(config, "NODEREAL_API_KEY", "")
    assert import_threat_labels.import_scam_lists(tmp_path / "checkpoint.jsonl", dry_run=True) == 0
    assert checked == [fresh]


def test_a_missing_result_when_placing_a_listed_address_is_an_error():
    """used_on_bsc places government listings; None must not read as "unused" (r1-scripts-2)."""
    with pytest.raises(NoderealError):
        threat.used_on_bsc(StubRpc(nonce=None), "0x" + "1" * 40)
    assert threat.used_on_bsc(StubRpc(nonce="0x0", code="0x", balance="0x5"), "0x" + "1" * 40) is True


def test_the_plain_rpc_client_names_itself(monkeypatch):
    """Public endpoints such as publicnode refuse urllib's default User-Agent with
    403, which made every --recheck-bsc check an error (all kept, none decided)."""
    sent = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"jsonrpc": "2.0", "id": 1, "result": "0x1"}'

    def fake_urlopen(request, timeout):
        sent["agent"] = request.get_header("User-agent")
        return Reply()

    monkeypatch.setattr(threat.urllib.request, "urlopen", fake_urlopen)
    assert threat.PlainRpc("https://rpc.example")._rpc("eth_blockNumber", []) == "0x1"
    assert sent["agent"] and not sent["agent"].startswith("Python-urllib")
