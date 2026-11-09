"""Tests for reading crypto addresses out of other governments' sanctions lists.

Most of these lists carry addresses in free text, so the parsing that matters
is the chain an address is filed under: a BNB-chain address filed as Ethereum
would never match, and a lifted seizure order must not accuse anyone.
"""
from __future__ import annotations

import json
import sys
from datetime import date

import pytest

import scripts.import_intl_sanctions as intl
from app import config
from app.risk_matcher import SANCTIONED, SEIZED
from scripts.import_intl_sanctions import addresses_in, chain_hint

ETH_ADDR = "0x175d44451403Edf28469dF03A9280c1197ADb92c"
TRON_ADDR = "TXEsK1sEsKjZ1xtHitnyAAoqw3WLdYdRNW"


def test_the_chain_named_before_an_address_decides_where_it_is_filed():
    text = f"(1) ETH: {ETH_ADDR} (2) BNB: {ETH_ADDR} (3) USDT: {TRON_ADDR}"
    assert addresses_in(text) == [(ETH_ADDR, "ethereum"), (ETH_ADDR, "bsc"), (TRON_ADDR, "tron")]


def test_a_token_name_alone_does_not_pick_an_evm_chain():
    assert chain_hint("USDT: ") is None
    assert chain_hint("wallet ") is None


def test_a_wallet_named_only_in_lifted_orders_is_left_out(monkeypatch):
    lifted, current = "0x" + "1" * 40, "0x" + "2" * 40
    entities = [
        {"id": "w1", "schema": "CryptoWallet", "properties": {"publicKey": [lifted]}},
        {"id": "w2", "schema": "CryptoWallet", "properties": {"publicKey": [current], "currency": ["ETH"]}},
        {"id": "s1", "schema": "Sanction", "properties": {
            "entity": ["w1"], "authorityId": ["ASO 1/21"], "endDate": ["2022-01-01"]}},
        {"id": "s2", "schema": "Sanction", "properties": {
            "entity": ["w2"], "authorityId": ["ASO 9/26"]}},
    ]
    index = {"resources": [{"name": "entities.ftm.json", "url": "https://data.opensanctions.org/artifacts/x/entities.ftm.json"}]}

    def fake_fetch(url):
        if url.endswith("/entities.ftm.json"):
            return "\n".join(json.dumps(e) for e in entities).encode()
        return json.dumps(index).encode()

    monkeypatch.setattr(intl, "fetch", fake_fetch)
    rows, _ = intl.read_opensanctions("il_mod_crypto", date(2026, 9, 23))

    assert [(address, hint) for address, hint, _ in rows] == [(current, "ethereum")]
    assert "ASO 9/26" in rows[0][2]["source"]


# -- end dates (audit r1-scripts-8, r1-labels-data-3) ------------------------------
TODAY = date(2026, 11, 5)


def _rows(monkeypatch, *end_dates, today=TODAY):
    """read_opensanctions over one Tron wallet named in one order per end-date list."""
    entities = [{"id": "w", "schema": "CryptoWallet", "properties": {"publicKey": [TRON_ADDR]}}]
    for i, ends in enumerate(end_dates):
        props = {"entity": ["w"], "authorityId": [f"FO {i}/24"]}
        if ends is not None:
            props["endDate"] = ends
        entities.append({"id": f"s{i}", "schema": "Sanction", "properties": props})
    index = {"resources": [{"name": "entities.ftm.json", "url": "https://data.opensanctions.org/artifacts/x/entities.ftm.json"}]}
    monkeypatch.setattr(intl, "fetch", lambda url: (
        "\n".join(json.dumps(e) for e in entities) if url.endswith("/entities.ftm.json") else json.dumps(index)).encode())
    rows, _ = intl.read_opensanctions("il_mod_crypto", today)
    return [record for _, _, record in rows]


def test_a_month_precision_end_date_is_in_force_until_the_month_ends(monkeypatch):
    (record,) = _rows(monkeypatch, ["2026-11"])
    assert record["valid_until"] == "2026-11-30"


