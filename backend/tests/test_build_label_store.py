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
# Each test of one refusal builds without the hunt's never-poison lists, on
# purpose, so that refusal is the only one it meets.
TRIAL = ["--without-never-poison"]


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
    assert build_label_store.main([str(src), "--out", str(out), *TRIAL]) == 1
    printed = capsys.readouterr().out
    assert "Some blog post" in printed
    assert not out.exists()  # nothing to release by mistake
    assert build_label_store.main([str(src), "--out", str(out), *TRIAL, "--allow-unknown-sources"]) == 0
    assert out.exists()


# -- r1-labels-data-1: no scan or list may label infrastructure ------------------
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"     # exchange_labels.json: hot wallet
DEPOSIT = "0x000f9f5f6db6d63bb64bb55d58272a1ce660fd90"        # exchange_labels.json: a Binance customer deposit address
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
    assert report["skipped"] == {"never-flag: burn/system address": 2, "never-flag: token contract": 2, "never-flag: exchange wallet": 2,
                                 "never-flag: exchange deposit address": 1, "never-flag: DEX router": 1, "never-flag: casino wallet": 1}
    listed = (tmp_path / "flagged.csv.refused.tsv").read_text()
    assert BINANCE_14 in listed and CLOUDBET in listed and ROUTER_1INCH in listed


def test_an_issuer_freeze_on_an_exchange_or_deposit_wallet_stays(tmp_path):
    src = write_csv(tmp_path / "flagged.csv", [freeze(DEPOSIT), freeze(BINANCE_14), freeze(USDT)])
    report = build(src, tmp_path / "label_store.db")
    assert report["rows"] == 2 and report["skipped"] == {"never-flag: token contract": 1}


def test_a_court_record_on_infrastructure_or_a_flood_of_refusals_fails_the_build(tmp_path, capsys):
    fbi = {"address": BINANCE_14, "chain": "ethereum", "category": "hack proceeds (FBI)",
           "entity_or_incident": "Lazarus", "sources": "FBI alert 31 Oct 2026"}
    src = write_csv(tmp_path / "flagged.csv", [SCAM, fbi])
    out = tmp_path / "label_store.db"
    assert build_label_store.main([str(src), "--out", str(out), *TRIAL]) == 1
    assert "refused.tsv" in capsys.readouterr().out and not out.exists()
    assert build_label_store.main([str(src), "--out", str(out), *TRIAL, "--accept-refusals"]) == 0

    src = write_csv(tmp_path / "many.csv", [SCAM, poisoning(USDT), poisoning(WETH)])
    assert build_label_store.main([str(src), "--out", str(out), *TRIAL, "--max-refused", "1"]) == 1
    assert build_label_store.main([str(src), "--out", str(out), *TRIAL, "--max-refused", "2"]) == 0


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
    assert report["skipped"] == {"never-flag: on a never-flag list": 2, "never-flag: on a never-poison list": 1}


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
    assert build_label_store.main([str(src), "--out", str(out), *TRIAL]) == 1
    assert WALLET in capsys.readouterr().out and not out.exists()
    assert build_label_store.main([str(src), "--out", str(out), *TRIAL, "--allow-conflicts"]) == 0


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


# -- r1-labels-data-1, round 2: the in-repo lists apply with no flag ------------
LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"            # Chainlink, data/never_flag_tokens.json
USDC_E_POLYGON = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"  # bridged USDC on Polygon
USDC_TRON = "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8"               # USDC on Tron
ROUTER_1INCH_V5 = "0x1111111254eeb25477b68fb85ed929f73a960582"  # router_labels.json (Ethereum only)


def test_a_default_build_refuses_the_token_contracts_the_owners_list_names(tmp_path):
    """Probe C: with no --never-flag list given, LINK, USDC.e and Tron USDC were
    stored as poisoners. The token list now lives in data/, so no flag is needed."""
    rows = [poisoning(LINK), poisoning(USDC_E_POLYGON, "polygon"), poisoning(USDC_TRON, "tron"), SCAM]
    report = build(write_csv(tmp_path / "flagged.csv", rows), tmp_path / "label_store.db")
    assert report["rows"] == 1
    assert report["skipped"] == {"never-flag: token contract": 3}


