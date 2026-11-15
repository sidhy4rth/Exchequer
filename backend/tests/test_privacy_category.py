"""Privacy protocols are a note on the trace, never a risk hit or a stop (#189).

Railgun, Aztec, Hinkal and Privacy Pools are privacy protocols no enforcement
action names a mixer. With the flag EXCHEQUER_PRIVACY_CATEGORY on, a trace
that passes through one of their contracts says so in `privacy_notes` and
walks on; the risk screening, the score and the totals do not change. With
the flag off nothing changes at all: Privacy Pools stays the mixer it is on
main. Reads the shipped data files; no network.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace

import networkx as nx
import pytest

from app import config, never_flag, pipeline
from app.etherscan_client import Transaction, normalize_address
from app.pipeline import TraceRequest, run_trace
from app.risk_matcher import (CATEGORIES, MIXER, PRIVACY, SANCTIONED, RiskMatcher, clear_label_caches,
                              get_risk_matcher)
from conftest import addr

CHAINS = ("ethereum", "bsc", "polygon", "arbitrum", "tron")
RAILGUN = "0x22af4edbea3de885dda8f0a0653e6209e44e5b84"  # Railgun Relay Adapt, Ethereum
POOL = "0xf241d57c6debae225c0f2e6ea1529373c9a9c9fb"     # Privacy Pools ETH pool (a mixer on main)
ENTRY = "0x6818809eefce719e480a7526d76bd3e561526b46"    # Privacy Pools Entrypoint proxy
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"  # data/exchange_labels.json
SEED, W1, W2 = addr("5eed"), addr("a1"), addr("a2")
T = 1_700_000_000


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(config, "PRIVACY_CATEGORY", True)
    clear_label_caches()
    yield
    monkeypatch.setattr(config, "PRIVACY_CATEGORY", False)
    clear_label_caches()


def privacy_file(chain):
    return json.loads(config.get_chain(chain).privacy_protocols_path.read_text())


# --- the flag -------------------------------------------------------------------

def test_the_flag_is_registered_and_off_by_default():
    assert config.FLAGS["EXCHEQUER_PRIVACY_CATEGORY"]["on"] is False
    assert config.PRIVACY_CATEGORY is False


@pytest.mark.parametrize("chain", CHAINS)
def test_flag_off_no_privacy_entry_is_read(chain):
    clear_label_caches()
    matcher = get_risk_matcher(chain)
    for address in privacy_file(chain)["labels"]:
        assert matcher.privacy_lookup(address) is None
    graph = nx.DiGraph()
    graph.add_nodes_from(privacy_file(chain)["labels"], depth=1)
    assert matcher.annotate_privacy(graph) == []
    assert not any("privacy_entity" in d for _, d in graph.nodes(data=True))


@pytest.mark.parametrize("address", [POOL, ENTRY])
def test_flag_off_privacy_pools_is_still_a_mixer_and_a_stop(address):
    clear_label_caches()
    matcher = get_risk_matcher("ethereum")
    assert matcher.lookup(address)["category"] == MIXER
    assert matcher.is_terminal(address)


# --- with the flag on: a note, not a risk hit -----------------------------------

@pytest.mark.parametrize("chain", CHAINS)
def test_flag_on_every_privacy_contract_is_a_note_and_not_a_stop(chain, flag_on):
    matcher = get_risk_matcher(chain)
    for address, entry in privacy_file(chain)["labels"].items():
        assert matcher.lookup(address) is None, address
        assert not matcher.is_flagged(address) and not matcher.is_terminal(address)
        assert matcher.privacy_lookup(address)["entity"] == entry["entity"]
        assert matcher.is_labelled(address)  # still not an unlabelled deposit address


def test_flag_on_a_privacy_hit_sets_no_risk_tag_and_reads_as_a_note(flag_on):
    matcher = get_risk_matcher("ethereum")
    graph = nx.DiGraph()
    graph.add_edge(W1, RAILGUN, value_native=2.5)
    graph.nodes[RAILGUN]["depth"] = 2
    assert matcher.annotate(graph) == []
    [match] = matcher.annotate_privacy(graph)
    node = graph.nodes[RAILGUN]
    assert node["privacy_entity"] == "Railgun"
    assert not {"risk_category", "flags", "is_terminal"} & node.keys()
    assert match.category == PRIVACY and not match.is_terminal and match.to_dict()["is_terminal"] is False
    note = match.describe()
    assert note.startswith(f"Privacy protocol: {RAILGUN} is Railgun: Relay Adapt")
    assert "2.5000 ETH" in note and "2 hops" in note
    assert "funds passing through lose their visible link" in note
    assert "The trace did not stop here" in note and "This is not an accusation" in note
    assert "payouts were not followed" not in note  # a contract whose payouts the walk did follow


def test_flag_on_a_privacy_pool_whose_payouts_were_not_followed_says_so(flag_on):
    # A live trace (15 Nov) into the Privacy Pools Entrypoint: graph_builder's
    # service-contract rule left its payouts unfollowed, and the note said
    # "The trace did not stop here" beside a limit saying they were not followed.
    matcher = get_risk_matcher("ethereum")
    graph = nx.DiGraph()
    graph.add_edge(W1, ENTRY, value_native=0.5)
    graph.nodes[ENTRY].update(depth=1, is_service_contract=True)
    [match] = matcher.annotate_privacy(graph)
    assert match.payouts_followed is False and not match.is_terminal
    assert "payouts_followed" not in match.to_dict()  # no change to the case contract
    note = match.describe()
    assert "The trace did not stop here" not in note
    assert "Being a privacy protocol did not stop the trace here, but its payouts were not followed" in note
    assert "This is not an accusation" in note


@pytest.mark.parametrize("address", [POOL, ENTRY])
def test_flag_on_privacy_pools_moves_from_mixer_to_privacy(address, flag_on):
    matcher = get_risk_matcher("ethereum")
    assert matcher.lookup(address) is None and not matcher.is_terminal(address)
    assert matcher.privacy_lookup(address)["entity"] == "Privacy Pools"
    assert address not in dict(matcher.entries())


def test_flag_on_the_mixer_total_drops_by_privacy_pools_two_and_nothing_else(monkeypatch):
    clear_label_caches()
    before = get_risk_matcher("ethereum").counts_by_category()
    monkeypatch.setattr(config, "PRIVACY_CATEGORY", True)
    clear_label_caches()
    try:
        after = get_risk_matcher("ethereum").counts_by_category()
    finally:
        monkeypatch.setattr(config, "PRIVACY_CATEGORY", False)
        clear_label_caches()
    assert after == {**before, MIXER: before[MIXER] - 2} and PRIVACY not in after


def test_privacy_is_not_a_risk_category():
    # Not counted in any total: counts_by_category, /risk-labels and the report read CATEGORIES.
    assert PRIVACY not in CATEGORIES


# --- precedence -----------------------------------------------------------------

def _write(path, labels, chain="ethereum"):
    path.write_text(json.dumps({"_meta": {"chain": chain, "source": "test list"}, "labels": labels}))
    return path


def test_a_government_listing_outranks_a_privacy_entry(tmp_path):
    a = addr("b1")
    risk = _write(tmp_path / "risk.json", {a: {"category": SANCTIONED, "entity": "X", "source": "OFAC"}})
    privacy = _write(tmp_path / "privacy.json", {a: {"category": PRIVACY, "entity": "Railgun", "source": "docs"}})
    matcher = RiskMatcher.from_file(risk, privacy_path=privacy, privacy_over=frozenset({"threat.json"}))
    assert matcher.lookup(a)["category"] == SANCTIONED and matcher.privacy_lookup(a) is None


def test_only_the_threat_files_mixer_tag_gives_way(tmp_path):
    a, b = addr("b2"), addr("b3")
    risk = _write(tmp_path / "risk.json", {b: {"category": MIXER, "entity": "OFAC mixer", "source": "OFAC"}})
    threat = _write(tmp_path / "threat.json", {a: {"category": MIXER, "entity": "Privacy Pools", "source": "tag"}})
    privacy = _write(tmp_path / "privacy.json", {x: {"category": PRIVACY, "entity": "P", "source": "docs"}
                                                for x in (a, b)})
    matcher = RiskMatcher.from_file(risk, extra_paths=(threat,), privacy_path=privacy,
                                    privacy_over=frozenset({"threat.json"}))
    assert matcher.lookup(a) is None and matcher.privacy_lookup(a)["entity"] == "P"
    assert matcher.lookup(b)["category"] == MIXER and matcher.is_terminal(b)  # a government mixer listing stands


def test_privacy_is_read_only_from_a_privacy_file(tmp_path):
    a, b = addr("b4"), addr("b5")
    risk = _write(tmp_path / "risk.json", {a: {"category": PRIVACY, "entity": "P", "source": "x"}})
    privacy = _write(tmp_path / "privacy.json", {b: {"category": MIXER, "entity": "M", "source": "x"}})
    matcher = RiskMatcher.from_file(risk, privacy_path=privacy)
    assert matcher.lookup(a) is None and matcher.privacy_lookup(a) is None  # a risk file cannot say privacy
    assert matcher.lookup(b) is None and matcher.privacy_lookup(b) is None  # a privacy file cannot say mixer


# --- end to end, with a fake provider -------------------------------------------

_COUNTER = iter(range(1, 10**6))


def _tx(src, dst, value, when):
    return Transaction(hash="0x" + f"{next(_COUNTER):064x}", from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 1e18), timestamp=when, block_number=when // 12,
                       is_error=False, asset="ETH")


def _route(through):
    return [_tx(SEED, W1, 9.0, T + 10), _tx(W1, through, 9.0, T + 20), _tx(through, W2, 9.0, T + 30),
            _tx(W2, BINANCE_14, 9.0, T + 40)]


@pytest.fixture
def trace(monkeypatch):
    def run(history):
        class Fake:
            def get_outgoing_transactions(self, address, limit=None):
                return [t for t in history if t.from_address == address]

        @contextmanager
        def open_source(chain, asset):
            yield Fake()
        monkeypatch.setattr(pipeline, "open_source", open_source)
        monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
        return run_trace(TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=5,
                                      follow_swaps=False))
    return run


VOLATILE = ("seconds_elapsed", "time_limit_seconds")


def _steady(result):
    out = {k: v for k, v in result.items() if k not in VOLATILE}
    out["provenance"] = {k: v for k, v in (result.get("provenance") or {}).items() if k != "captured_at"}
    return out


def _without_privacy(result):
    out = {k: v for k, v in _steady(result).items() if k not in ("privacy_matches", "privacy_notes")}
    out["graph"] = {**result["graph"], "nodes": [{k: v for k, v in n.items() if k != "privacy_entity"}
                                                 for n in result["graph"]["nodes"]]}
    return out


def test_a_privacy_hit_shows_the_note_and_the_trace_walks_on(trace, flag_on):
    on = trace(_route(RAILGUN))
    assert on["exchange_address"] == BINANCE_14  # walked past the contract to the exchange
    assert on["risk_matches"] == [] and on["risk_flags"] == [] and on["risk_notes"] == []
    [match] = on["privacy_matches"]
    assert match["address"] == RAILGUN and match["category"] == PRIVACY and match["is_terminal"] is False
    assert "lose their visible link" in on["privacy_notes"][0] and "not an accusation" in on["privacy_notes"][0]
    node = next(n for n in on["graph"]["nodes"] if n["address"] == RAILGUN)
    assert node["privacy_entity"] == "Railgun" and node["risk_category"] is None and node["flags"] == []
    assert node["is_terminal"] is False and node["expanded"] is True


def test_a_privacy_hit_changes_nothing_else_not_the_score_not_the_severity(trace, monkeypatch):
    clear_label_caches()
    history = _route(RAILGUN)
    off = trace(history)
    monkeypatch.setattr(config, "PRIVACY_CATEGORY", True)
    clear_label_caches()
    try:
        on = trace(history)
    finally:
        monkeypatch.setattr(config, "PRIVACY_CATEGORY", False)
        clear_label_caches()
    assert on["confidence"] == off["confidence"] and on["confidence_detail"] == off["confidence_detail"]
    assert _without_privacy(on) == _steady(off)


def test_flag_on_privacy_pools_no_longer_stops_the_trace(trace, flag_on):
    r = trace(_route(POOL))
    assert r["exchange_address"] == BINANCE_14 and r["risk_matches"] == []
    assert [m["entity"] for m in r["privacy_matches"]] == ["Privacy Pools"]


def test_flag_off_the_output_is_exactly_as_before(trace, monkeypatch):
    # With the flag off, a privacy file on disk changes nothing: the same trace
    # with no privacy file configured (as before #189) gives the same result.
    clear_label_caches()
    for through in (RAILGUN, POOL):
        history = _route(through)
        now = trace(history)
        assert "privacy_matches" not in now and "privacy_notes" not in now
        assert not any("privacy_entity" in n for n in now["graph"]["nodes"])
        before_chain = replace(config.get_chain("ethereum"), privacy_protocols_filename="")
        with monkeypatch.context() as m:
            m.setitem(config.CHAINS, "ethereum", before_chain)
            clear_label_caches()
            before = trace(history)
        clear_label_caches()
        assert _steady(now) == _steady(before)
    # And on main Privacy Pools is a mixer: the trace stops at its pool.
    stopped = trace(_route(POOL))
    assert stopped["exchange_address"] is None and [m["category"] for m in stopped["risk_matches"]] == [MIXER]


# --- the data -------------------------------------------------------------------

def _addresses(path):
    if path is None or not path.exists():
        return set()
    document = json.loads(path.read_text())
    labels = document.get("labels", document) if isinstance(document, dict) else {}
    return {normalize_address(a) for a in labels if isinstance(a, str) and not a.startswith("_")}


@pytest.mark.parametrize("chain", CHAINS)
def test_each_privacy_file_holds_only_sourced_privacy_contracts(chain):
    document = privacy_file(chain)
    meta, labels = document["_meta"], document["labels"]
    assert meta["chain"] == chain and labels and meta["counts"] == {PRIVACY: len(labels)}
    for address, entry in labels.items():
        assert address == normalize_address(address)
        assert entry["category"] == PRIVACY
        assert entry["entity"] in {"Railgun", "Aztec", "Hinkal", "Privacy Pools"}
        assert entry["label"].startswith(entry["entity"].split()[0])
        assert "<https://" in entry["source"] and "Checked on chain 2026-11-11" in entry["source"]


def test_the_hunt_rows_are_all_filed():
    # 27 contracts: the 25 the hunt found new, and Privacy Pools' two (already on main as a mixer).
    assert sum(len(privacy_file(c)["labels"]) for c in CHAINS) == 27
    assert {POOL, ENTRY} <= set(privacy_file("ethereum")["labels"])


@pytest.mark.parametrize("chain", CHAINS)
def test_no_privacy_contract_is_an_exchange_router_gambling_or_never_flag_address(chain):
    c = config.get_chain(chain)
    privacy = set(privacy_file(chain)["labels"])
    assert never_flag.screen(chain, privacy) == {}
    for path in (c.labels_path, c.router_labels_path, c.gambling_labels_path, c.risk_labels_path,
                 c.intl_sanctions_path, c.frozen_labels_path, config.DATA_DIR / "instant_exchangers.json"):
        assert not privacy & _addresses(path), path
    # The threat file names only Privacy Pools' two contracts, as the mixer tag the flag supersedes.
    assert privacy & _addresses(c.threat_labels_path) <= ({POOL, ENTRY} if chain == "ethereum" else set())


def test_no_privacy_contract_is_in_a_demo():
    text = " ".join((config.DATA_DIR / name).read_text().lower()
                    for name in ("recorded_demos.json", "demo_traces.json", "demo_expectations.json"))
    for chain in CHAINS:
        for address in privacy_file(chain)["labels"]:
            assert address.lower() not in text, address


# --- the contract ---------------------------------------------------------------

def test_the_contract_reads_privacy_matches_and_refuses_a_terminal_one(trace, flag_on):
    from pydantic import ValidationError

    from app.contracts import read_case
    result = trace(_route(RAILGUN))
    case = read_case(result)
    assert [m.entity for m in case.privacy_matches] == ["Railgun"] and len(case.privacy_notes) == 1
    bad = {**result, "privacy_matches": [{**result["privacy_matches"][0], "is_terminal": True}]}
    with pytest.raises(ValidationError):
        read_case(bad)


def test_a_case_without_them_reads_as_none(trace):
    clear_label_caches()
    from app.contracts import read_case
    case = read_case(trace(_route(RAILGUN)))
    assert case.privacy_matches is None and case.privacy_notes is None


@pytest.mark.parametrize("chain", CHAINS)
def test_each_privacy_file_loads_without_a_warning(chain, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        matcher = RiskMatcher.from_file(None, privacy_path=config.get_chain(chain).privacy_protocols_path)
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
            and "risk screening disabled" not in r.getMessage()] == []
    assert len(matcher._privacy) == len(privacy_file(chain)["labels"])
