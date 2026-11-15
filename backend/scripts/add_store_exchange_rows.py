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
- not already named by a source the exchange matcher reads first: the chain's
  label file, the instant-exchanger seed (data/instant_exchangers.json) or a
  store instant-exchanger row. That source keeps it (the same name:
  corroborated; another: a conflict, listed).
Its type is exchange_wallet (blank reads as it), one of the exchange's own
wallets, or deposit_wallet (ADR-0012), an address on the list that behaves as a
customer's deposit address. A deposit row states its basis in three more
columns: sweeps_to (the wallet it swept to), sweep_tx (one such sweep's hash)
and checked_on (YYYY-MM-DD, the day it was read). sweeps_to must be a wallet the
chain's label file names as the same exchange's hot, cold or exchange wallet;
a row whose sweeps_to is not one is left out, as is an exchange_wallet row that
states a sweep. A CSV with any other type, or a deposit row without a
well-formed basis, is refused whole, and nothing is written.
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
from datetime import date
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import label_rules, never_flag  # noqa: E402
from app.etherscan_client import normalize_address  # noqa: E402
from app.deposit_inference import SWEEP_DESTINATION_TYPES  # noqa: E402
from app.exchange_matcher import curated_sources, role_of  # noqa: E402
from app.label_store import (  # noqa: E402
    CHAIN_IDS, DEPOSIT_TABLE, DEPOSIT_WALLET, EXCHANGE_TABLE, POR_BASIS, POR_DEPOSIT_BASIS, SCHEMA_VERSION,
    encode_address, encode_tx,
)

COLUMNS = ("address", "chain", "exchange", "label", "type", "source_id", "source_url", "published", "retrieved",
           "sha256")
REFUSED = (never_flag.SYSTEM, never_flag.TOKEN, never_flag.ROUTER, never_flag.LISTED, never_flag.GAMBLING)
# An exchange's own wallet (ADR-0011), or a deposit address that says why it is one (ADR-0012).
EXCHANGE_WALLET = "exchange_wallet"
ALLOWED_TYPES = (EXCHANGE_WALLET, DEPOSIT_WALLET)
DEPOSIT_COLUMNS = ("sweeps_to", "sweep_tx", "checked_on")  # a deposit row's basis; optional for any other


def deposit_basis(row: dict[str, str]) -> tuple[bytes, bytes, int] | None:
    """A deposit row's basis as stored (sweeps_to, sweep_tx, checked_on as YYYYMMDD), or None if any part is
    missing or malformed."""
    sweeps_to, tx, day = ((row.get(k) or "").strip() for k in DEPOSIT_COLUMNS)
    raw, tx_raw = encode_address(sweeps_to), encode_tx(tx)
    try:
        when = date.fromisoformat(day) if len(day) == 10 else None
    except ValueError:
        when = None
    if raw is None or tx_raw is None or when is None or (row["chain"].strip() == "tron") != (len(raw) == 21):
        return None
    return raw, tx_raw, int(when.strftime("%Y%m%d"))


def own_wallet(files: dict[str, dict[str, str]], address: str, exchange: str) -> bool:
    """Whether the label file names `address` as `exchange`'s hot, cold or exchange wallet: what a deposit
    sweeps into (deposit_inference.SWEEP_DESTINATION_TYPES)."""
    found = files.get(normalize_address(address))
    return bool(found) and found["exchange"] == exchange \
        and role_of(found["type"], found.get("role")) in SWEEP_DESTINATION_TYPES


def source_text(row: dict[str, str]) -> str:
    """One line a report can quote: which list, where it is, when, and the file's hash."""
    return (f"{row['source_id']}: {row['exchange']}'s own published address list, {row['source_url']} "
            f"(published {row['published']}, retrieved {row['retrieved']}, SHA-256 {row['sha256']})")


def curated_names(chain: str, sources: tuple | None = None) -> dict[str, tuple[str, str, str]]:
    """{address: (who names it, name, label)} from every curated source the
    exchange matcher reads before a store exchange row, never the store being
    written. A label file's record wins over the seed's, as in the matcher."""
    files, seed = sources or curated_sources(chain)
    names = {a: ("the instant-exchanger seed", r["service"], r["service"]) for a, r in seed.items()}
    names.update({a: ("a label file", r["exchange"], r["label"]) for a, r in files.items()})
    return names


def store_instant_exchanger(db: sqlite3.Connection, raw: bytes, chain_id: int) -> tuple[str, str, str] | None:
    """The store's own instant-exchanger row on this address, which the matcher
    reads after a store exchange row: an exchange row would hide it."""
    row = db.execute("SELECT t.text, l.label FROM labels l LEFT JOIN texts t ON t.id = l.entity "
                     "WHERE l.address=? AND l.chain=? AND l.category=?",
                     (raw, chain_id, label_rules.INSTANT_EXCHANGER)).fetchone()
    if row is None:
        return None
    name = (label_rules.clean_text(row[0] or "")
            or label_rules.DEFAULT_ENTITY[label_rules.INSTANT_EXCHANGER])
    return "the store's instant-exchanger row", name, label_rules.clean_text(row[1] or "") or name


def add(store: Path, csv_path: Path, listed: Iterable[Path] = (), dry_run: bool = False) -> dict:
    listed = tuple(listed)
    db = sqlite3.connect(store)
    try:
        version = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not version or int(version[0]) != SCHEMA_VERSION:
            raise ValueError(f"{store} has schema {version and version[0]}, expected {SCHEMA_VERSION}")
        never: dict[str, dict[bytes, str]] = {}
        curated: dict[str, dict[str, tuple[str, str, str]]] = {}
        files: dict[str, dict[str, dict[str, str]]] = {}
        bad_types: Counter[str] = Counter()
        no_basis = 0
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
                wallet_type = row["type"].strip() or EXCHANGE_WALLET
                if wallet_type not in ALLOWED_TYPES:
                    bad_types[wallet_type] += 1
                deposit = deposit_basis(row) if wallet_type == DEPOSIT_WALLET else None
                if wallet_type == DEPOSIT_WALLET and deposit is None:
                    no_basis += 1
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
                    sources_read = curated_sources(chain)
                    files[chain] = sources_read[0]
                    curated[chain] = curated_names(chain, sources_read)
                kind = never_flag.SYSTEM if never_flag.is_system(raw) else never[chain].get(raw)
                if kind in REFUSED:
                    left_out.append((chain, address, f"a {kind}"))
                    continue
                held = curated[chain].get(normalize_address(address)) \
                    or store_instant_exchanger(db, raw, CHAIN_IDS[chain])
                if held is not None:
                    who, name, label = held
                    if name == row["exchange"].strip():
                        corroborated += 1
                    else:
                        left_out.append((chain, address, f"CONFLICT: {who} names it {name} ('{label}'); "
                                                         "that source keeps it"))
                    continue
                if wallet_type == EXCHANGE_WALLET and any((row.get(k) or "").strip() for k in DEPOSIT_COLUMNS):
                    left_out.append((chain, address, "an own-wallet row that states a sweep: which is it?"))
                    continue
                if deposit is not None and not own_wallet(files[chain], row["sweeps_to"].strip(),
                                                          row["exchange"].strip()):
                    left_out.append((chain, address, f"deposit basis: {row['sweeps_to'].strip()} is not a wallet "
                                                     f"the label file names as {row['exchange'].strip()}'s own"))
                    continue
                sources.setdefault(row["source_id"], source_text(row))
                rows.append((raw, CHAIN_IDS[chain], row["exchange"].strip(), row["label"].strip() or row["exchange"].strip(),
                             wallet_type, row["source_id"], deposit))
        if bad_types or no_basis:
            found = ", ".join([f"type {t!r} ({n} rows)" for t, n in sorted(bad_types.items())]
                              + ([f"type {DEPOSIT_WALLET!r} without a well-formed basis ({no_basis} rows)"]
                                 if no_basis else []))
            raise ValueError(f"{csv_path}: refused, nothing written: {found}; exchange_rows hold only "
                             f"{EXCHANGE_WALLET} rows, an exchange's own wallets (ADR-0011), or {DEPOSIT_WALLET} "
                             f"rows that state {', '.join(DEPOSIT_COLUMNS)} (ADR-0012)")
        report = {"store": store.name, "csv": csv_path.name, "added": len(rows),
                  "deposit_rows": sum(1 for *_, deposit in rows if deposit is not None), "corroborated": corroborated,
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
        db.execute(f"CREATE TABLE IF NOT EXISTS {DEPOSIT_TABLE} (address BLOB NOT NULL, chain INTEGER NOT NULL, "
                   "sweeps_to BLOB NOT NULL, sweep_tx BLOB NOT NULL, checked_on INTEGER NOT NULL, "
                   "PRIMARY KEY (address, chain)) WITHOUT ROWID")
        for source_id in sorted(reread):  # a re-run replaces that source's rows, even when none is added now
            prefix = f"{source_id}: "
            of_source = (f"SELECT address, chain FROM {EXCHANGE_TABLE} WHERE source IN "
                         "(SELECT id FROM texts WHERE substr(text, 1, ?) = ?)")
            db.execute(f"DELETE FROM {DEPOSIT_TABLE} WHERE (address, chain) IN ({of_source})", (len(prefix), prefix))
            db.execute(f"DELETE FROM {EXCHANGE_TABLE} WHERE source IN "
                       "(SELECT id FROM texts WHERE substr(text, 1, ?) = ?)", (len(prefix), prefix))
        basis = {EXCHANGE_WALLET: tid(POR_BASIS), DEPOSIT_WALLET: tid(POR_DEPOSIT_BASIS)}
        db.executemany(f"INSERT OR REPLACE INTO {EXCHANGE_TABLE} VALUES (?,?,?,?,?,?,?)",
                       # Every text once, in the texts table: 474,530 copies of one label are 14 MB.
                       [(raw, chain_id, tid(exchange), tid(label), tid(wallet_type), basis[wallet_type],
                         tid(sources[source_id]))
                        for raw, chain_id, exchange, label, wallet_type, source_id, _ in rows])
        # A row replaced by this run keeps no basis from another source's deposit row on the same address.
        db.executemany(f"DELETE FROM {DEPOSIT_TABLE} WHERE address=? AND chain=?",
                       [(raw, chain_id) for raw, chain_id, *_ in rows])
        db.executemany(f"INSERT INTO {DEPOSIT_TABLE} VALUES (?,?,?,?,?)",
                       [(raw, chain_id, *deposit) for raw, chain_id, *_, deposit in rows if deposit is not None])
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