@pytest.mark.parametrize("chain", ["ethereum", "bsc", "polygon", "arbitrum"])
def test_an_ethereum_router_is_refused_on_every_evm_chain(tmp_path, chain):
    """Probe C: the 1inch v5 router was refused on Ethereum only. A router file
    lists contracts, and a contract's address has no key, so on another EVM chain
    it is never somebody's wallet."""
    scam = {**SCAM, "address": ROUTER_1INCH_V5, "chain": chain}
    report = build(write_csv(tmp_path / "flagged.csv", [scam, poisoning(ROUTER_1INCH_V5, chain)]),
                   tmp_path / "label_store.db")
    assert report["rows"] == 0
    assert report["skipped"] == {"never-flag: DEX router": 2}


def test_a_release_build_needs_the_never_poison_lists_or_says_it_has_none(tmp_path, capsys):
    """The never-poison lists (the services list alone is about 48,000 addresses)
    are kept with the hunt, outside the repository. A build that was not given
    one is refused, unless the person building says so on purpose; the store
    records which lists it was built with either way."""
    import sqlite3

    src = write_csv(tmp_path / "flagged.csv", [SCAM])
    out = tmp_path / "label_store.db"
    assert build_label_store.main([str(src), "--out", str(out)]) == 1
    assert "--never-poison" in capsys.readouterr().out and not out.exists()

    assert build_label_store.main([str(src), "--out", str(out), "--without-never-poison"]) == 0
    meta = dict(sqlite3.connect(out).execute("SELECT key, value FROM meta").fetchall())
    assert meta["never_poison_lists"] == "none (built with --without-never-poison)"

    services = tmp_path / "never_poison_services.txt"
    services.write_text(f"{addr('5e2c')}\n{addr('5e2d')}\n")
    assert build_label_store.main([str(src), "--out", str(out), "--never-poison", str(services)]) == 0
    meta = dict(sqlite3.connect(out).execute("SELECT key, value FROM meta").fetchall())
    assert meta["never_poison_lists"].startswith("never_poison_services.txt (2 lines, sha256 ")


# -- the hunt6 sources and categories (8 Nov) ----------------------------------------------
@pytest.mark.parametrize("source,category,expected", [
    ("Court record: USAO SDNY forfeiture complaint 24-cv-1", "pig-butchering", ("scam", 1)),
    ("Court record: USAO DDC forfeiture complaint", "sextortion/extortion", ("scam", 1)),
    ("Court record: forfeiture.gov order", "investment fraud (regulator)", ("scam", 1)),
    ("Government report: UN Panel of Experts S/2024/215", "hack proceeds", ("stolen", 3)),
    ("Incident write-up: rekt.news Orbit Bridge", "exploit attacker", ("stolen", 3)),
    ("Vendor IOC: ESET malware-ioc KryptoCibule", "malware (clipper/stealer)", ("stolen", 3)),
    ("Incident write-up: SlowMist Inferno Drainer", "drainer", ("scam", 3)),
    ("Community list: CryptoScamDB blacklist", "phishing/scam", ("scam", 5)),
])
def test_the_hunt6_sources_and_categories_are_placed(tmp_path, source, category, expected):
    """Each hunt6 source names its kind first, and the QA'd tier follows from it;
    a court record still cannot lift a laundering hop or a theft above its category's cap."""
    row = {"address": addr("abc123"), "chain": "ethereum", "category": category,
           "entity_or_incident": "hunt6 test", "sources": source}
    out = tmp_path / "label_store.db"
    build(write_csv(tmp_path / "flagged.csv", [row]), out)
    assert stored_rows(out) == [expected]


def test_a_private_lawsuit_is_not_a_court_record(tmp_path):
    """An allegation in a private suit is published, not a government record."""
    from app import label_rules
    assert label_rules.source_tier("Lawsuit filing: Cohn v. Popescu") == 3
    assert label_rules.source_tier("Court record: USAO EDNY") == 1
