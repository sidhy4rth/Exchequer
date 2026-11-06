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
import contextlib
import csv
import re
import sqlite3
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from app import label_rules, never_flag
from app.label_store import CHAIN_IDS, SCHEMA_VERSION, encode_address, encode_tx

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "label_store.db"

# hunt category -> (Exchequer category, the most evidence tier it may claim);
# None = left out. The row's sources then set its tier (app/label_rules.py).
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
NEVER_FLAG = "never-flag: "


def map_row(row: dict[str, str], never: dict[str, dict[bytes, str]] | None = None,
            refuse: Callable[..., None] | None = None) -> tuple[list[tuple], str | None]:
    """(store rows, skip reason) for one CSV row. Pure: no I/O.

    A store row is (address, chain_id, category, entity, label, peer, tx,
    date, source, tier) with entity and source still as text.

    `never` maps a chain to the addresses no row may label there
    (never_flag.build_kinds); the zero and burn range is refused even without
    it. Each refused (chain, address) is passed to `refuse`.
    """
    mapped = CATEGORY_MAP.get(row.get("category", ""), "unknown")
    if mapped == "unknown":
        return [], f"unknown category {row.get('category')!r}"
    if mapped is None:
        return [], f"left out: {row['category']}"
    category, tier = mapped
    # A list's "null" or "n/a" is no name; the category's own name stands in.
    entity_text = label_rules.clean_text(row.get("entity_or_incident"))
    label = None
    peer = None
    if category == "mixer" and not entity_text.startswith("Tornado.Cash"):
        # Only a mixer's own pool may end a trace; anything else the hunt
        # filed under "mixer" (e.g. a malicious contract's creator) is a scam.
        category = "scam"
    elif category == "mixer" and label_rules.mixer_service(entity_text) is None:
        # Its governance, registry or helper contracts are not where funds mix.
        return [], "mixer contract that is not a pool"
    if category == "poisoning":
        m = LOOKALIKE.match(entity_text)
        if m:
            peer_raw = encode_address(m.group(1))
            if peer_raw is None:
                return [], "unparseable lookalike target"
            peer, entity = peer_raw, POISONING_OPERATOR
        elif entity_text.lower().startswith("fake token contract"):
            entity = POISONING_TOKEN
        else:
            entity = entity_text or POISONING_OPERATOR
    else:
        entity = entity_text or row.get("category", "")
    refs = label_rules.public_text(label_rules.clean_text(row.get("source_refs")))
    tx_match = TX.search(refs)
    tx = encode_tx(tx_match.group(1)) if tx_match else None
    # A report cites a method, never a team member; and who published the row,
    # not the branch that filed it, sets how strong its evidence is.
    source = label_rules.public_text(label_rules.clean_text(row.get("sources")))
    tier = label_rules.evidence_tier(category, source, tier)
    if refs and not tx_match:
        source = f"{source} ({refs})"  # a URL or a list's own tag: part of the citation
    date = None
    d = (row.get("date") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        date = int(d.replace("-", ""))
    out = []
    traced = False
    refused = None
    for chain in (row.get("chain") or "").split("|"):
        chain = chain.strip()
        chain_id = CHAIN_IDS.get(chain)
        if chain_id is None:
            continue
        traced = True
        if category == "mixer" and chain not in label_rules.STORE_MIXER_CHAINS:
            continue  # the tag was read on Ethereum; this address is not that pool here
        address = row.get("address", "")
        raw = encode_address(address)
        if chain == "tron" and raw is not None and len(raw) == 20:
            raw = b"\x41" + raw  # a Tron contract written in hex form
        if raw is None or (chain != "tron" and len(raw) != 20):
            continue
        kinds = never.get(chain) if never else None
        kind = never_flag.SYSTEM if never_flag.is_system(raw) else (kinds.get(raw) if kinds else None)
        if never_flag.blocks(kind, category):
            # An exchange wallet, router, token contract or burn address: the
            # scan or list is wrong about it, whatever it says (never_flag.py).
            refused = kind
            if refuse is not None:
                refuse(chain, address, kind, category, tier, entity)
            continue
        out.append((raw, chain_id, category, entity, label, peer, tx, date, source, tier))
    if not out:
        if refused:
            return [], NEVER_FLAG + refused
        if traced and category == "mixer":
            return [], "mixer tag read on another chain"
        if traced:
            return [], "malformed address"
        return [], f"no Exchequer chain ({row.get('chain')})"
    return out, None


def iter_rows(reader: Iterable[dict[str, str]], skipped: collections.Counter,
              unknown: collections.Counter | None = None, never: dict[str, dict[bytes, str]] | None = None,
              refuse: Callable[..., None] | None = None) -> Iterator[tuple]:
    for row in reader:
        rows, reason = map_row(row, never, refuse)
        if reason:
            skipped[reason] += 1
        elif unknown is not None:
            # A source the tier rules do not place (app/label_rules.SOURCE_TIERS).
            for piece in label_rules.unknown_sources(label_rules.public_text(
                    label_rules.clean_text(row.get("sources")))):
                unknown[piece] += 1
        yield from rows


def build(csv_path: Path, out: Path, limit: int | None = None, *, listed: Iterable[Path] = (),
          no_poisoning: Iterable[Path] = (), refused_out: Path | None = None) -> dict:
    """Build the store at `out`. `listed` and `no_poisoning` are extra never-flag
    lists (every label refused, or only poisoning); every refused row is written
    to `refused_out`, by default beside the CSV and so outside the repository."""
    csv.field_size_limit(sys.maxsize)
    listed, no_poisoning = tuple(listed), tuple(no_poisoning)
    never = {key: never_flag.build_kinds(key, listed, no_poisoning) for key in CHAIN_IDS}
    refused_out = refused_out or csv_path.with_name(csv_path.name + ".refused.tsv")
    refused_out.unlink(missing_ok=True)
    tmp = out.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    try:
        return _build(db, tmp, csv_path, out, limit, never, refused_out)
    except BaseException:
        # Private hunt data: a failed or interrupted build leaves no copy behind.
        db.close()
        tmp.unlink(missing_ok=True)
        raise


def _build(db: sqlite3.Connection, tmp: Path, csv_path: Path, out: Path, limit: int | None,
           never: dict[str, dict[bytes, str]], refused_out: Path) -> dict:
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
    unknown: collections.Counter = collections.Counter()
    refused = {"rows": 0, "tier1": 0}
    written = 0
    started = time.time()
    batch: list[tuple] = []
    with contextlib.ExitStack() as files:
        refused_file = None

        def refuse(chain, address, kind, category, tier, entity):
            nonlocal refused_file
            if refused_file is None:
                refused_file = csv.writer(files.enter_context(open(refused_out, "w", newline="")), delimiter="\t")
                refused_file.writerow(["chain", "address", "kind", "category", "tier", "entity"])
            refused_file.writerow([chain, address, kind, category, tier, entity])
            refused["rows"] += 1
            refused["tier1"] += tier == 1

        fh = files.enter_context(open(csv_path, newline=""))
        reader = csv.DictReader(fh)
        for n, (raw, chain_id, category, entity, label, peer, tx, date, source, tier) in enumerate(
                iter_rows(reader, skipped, unknown, never, refuse)):
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
        ("never_flag_refused", str(refused["rows"])),
    ])
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(out)
    report = {
        "rows": sum(n for _, _, n in counts),
        "by_chain_category": {f"{names[c]}:{cat}": n for c, cat, n in counts},
        "skipped": dict(skipped.most_common()),
        "unknown_sources": dict(unknown.most_common()),
        "refused": refused["rows"],
        "refused_tier1": refused["tier1"],
        "refused_out": str(refused_out) if refused["rows"] else None,
        "size_mb": round(out.stat().st_size / 1e6, 1),
    }
    return report


