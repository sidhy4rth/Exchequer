"""Build data/label_store.db from the flagged-address hunt's CSV.

The CSV (one row per address; columns address, chain, category,
entity_or_incident, sources, source_refs, date, ...) is the merged output of
the hunt: government and court lists, stablecoin freeze events, published
threat intelligence and millions of address-poisoning wallets found by
on-chain detection. Each hunt category maps to one Exchequer category and an
evidence tier (app/label_store.TIERS); some are deliberately left out:

  gambling platform          the curated gambling_labels*.json files own it
  laundering-linked (1 hop)  one hop from a launderer is not an attribution
  seizure order (... lapsed) may no longer stand; not safe to assert
  sanctioned/seized (gov)    mixes designations with seizures
  anything on a chain Exchequer does not trace, or "evm (chain unspecified)"

    cd backend && .venv/bin/python -m scripts.build_label_store ~/exchequer-flagged/new_flagged.csv
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sqlite3
import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

from app.label_store import CHAIN_IDS, SCHEMA_VERSION, encode_address, encode_tx

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "label_store.db"

# hunt category -> (Exchequer category, evidence tier); None = left out.
CATEGORY_MAP: dict[str, tuple[str, int] | None] = {
    "hack proceeds (FBI)": ("stolen", 1),
    "hack proceeds": ("stolen", 3),
    "exploit attacker": ("stolen", 3),
    "stablecoin freeze": ("frozen", 2),
    "fraud platform (court record)": ("scam", 1),
    "phishing/scam": ("scam", 3),
    "ponzi/rugpull": ("scam", 3),
    "address poisoning": ("poisoning", 4),
    "laundering path (DOJ)": ("laundering", 1),
    "laundering (reported)": ("laundering", 3),
    "mixer": ("mixer", 3),
    "ransomware": ("stolen", 3),  # extorted proceeds, read like a theft's
    "gambling platform": None,
    "laundering-linked (1 hop)": None,
    "seizure order (gov, may be lapsed)": None,
    "sanctioned/seized (gov)": None,  # mixes designations with seizures; not safe to call either
}
LOOKALIKE = re.compile(r"^lookalike of (\S+)")
TX = re.compile(r"\btx (?:0x)?([0-9a-fA-F]{64})\b")
POISONING_OPERATOR = "Address-poisoning operator"
POISONING_TOKEN = "Fake token contract used in address poisoning"
# Our own detectors (the BigQuery scans, the Etherscan/Tenderly/Alchemy/TronGrid runs and the Tron
# operator expansion) are on-chain detection; only a list someone else published is threat intelligence.
ON_CHAIN_DETECTOR = re.compile(r"poisoning (?:detection|via)|operator expansion", re.I)


def map_row(row: dict[str, str]) -> tuple[list[tuple], str | None]:
    """(store rows, skip reason) for one CSV row. Pure: no I/O.

    A store row is (address, chain_id, category, entity, label, peer, tx,
    date, source, tier) with entity and source still as text.
    """
    mapped = CATEGORY_MAP.get(row.get("category", ""), "unknown")
    if mapped == "unknown":
        return [], f"unknown category {row.get('category')!r}"
    if mapped is None:
        return [], f"left out: {row['category']}"
    category, tier = mapped
    entity_text = (row.get("entity_or_incident") or "").strip()
    label = None
    peer = None
    if category == "mixer" and not entity_text.startswith("Tornado.Cash"):
        # Only a mixer's own pool may end a trace; anything else the hunt
        # filed under "mixer" (e.g. a malicious contract's creator) is a scam.
        category = "scam"
    if category == "poisoning":
        m = LOOKALIKE.match(entity_text)
        if m:
            peer_raw = encode_address(m.group(1))
            if peer_raw is None:
                return [], "unparseable lookalike target"
            peer, entity = peer_raw, POISONING_OPERATOR
        elif entity_text.startswith("fake token"):
            entity = POISONING_TOKEN
        else:
            entity = entity_text or POISONING_OPERATOR
            if not ON_CHAIN_DETECTOR.search(row.get("sources") or ""):
                tier = 3  # a published poisoning list
    else:
        entity = entity_text or row.get("category", "")
    refs = (row.get("source_refs") or "").strip()
    tx_match = TX.search(refs)
    tx = encode_tx(tx_match.group(1)) if tx_match else None
    source = (row.get("sources") or "").strip()
    if refs and not tx_match:
        source = f"{source} ({refs})"  # a URL or a list's own tag: part of the citation
    date = None
    d = (row.get("date") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        date = int(d.replace("-", ""))
    out = []
    traced = False
    for chain in (row.get("chain") or "").split("|"):
        chain = chain.strip()
        chain_id = CHAIN_IDS.get(chain)
        if chain_id is None:
            continue
        traced = True
        address = row.get("address", "")
        raw = encode_address(address)
        if chain == "tron" and raw is not None and len(raw) == 20:
            raw = b"\x41" + raw  # a Tron contract written in hex form
        if raw is None or (chain != "tron" and len(raw) != 20):
            continue
        out.append((raw, chain_id, category, entity, label, peer, tx, date, source, tier))
    if not out:
        if traced:
            return [], "malformed address"
        return [], f"no Exchequer chain ({row.get('chain')})"
    return out, None


def iter_rows(reader: Iterable[dict[str, str]], skipped: collections.Counter) -> Iterator[tuple]:
    for row in reader:
        rows, reason = map_row(row)
        if reason:
            skipped[reason] += 1
        yield from rows


def build(csv_path: Path, out: Path, limit: int | None = None) -> dict:
    csv.field_size_limit(sys.maxsize)
    tmp = out.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("""
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE texts (id INTEGER PRIMARY KEY, text TEXT UNIQUE);
        CREATE TABLE labels (
            address BLOB NOT NULL, chain INTEGER NOT NULL, category TEXT NOT NULL,
            entity INTEGER NOT NULL, label TEXT, peer BLOB, tx BLOB, date INTEGER,
            source INTEGER NOT NULL, tier INTEGER NOT NULL,
            PRIMARY KEY (address, chain)) WITHOUT ROWID;
        CREATE TABLE counts (chain TEXT, category TEXT, n INTEGER);
    """)
    text_ids: dict[str, int] = {}

    def tid(text: str) -> int:
        if text not in text_ids:
            text_ids[text] = len(text_ids) + 1
        return text_ids[text]

    skipped: collections.Counter = collections.Counter()
    written = 0
    started = time.time()
    batch: list[tuple] = []
    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        for n, (raw, chain_id, category, entity, label, peer, tx, date, source, tier) in enumerate(iter_rows(reader, skipped)):
            if limit is not None and n >= limit:
                break
            batch.append((raw, chain_id, category, tid(entity), label, peer, tx, date, tid(source), tier))
            if len(batch) >= 100_000:
                db.executemany("INSERT OR IGNORE INTO labels VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
                written += len(batch)
                batch.clear()
                print(f"  {written:,} rows ({time.time() - started:.0f}s)", flush=True)
    db.executemany("INSERT OR IGNORE INTO labels VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
    db.executemany("INSERT INTO texts VALUES (?,?)", [(i, t) for t, i in text_ids.items()])
    names = {v: k for k, v in CHAIN_IDS.items()}
    counts = db.execute("SELECT chain, category, COUNT(*) FROM labels GROUP BY 1, 2").fetchall()
    db.executemany("INSERT INTO counts VALUES (?,?,?)", [(names[c], cat, n) for c, cat, n in counts])
    db.executemany("INSERT INTO meta VALUES (?,?)", [
        ("schema_version", str(SCHEMA_VERSION)),
        ("built_from", csv_path.name),
        ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
    ])
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(out)
    report = {
        "rows": sum(n for _, _, n in counts),
        "by_chain_category": {f"{names[c]}:{cat}": n for c, cat, n in counts},
        "skipped": dict(skipped.most_common()),
        "size_mb": round(out.stat().st_size / 1e6, 1),
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=None, help="stop after N store rows (for a trial build)")
    args = ap.parse_args()
    report = build(args.csv.expanduser(), args.out, args.limit)
    print(f"{report['rows']:,} labels, {report['size_mb']} MB -> {args.out}")
    for key, n in sorted(report["by_chain_category"].items()):
        print(f"  {key}: {n:,}")
    for reason, n in report["skipped"].items():
        print(f"  skipped {n:,}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