def test_a_year_precision_end_date_runs_to_31_december(monkeypatch):
    (record,) = _rows(monkeypatch, ["2026"])
    assert record["valid_until"] == "2026-12-31"


def test_a_past_month_is_lifted(monkeypatch):
    assert _rows(monkeypatch, ["2026-10"]) == []


def test_the_latest_of_several_end_dates_counts(monkeypatch):
    (record,) = _rows(monkeypatch, ["2026-11-30", "2026"])
    assert record["valid_until"] == "2026-12-31"


def test_an_unreadable_end_date_keeps_the_entry_and_is_open_ended(monkeypatch, capsys):
    (record,) = _rows(monkeypatch, ["someday"])
    assert record["valid_until"] is None
    assert "1 unreadable end dates" in capsys.readouterr().out


def test_an_open_ended_order_beside_a_dated_one_has_no_end(monkeypatch):
    (record,) = _rows(monkeypatch, ["2027-01-01"], None)
    assert record["valid_until"] is None


def test_an_entry_records_when_its_order_ends(monkeypatch):
    (record,) = _rows(monkeypatch, ["2026-12-09"])
    assert record["valid_until"] == "2026-12-09"
    assert record["source"] == "Israel NBCTF seizure or forfeiture order FO 0/24 (via OpenSanctions)"


# -- a seizure order is not a designation (audit r1-labels-data-12) ----------------
@pytest.fixture
def written(tmp_path, monkeypatch):
    """main() with stub readers, writing into a scratch data directory."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    uk_record = {"entity": "Mustafa AYASH", "authority": "United Kingdom", "source": "UK Sanctions List, entry CTD0004"}
    il_record = {"entity": "Mustafa AYASH", "authority": "Israel", "valid_until": "2028-02-01",
                 "source": "Israel NBCTF seizure or forfeiture order FO 2/24 (via OpenSanctions)"}
    seizure = {"entity": "NBCTF order FO 5/24", "authority": "Israel", "valid_until": "2026-12-31",
               "source": "Israel NBCTF seizure or forfeiture order FO 5/24 (via OpenSanctions)"}
    monkeypatch.setattr(intl, "read_uk", lambda: [(ETH_ADDR, "ethereum", uk_record)])
    monkeypatch.setattr(intl, "read_eu", lambda: [])

    def fake_os(dataset, today):
        rows = [(ETH_ADDR, "ethereum", il_record), (TRON_ADDR, "tron", seizure)] if dataset == "il_mod_crypto" else []
        return rows, f"https://data.opensanctions.org/artifacts/{dataset}/v/entities.ftm.json"
    monkeypatch.setattr(intl, "read_opensanctions", fake_os)
    monkeypatch.setattr(sys, "argv", ["import_intl_sanctions"])
    assert intl.main() == 0
    return {key: json.loads((tmp_path / f"intl_sanctions{'' if key == 'ethereum' else '_' + key}.json").read_text())
            for key in ("ethereum", "tron")}


def test_an_israeli_seizure_order_is_filed_as_seized(written):
    entry = written["tron"]["labels"][TRON_ADDR]
    assert entry["category"] == SEIZED
    assert entry["valid_until"] == "2026-12-31"
    assert written["tron"]["_meta"]["counts"]["by_category"] == {SEIZED: 1}


def test_an_address_on_a_uk_list_and_an_israeli_order_stays_sanctioned_and_names_both(written):
    entry = written["ethereum"]["labels"][ETH_ADDR.lower()]
    assert entry["category"] == SANCTIONED
    assert entry["authorities"] == ["United Kingdom", "Israel"]
    assert "UK Sanctions List" in entry["source"] and "Israel NBCTF" in entry["source"]
    assert "valid_until" not in entry  # the UK designation has no end


# -- offline re-check against a local copy (audit r1-labels-data-3) ---------------
LAPSED_TRON = "TSaLg1S1gC4fkwcBSKM36KNSikWjA1HE2q"


@pytest.fixture
def held(tmp_path, monkeypatch):
    """Held files as the 22 Sep import wrote them, and a later OpenSanctions copy."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    old = "Israel NBCTF administrative seizure order ASO 5/24 (via OpenSanctions)"
    tron = {"_meta": {"last_reviewed": "2026-09-22", "counts": {}}, "labels": {
        TRON_ADDR: {"category": SANCTIONED, "entity": "NBCTF seizure order ASO 5/24", "label": "NBCTF seizure order ASO 5/24",
                    "source": old, "authorities": ["Israel"]},
        LAPSED_TRON: {"category": SANCTIONED, "entity": "NBCTF seizure order ASO 6/24", "label": "NBCTF seizure order ASO 6/24",
                      "source": old.replace("5/24", "6/24"), "authorities": ["Israel"]},
    }}
    eth = {"_meta": {"last_reviewed": "2026-09-22"}, "labels": {
        ETH_ADDR.lower(): {"category": SANCTIONED, "entity": "Mustafa AYASH", "label": "Mustafa AYASH",
                           "source": f"UK Sanctions List, entry CTD0004; {old}", "authorities": ["United Kingdom", "Israel"]},
    }}
    (tmp_path / "intl_sanctions_tron.json").write_text(json.dumps(tron))
    (tmp_path / "intl_sanctions.json").write_text(json.dumps(eth))
    entities = [
        {"id": "w1", "schema": "CryptoWallet", "properties": {"publicKey": [TRON_ADDR]}},
        {"id": "w2", "schema": "CryptoWallet", "properties": {"publicKey": [LAPSED_TRON]}},
        {"id": "w3", "schema": "CryptoWallet", "properties": {"publicKey": [ETH_ADDR]}},
        {"id": "s1", "schema": "Sanction", "properties": {"entity": ["w1"], "authorityId": ["FO 05/24"], "endDate": ["2026-12-31"]}},
        {"id": "s2", "schema": "Sanction", "properties": {"entity": ["w2"], "authorityId": ["FO 06/24"], "endDate": ["2026-07-31"]}},
        {"id": "s3", "schema": "Sanction", "properties": {"entity": ["w3"], "authorityId": ["FO 02/24"], "endDate": ["2024-02-22"]}},
    ]
    copy = tmp_path / "copy.ftm.json"
    copy.write_text("\n".join(json.dumps(e) for e in entities))

    def no_network(url):
        raise AssertionError(f"the re-check must not fetch {url}")
    monkeypatch.setattr(intl, "fetch", no_network)
    assert intl.recheck("il_mod_crypto", copy, "artifact-v2", TODAY) == 0
    return {name: json.loads((tmp_path / name).read_text()) for name in ("intl_sanctions_tron.json", "intl_sanctions.json")}


