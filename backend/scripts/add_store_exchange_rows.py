"""Add an exchange's own published wallet list to a built label store (ADR-0011).

An exchange's proof-of-reserves (PoR) file lists the addresses it says are its
own. OKX's runs to 474,530 Tron addresses, too many for the JSON label files,
so its rows go into the store's optional `exchange_rows` table, which the
exchange matcher reads behind EXCHEQUER_STORE_EXCHANGE_ROWS. The table sits
beside `labels`, never in it, so the code live today never reads these rows.

The CSV (one row per address) is what scripts/import_por_tron_labels.py parses
from the exchange's file: address, chain, exchange, label, type, source_id,
source_url, published, retrieved, sha256. Each row must be:
- a valid address of its chain's family (Base58Check on Tron);
- not a burn or system address, token contract, DEX router or casino wallet,
  nor on a never-flag list given with --never-flag (app/never_flag.py);
- not already named by a curated exchange label file: the file keeps it (the
  same exchange: corroborated; another exchange: a conflict, listed).
Every row left out is listed in <csv>.left_out.tsv. Rows of a source already in
the store are replaced, so a re-run is repeatable. Run it on the release copy
of the store, before it is vacuumed, hashed and published.

    cd backend && .venv/bin/python -m scripts.add_store_exchange_rows STORE.db okx_por_tron.csv \\
        [--never-flag LIST ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, never_flag  # noqa: E402
from app.etherscan_client import normalize_address  # noqa: E402
from app.exchange_matcher import ExchangeMatcher  # noqa: E402
from app.label_store import (  # noqa: E402
    CHAIN_IDS, EXCHANGE_TABLE, POR_BASIS, SCHEMA_VERSION, encode_address,
)

COLUMNS = ("address", "chain", "exchange", "label", "type", "source_id", "source_url", "published", "retrieved",
           "sha256")
REFUSED = (never_flag.SYSTEM, never_flag.TOKEN, never_flag.ROUTER, never_flag.LISTED, never_flag.GAMBLING)


def source_text(row: dict[str, str]) -> str:
    """One line a report can quote: which list, where it is, when, and the file's hash."""
    return (f"{row['source_id']}: {row['exchange']}'s own published address list, {row['source_url']} "
            f"(published {row['published']}, retrieved {row['retrieved']}, SHA-256 {row['sha256']})")


