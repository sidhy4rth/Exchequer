"""The offline build of the label store (scripts/build_label_store.py).

The store is private hunt data kept out of the public repository, so a build
that fails or is interrupted must leave nothing behind for a `git add` to pick up.
"""
from __future__ import annotations

import csv

import pytest

from scripts import build_label_store
from scripts.build_label_store import build

from conftest import addr

FIELDS = ["address", "chain", "category", "entity_or_incident", "sources", "source_refs", "date"]


def write_csv(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({**dict.fromkeys(FIELDS, ""), **r})
    return path


SCAM = {"address": addr("5ca33e"), "chain": "ethereum", "category": "phishing/scam",
        "entity_or_incident": "Inferno Drainer receiver", "sources": "Threat-intel report: Check Point"}


def test_an_interrupted_build_leaves_no_building_file(tmp_path, monkeypatch):
    src = write_csv(tmp_path / "flagged.csv", [SCAM])
    out = tmp_path / "data" / "label_store.db"
    out.parent.mkdir()
    real = build_label_store.iter_rows

    def interrupted(*args, **kwargs):
        yield from real(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(build_label_store, "iter_rows", interrupted)
    with pytest.raises(KeyboardInterrupt):
        build(src, out)
    assert not out.with_suffix(".building").exists() and not out.exists()


def test_a_source_the_rules_do_not_place_fails_the_build(tmp_path, capsys):
    """r1-labels-data-2: a row's tier comes from an allow-list of sources, so a new
    list must be placed there before its rows can ship."""
    blog = {**SCAM, "address": addr("b10c"), "sources": "Some blog post"}
    src = write_csv(tmp_path / "flagged.csv", [SCAM, blog])
    out = tmp_path / "label_store.db"
    assert build_label_store.main([str(src), "--out", str(out)]) == 1
    printed = capsys.readouterr().out
    assert "Some blog post" in printed
    assert not out.exists()  # nothing to release by mistake
    assert build_label_store.main([str(src), "--out", str(out), "--allow-unknown-sources"]) == 0
    assert out.exists()


# -- r1-labels-data-1: no scan or list may label infrastructure ------------------
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"     # exchange_labels.json: hot wallet
DEPOSIT = "0x0da044b16bb53ab6d6691e25b1ec7ad380fa5fa7"        # exchange_labels.json: deposit wallet
ROUTER_1INCH = "0x11111112542d85b3ef69ae05771c2dccff4faa26"   # router_labels.json
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"           # config: a traced token
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"           # data/never_flag_tokens.txt
CLOUDBET = "TAJ3SYGtVjGqm61qoGzZN9bQY6MST2JQVL"               # gambling_labels_tron.json
WHITEBIT = "TWBPGLwQw2EbqYLLw1DJnTDt2ZQ9yJW1JJ"               # exchange_labels_tron.json
DETECTOR = "Ethereum poisoning via BigQuery full-history scan (8-char lookalike)"


def poisoning(address, chain="ethereum"):
    return {"address": address, "chain": chain, "category": "address poisoning",
            "entity_or_incident": "lookalike sent by a poisoning operator", "sources": DETECTOR}


def freeze(address, chain="ethereum"):
    return {"address": address, "chain": chain, "category": "stablecoin freeze",
            "entity_or_incident": "USDT", "sources": "USDT0 contract freeze events (on-chain replay)"}


def test_infrastructure_never_becomes_a_store_row(tmp_path):
    infra = [BINANCE_14, DEPOSIT, ROUTER_1INCH, USDT, WETH, "0x" + "0" * 40, "0x" + "0" * 36 + "dead"]
    rows = [poisoning(a) for a in infra] + [poisoning(CLOUDBET, "tron"), poisoning(WHITEBIT, "tron"),
                                             SCAM]
    src = write_csv(tmp_path / "flagged.csv", rows)
    out = tmp_path / "label_store.db"
    report = build(src, out)
    assert report["rows"] == 1  # only the real scam wallet
    assert report["refused"] == 9
    assert report["skipped"] == {"never-flag: system": 2, "never-flag: token": 2, "never-flag: exchange": 2,
                                 "never-flag: deposit": 1, "never-flag: router": 1, "never-flag: gambling": 1}
    listed = (tmp_path / "flagged.csv.refused.tsv").read_text()
    assert BINANCE_14 in listed and CLOUDBET in listed and ROUTER_1INCH in listed


def test_an_issuer_freeze_on_an_exchange_or_deposit_wallet_stays(tmp_path):
    src = write_csv(tmp_path / "flagged.csv", [freeze(DEPOSIT), freeze(BINANCE_14), freeze(USDT)])
    report = build(src, tmp_path / "label_store.db")
    assert report["rows"] == 2 and report["skipped"] == {"never-flag: token": 1}


def test_a_court_record_on_infrastructure_or_a_flood_of_refusals_fails_the_build(tmp_path, capsys):
    fbi = {"address": BINANCE_14, "chain": "ethereum", "category": "hack proceeds (FBI)",
           "entity_or_incident": "Lazarus", "sources": "FBI alert 31 Oct 2026"}
    src = write_csv(tmp_path / "flagged.csv", [SCAM, fbi])
    out = tmp_path / "label_store.db"
    assert build_label_store.main([str(src), "--out", str(out)]) == 1
    assert "refused.tsv" in capsys.readouterr().out and not out.exists()
    assert build_label_store.main([str(src), "--out", str(out), "--accept-refusals"]) == 0

    src = write_csv(tmp_path / "many.csv", [SCAM, poisoning(USDT), poisoning(WETH)])
    assert build_label_store.main([str(src), "--out", str(out), "--max-refused", "1"]) == 1
    assert build_label_store.main([str(src), "--out", str(out), "--max-refused", "2"]) == 0


def test_the_owners_never_flag_lists_apply_too(tmp_path):
    """The out-of-repo gates (one address per line, or a note then a tab and the
    address) run inside the build rather than as a step someone can skip."""
    tokens = tmp_path / "never_flag_tokens.txt"
    tokens.write_text(f"{addr('70c3')}\n")
    services = tmp_path / "never_poison_x.txt"
    services.write_text(f"# reason\tfile\taddress\nknown service\tops.csv\t{addr('5e2c')}\n")
    rows = [poisoning(addr("70c3")), freeze(addr("70c3")), poisoning(addr("5e2c")), freeze(addr("5e2c"))]
    src = write_csv(tmp_path / "flagged.csv", rows)
    report = build(src, tmp_path / "label_store.db", listed=[tokens], no_poisoning=[services])
    assert report["rows"] == 1  # the freeze on the service, which only poisoning labels may not name
    assert report["skipped"] == {"never-flag: listed": 2, "never-flag: never-poison": 1}


# -- r1-scripts-7: two rows for one address keep the stronger evidence -----------
def stored_rows(out):
    import sqlite3

    db = sqlite3.connect(out)
    try:
        return db.execute("SELECT category, tier FROM labels").fetchall()
    finally:
        db.close()


WALLET = addr("d0b1e")
FBI_ROW = {"address": WALLET, "chain": "ethereum", "category": "hack proceeds (FBI)",
           "entity_or_incident": "Lazarus Group", "sources": "FBI alert 31 Oct 2026"}


def test_the_strongest_tier_wins_whatever_the_csv_order(tmp_path):
    for order in ([poisoning(WALLET), FBI_ROW], [FBI_ROW, poisoning(WALLET)]):
        out = tmp_path / "label_store.db"
        report = build(write_csv(tmp_path / "flagged.csv", order), out)
        assert stored_rows(out) == [("stolen", 1)]
        assert report["duplicates"] == 1 and report["conflicts"] == 1


def test_a_tie_never_makes_an_address_a_mixer(tmp_path):
    mixer = {"address": WALLET, "chain": "ethereum", "category": "mixer",
             "entity_or_incident": "Tornado.Cash: 0.1 WBTC", "sources": "Explorer tag via dawsbot/eth-labels @d9b21ae"}
    scam = {**SCAM, "address": WALLET}
    out = tmp_path / "label_store.db"
    build(write_csv(tmp_path / "flagged.csv", [mixer, scam]), out)
    assert stored_rows(out) == [("scam", 3)]


def test_a_strong_conflict_fails_the_build_unless_allowed(tmp_path, capsys):
    src = write_csv(tmp_path / "flagged.csv", [poisoning(WALLET), FBI_ROW])
    out = tmp_path / "label_store.db"
    assert build_label_store.main([str(src), "--out", str(out)]) == 1
    assert WALLET in capsys.readouterr().out and not out.exists()
    assert build_label_store.main([str(src), "--out", str(out), "--allow-conflicts"]) == 0


def test_checksummed_and_lowercase_forms_are_one_row(tmp_path):
    checksummed = "0x" + WALLET[2:].upper()
    out = tmp_path / "label_store.db"
    report = build(write_csv(tmp_path / "flagged.csv", [{**SCAM, "address": WALLET},
                                                        {**SCAM, "address": checksummed}]), out)
    assert report["rows"] == 1 and report["duplicates"] == 1 and report["conflicts"] == 0


def test_tron_hex_and_base58_forms_are_one_row(tmp_path):
    from app.label_store import decode_address

    body = bytes.fromhex("ab" * 20)
    base58 = decode_address(b"\x41" + body)
    rows = [{**poisoning(base58, "tron"), "sources": "Tron poisoning via BigQuery full-history scan"},
            {**poisoning("0x" + body.hex(), "tron"), "sources": "Tron poisoning via BigQuery full-history scan"}]
    report = build(write_csv(tmp_path / "flagged.csv", rows), tmp_path / "label_store.db")
    assert report["rows"] == 1 and report["duplicates"] == 1 and report["conflicts"] == 0