def problems(report: dict, args: argparse.Namespace) -> list[str]:
    """Why this build must not be released, if anything."""
    found = []
    if not args.accept_refusals and report["refused_tier1"]:
        found.append(f"{report['refused_tier1']:,} government or court record(s) name an exchange, router, "
                     f"token or burn address; read {report['refused_out']}")
    if not args.accept_refusals and report["refused"] > args.max_refused:
        found.append(f"{report['refused']:,} rows name infrastructure (more than --max-refused "
                     f"{args.max_refused:,}): a detector or list may be misfiring; read {report['refused_out']}")
    if report["unknown_sources"] and not args.allow_unknown_sources:
        found.append("sources app/label_rules.SOURCE_TIERS does not place (add each, with its tier): "
                     + "; ".join(f"{p!r} ({n:,} rows)" for p, n in list(report["unknown_sources"].items())[:20]))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=None, help="stop after N store rows (for a trial build)")
    ap.add_argument("--allow-unknown-sources", action="store_true",
                    help="keep rows whose sources the tier rules do not place, at their category's tier")
    ap.add_argument("--never-flag", type=Path, action="append", default=[],
                    help="a list of addresses no row may label (one per line, last field); repeatable")
    ap.add_argument("--never-poison", type=Path, action="append", default=[],
                    help="a list of addresses no poisoning row may label; repeatable")
    ap.add_argument("--refused-out", type=Path, default=None,
                    help="where refused rows are listed (default: beside the CSV)")
    ap.add_argument("--max-refused", type=int, default=1000,
                    help="refuse the build when more rows than this name infrastructure")
    ap.add_argument("--accept-refusals", action="store_true",
                    help="after reading the refused list: release even with court records or many refusals in it")
    args = ap.parse_args(argv)
    report = build(args.csv.expanduser(), args.out, args.limit,
                   listed=[p.expanduser() for p in args.never_flag],
                   no_poisoning=[p.expanduser() for p in args.never_poison], refused_out=args.refused_out)
    print(f"{report['rows']:,} labels, {report['size_mb']} MB -> {args.out}")
    for key, n in sorted(report["by_chain_category"].items()):
        print(f"  {key}: {n:,}")
    for reason, n in report["skipped"].items():
        print(f"  skipped {n:,}: {reason}")
    if report["refused"]:
        print(f"  {report['refused']:,} rows naming infrastructure refused, listed in {report['refused_out']}")
    found = problems(report, args)
    if found:
        # Nothing is left to release by mistake; the build is repeatable.
        args.out.unlink(missing_ok=True)
        for problem in found:
            print(f"REFUSED: {problem}")
        print(f"removed {args.out}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