def test_recheck_drops_a_wallet_whose_orders_have_all_ended(held):
    tron = held["intl_sanctions_tron.json"]
    assert LAPSED_TRON not in tron["labels"]
    assert tron["_meta"]["rechecked"]["il_mod_crypto"]["removed_addresses"] == [LAPSED_TRON]
    assert tron["_meta"]["opensanctions_versions"]["il_mod_crypto"] == "artifact-v2"
    assert tron["_meta"]["last_reviewed"] == "2026-09-22"  # only Israel's listings were re-read


def test_recheck_re_reads_an_order_in_force_and_files_it_as_seized(held):
    entry = held["intl_sanctions_tron.json"]["labels"][TRON_ADDR]
    assert entry == {"category": SEIZED, "entity": "NBCTF order FO 05/24", "label": "NBCTF order FO 05/24",
                     "source": "Israel NBCTF seizure or forfeiture order FO 05/24 (via OpenSanctions)",
                     "authorities": ["Israel"], "valid_until": "2026-12-31"}


def test_recheck_keeps_the_uk_listing_of_a_wallet_whose_israeli_order_ended(held):
    entry = held["intl_sanctions.json"]["labels"][ETH_ADDR.lower()]
    assert entry["category"] == SANCTIONED
    assert entry["authorities"] == ["United Kingdom"]
    assert entry["source"] == "UK Sanctions List, entry CTD0004"
    assert held["intl_sanctions.json"]["_meta"]["counts"] == {
        "addresses": 1, "by_authority": {"United Kingdom": 1}, "by_category": {SANCTIONED: 1}}