def add(store: Path, csv_path: Path, listed: Iterable[Path] = (), dry_run: bool = False) -> dict:
    listed = tuple(listed)
    db = sqlite3.connect(store)
    try:
        version = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not version or int(version[0]) != SCHEMA_VERSION:
            raise ValueError(f"{store} has schema {version and version[0]}, expected {SCHEMA_VERSION}")
        never: dict[str, dict[bytes, str]] = {}
        curated: dict[str, dict[str, dict]] = {}
        rows: list[tuple] = []
        left_out: list[tuple[str, str, str]] = []
        corroborated = 0
        sources: dict[str, str] = {}
        reread: set[str] = set()  # every source the CSV holds rows of, added or not: each is replaced
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = set(COLUMNS) - set(reader.fieldnames or ())
            if missing:
                raise ValueError(f"{csv_path}: missing columns {sorted(missing)}")
            for row in reader:
                chain, address = row["chain"].strip(), row["address"].strip()
                if row["source_id"].startswith("por:"):
                    reread.add(row["source_id"])
                raw = encode_address(address)
                if chain not in CHAIN_IDS or raw is None or (chain == "tron") != (len(raw) == 21):
                    left_out.append((chain, address, "not a valid address of this chain"))
                    continue
                if not row["exchange"].strip() or not row["source_id"].startswith("por:"):
                    left_out.append((chain, address, "no exchange, or not a published-list (por:) source"))
                    continue
                if chain not in never:
                    never[chain] = never_flag.build_kinds(chain, listed)
                    # The curated files only: never the store being written.
                    labels = config.get_chain(chain).labels_path
                    curated[chain] = dict(ExchangeMatcher.from_file(labels, chain=chain).entries())
                kind = never_flag.SYSTEM if never_flag.is_system(raw) else never[chain].get(raw)
                if kind in REFUSED:
                    left_out.append((chain, address, f"a {kind}"))
                    continue
                held = curated[chain].get(normalize_address(address))
                if held is not None:
                    if held["exchange"] == row["exchange"]:
                        corroborated += 1
                    else:
                        left_out.append((chain, address, f"CONFLICT: a label file names it {held['exchange']} "
                                                         f"('{held['label']}'); the file keeps it"))
                    continue
                sources.setdefault(row["source_id"], source_text(row))
                rows.append((raw, CHAIN_IDS[chain], row["exchange"].strip(), row["label"].strip() or row["exchange"].strip(),
                             row["type"].strip() or "exchange_wallet", row["source_id"]))
        report = {"store": store.name, "csv": csv_path.name, "added": len(rows), "corroborated": corroborated,
                  "left_out": len(left_out), "left_out_why": dict(Counter(w.split(":")[0] for *_, w in left_out)),
                  "sources": sources}
        out = csv_path.with_name(csv_path.name + ".left_out.tsv")
        with open(out, "w", newline="") as fh:
            writer = csv.writer(fh, delimiter="\t")
            writer.writerow(["chain", "address", "why"])
            writer.writerows(left_out)
        if dry_run:
            return report

        text_ids: dict[str, int] = {}

        def tid(text: str) -> int:
            if text not in text_ids:
                db.execute("INSERT OR IGNORE INTO texts (text) VALUES (?)", (text,))
                text_ids[text] = db.execute("SELECT id FROM texts WHERE text=?", (text,)).fetchone()[0]
            return text_ids[text]

        db.execute(f"CREATE TABLE IF NOT EXISTS {EXCHANGE_TABLE} (address BLOB NOT NULL, chain INTEGER NOT NULL, "
                   "exchange INTEGER NOT NULL, label INTEGER NOT NULL, type INTEGER NOT NULL, basis INTEGER NOT NULL, "
                   "source INTEGER NOT NULL, PRIMARY KEY (address, chain)) WITHOUT ROWID")
        for source_id in sorted(reread):  # a re-run replaces that source's rows, even when none is added now
            prefix = f"{source_id}: "
            db.execute(f"DELETE FROM {EXCHANGE_TABLE} WHERE source IN "
                       "(SELECT id FROM texts WHERE substr(text, 1, ?) = ?)", (len(prefix), prefix))
        basis = tid(POR_BASIS)
        db.executemany(f"INSERT OR REPLACE INTO {EXCHANGE_TABLE} VALUES (?,?,?,?,?,?,?)",
                       # Every text once, in the texts table: 474,530 copies of one label are 14 MB.
                       [(raw, chain_id, tid(exchange), tid(label), tid(wallet_type), basis, tid(sources[source_id]))
                        for raw, chain_id, exchange, label, wallet_type, source_id in rows])
        names = {v: k for k, v in CHAIN_IDS.items()}
        totals: dict[str, dict[str, int]] = {}
        for chain_id, exchange, n in db.execute(
                f"SELECT e.chain, t.text, COUNT(*) FROM {EXCHANGE_TABLE} e JOIN texts t ON t.id = e.exchange "
                "GROUP BY 1, 2"):
            totals.setdefault(names[chain_id], {})[exchange] = n
        db.execute("INSERT OR REPLACE INTO meta VALUES ('exchange_rows', ?)", (json.dumps(totals, sort_keys=True),))
        db.commit()
        report["held"] = totals
        return report
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("store", type=Path)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--never-flag", type=Path, action="append", default=[],
                    help="a list of addresses no row may name (one per line, last field); repeatable")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    report = add(args.store.expanduser(), args.csv.expanduser(), [p.expanduser() for p in args.never_flag],
                 dry_run=args.dry_run)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