def test_an_entities_link_off_opensanctions_is_refused(monkeypatch):
    """The index is third-party data; its link is followed only to OpenSanctions' host."""
    index = {"resources": [{"name": "entities.ftm.json", "url": "file:///etc/passwd"}]}
    monkeypatch.setattr(intl, "fetch", lambda url: json.dumps(index).encode())
    with pytest.raises(ValueError):
        intl.read_opensanctions("il_mod_crypto", TODAY)


# -- a failed check is unknown, never "not used" (audit r1-scripts-2) --------------
UNPLACED = "0x" + "7" * 40


@pytest.fixture
def placement(tmp_path, monkeypatch):
    """main() over one UK-listed address that names no chain, held on Ethereum and BSC."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    held = {"category": SANCTIONED, "entity": "X", "label": "X", "source": "UK", "authorities": ["United Kingdom"]}
    for name in ("intl_sanctions.json", "intl_sanctions_bsc.json"):
        (tmp_path / name).write_text(json.dumps({"_meta": {}, "labels": {UNPLACED: held}}))
    record = {"entity": "X", "authority": "United Kingdom", "source": "UK"}
    monkeypatch.setattr(intl, "read_uk", lambda: [(UNPLACED, None, record)])
    monkeypatch.setattr(intl, "read_eu", lambda: [])
    monkeypatch.setattr(intl, "read_opensanctions", lambda dataset, today: ([], "https://data.opensanctions.org/x"))

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
        def close(self):
            pass
    monkeypatch.setattr(intl, "EtherscanClient", Eth)
    monkeypatch.setattr(intl, "NoderealClient", Bsc)
    monkeypatch.setattr(sys, "argv", ["import_intl_sanctions"])

    def run(eth_used, bsc_used, key="stub"):
        monkeypatch.setattr(config, "NODEREAL_API_KEY", key)
        monkeypatch.setattr(intl, "used_on_ethereum", eth_used)
        monkeypatch.setattr(intl, "used_on_bsc", bsc_used)
        code = intl.main()
        return code, {n: json.loads((tmp_path / n).read_text()) for n in ("intl_sanctions.json", "intl_sanctions_bsc.json")}
    return run


def _quota(*_):
    raise intl.NoderealError("monthly quota exceeded")


def test_a_nodereal_quota_error_keeps_the_held_bsc_placement(placement):
    code, files = placement(lambda *_: True, _quota)
    assert code == 0
    assert UNPLACED in files["intl_sanctions_bsc.json"]["labels"]
    assert files["intl_sanctions_bsc.json"]["_meta"]["unverified"] == [UNPLACED]


def test_no_nodereal_key_carries_bsc_placements_over(placement):
    code, files = placement(lambda *_: True, _quota, key="")
    assert code == 0 and UNPLACED in files["intl_sanctions_bsc.json"]["labels"]


def test_an_ethereum_error_does_not_skip_the_bsc_check(placement):
    def eth_down(*_):
        raise intl.EtherscanError("rate limit")
    code, files = placement(eth_down, lambda *_: True)
    assert code == 0
    assert UNPLACED in files["intl_sanctions.json"]["labels"]  # the held Ethereum placement is kept
    assert UNPLACED in files["intl_sanctions_bsc.json"]["labels"]


def test_an_unchecked_new_address_stops_the_intl_import(placement, tmp_path):
    for name in ("intl_sanctions.json", "intl_sanctions_bsc.json"):
        (tmp_path / name).write_text(json.dumps({"_meta": {}, "labels": {}}))

    def eth_down(*_):
        raise intl.EtherscanError("rate limit")
    code, files = placement(eth_down, lambda *_: True)
    assert code == 1
    assert files["intl_sanctions.json"]["labels"] == {}  # nothing written
