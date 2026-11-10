"""Build data/label_store.db from the flagged-address hunt's CSV.

The CSV (one row per address; columns address, chain, category,
entity_or_incident, sources, source_refs, date, ...) is the merged output of
the hunt: government and court lists, stablecoin freeze events, published
threat intelligence and millions of address-poisoning wallets found by
on-chain detection. Each hunt category maps to one Exchequer category, and
a row's sources set its evidence tier (app/label_rules.py, app/label_store.TIERS);
some are deliberately left out:

  gambling platform          the curated gambling_labels*.json files own it
  laundering-linked (1 hop)  one hop from a launderer is not an attribution
  seizure order (... lapsed) may no longer stand; not safe to assert
  sanctioned/seized (gov)    mixes designations with seizures
  a mixer's non-pool contract, or its tag on a chain it was not read on
  anything on a chain Exchequer does not trace, or "evm (chain unspecified)"

No row may label an exchange wallet, router, token contract, casino or burn
address (app/never_flag.py); those are refused and listed in
<csv>.refused.tsv. The token list (data/never_flag_tokens.json, the 14,800
CoinGecko and Uniswap tokens) and the router files apply with no flag. The
never-poison lists are kept with the hunt, outside the repository, so a build
must be given at least one with --never-poison, or be told it has none with
--without-never-poison; the store records which lists it was built with. Two
rows for one address keep the stronger evidence. The build is removed and
exits 1 -- nothing to release by mistake -- when a source is not on the tier
allow-list, a court record or more than --max-refused rows name
infrastructure, a government, court or issuer record conflicts with another
category, or no never-poison list was given; each has a flag to accept it
after review.

    cd backend && .venv/bin/python -m scripts.build_label_store ~/exchequer-flagged/new_flagged.csv \
        --never-poison ~/exchequer-flagged/never_poison_services.txt \
        --never-poison ~/exchequer-flagged/never_poison_suresh.txt \
        --never-poison ~/exchequer-flagged/never_poison_mukesh.txt \
        --never-poison ~/exchequer-flagged/never_poison_scout.txt
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import csv
import hashlib
import re
import sqlite3
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from app import label_rules, never_flag
from app.label_store import CHAIN_IDS, SCHEMA_VERSION, decode_address, encode_address, encode_tx, pinned_mixers

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
    # hunt6 (8 Nov): scams named in court filings and regulator notices.
    "pig-butchering": ("scam", 1),
    "sextortion/extortion": ("scam", 1),
    "investment fraud (regulator)": ("scam", 1),
    "drainer": ("scam", 3),  # a wallet-drainer kit's receiver
    "malware (clipper/stealer)": ("stolen", 3),  # what the clipper swapped in received stolen coins
    # A no-KYC swap service: read by the exchange matcher, never as a risk row.
    "instant exchanger": (label_rules.INSTANT_EXCHANGER, 3),
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
# Two rows for one address on one chain: the stronger tier wins; at an equal
# tier, the more specific category. A mixer sits below a scam, so a tie never
# makes an address end a trace.
PRIORITY = {"stolen": 0, "laundering": 1, "frozen": 2, "scam": 3, "mixer": 4, "poisoning": 5,
            label_rules.INSTANT_EXCHANGER: 6}
STRONG_SHOWN = 20


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
        # Only a mixer's own pool may end a trace, and at run time only a pool
        # pinned in the repo does (label_store.pinned_mixers); anything else the
        # hunt filed under "mixer" (e.g. a malicious contract's creator) is a scam.
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
          no_poisoning: Iterable[Path] = (), refused_out: Path | None = None,
          without_never_poison: bool = False) -> dict:
    """Build the store at `out`. `listed` and `no_poisoning` are extra never-flag
    lists (every label refused, or only poisoning); every refused row is written
    to `refused_out`, by default beside the CSV and so outside the repository."""
    csv.field_size_limit(sys.maxsize)
    listed, no_poisoning = tuple(listed), tuple(no_poisoning)
    never = {key: never_flag.build_kinds(key, listed, no_poisoning) for key in CHAIN_IDS}
    lists = {"never_flag_lists": describe_lists(listed), "never_poison_lists": describe_lists(no_poisoning)}
    if without_never_poison and not no_poisoning:
        lists["never_poison_lists"] = "none (built with --without-never-poison)"
    refused_out = refused_out or csv_path.with_name(csv_path.name + ".refused.tsv")
    refused_out.unlink(missing_ok=True)
    tmp = out.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    try:
        return _build(db, tmp, csv_path, out, limit, never, refused_out, lists)
    except BaseException:
        # Private hunt data: a failed or interrupted build leaves no copy behind.
        db.close()
        tmp.unlink(missing_ok=True)
        raise


def describe_lists(paths: Iterable[Path]) -> str:
    """Which never-flag lists a build used, as its meta table records them: a
    list kept outside the repository can be named and checked, never read back."""
    found = []
    for path in paths:
        data = Path(path).read_bytes()
        lines = sum(1 for line in data.decode("utf-8", "replace").splitlines()
                    if line.strip() and not line.lstrip().startswith("#"))
        found.append(f"{Path(path).name} ({lines} lines, sha256 {hashlib.sha256(data).hexdigest()[:16]})")
    return "; ".join(found) if found else "none"


def _build(db: sqlite3.Connection, tmp: Path, csv_path: Path, out: Path, limit: int | None,
           never: dict[str, dict[bytes, str]], refused_out: Path, lists: dict[str, str]) -> dict:
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
    merged = {"duplicates": 0, "conflicts": 0, "strong": 0}
    strong: list[str] = []
    names = {v: k for k, v in CHAIN_IDS.items()}

    def insert(rows: list[tuple]) -> None:
        cur = db.executemany("INSERT OR IGNORE INTO labels VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        if cur.rowcount == len(rows):
            return
        # Rare: an address already held on this chain (a checksummed and a
        # lowercase form, Tron hex and base58, overlapping chain lists). The
        # stronger evidence wins whatever the CSV order, and it is counted.
        merged["duplicates"] += len(rows) - cur.rowcount
        for r in rows:
            held = db.execute("SELECT category, entity, label, peer, tx, date, source, tier FROM labels "
                              "WHERE address=? AND chain=?", r[:2]).fetchone()
            if held == tuple(r[2:]):
                continue  # this row, or an identical twin, is the one held
            if held[0] != r[2]:
                merged["conflicts"] += 1
                if min(held[7], r[9]) <= 2:
                    merged["strong"] += 1
                    if len(strong) < STRONG_SHOWN:
                        strong.append(f"{names[r[1]]} {decode_address(r[0])}: {held[0]} (tier {held[7]}) "
                                      f"and {r[2]} (tier {r[9]})")
            if (r[9], PRIORITY[r[2]]) < (held[7], PRIORITY[held[0]]):
                db.execute("UPDATE labels SET category=?, entity=?, label=?, peer=?, tx=?, date=?, source=?, "
                           "tier=? WHERE address=? AND chain=?", (*r[2:], *r[:2]))

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
                insert(batch)
                written += len(batch)
                batch.clear()
                print(f"  {written:,} rows ({time.time() - started:.0f}s)", flush=True)
    insert(batch)
    db.executemany("INSERT INTO texts VALUES (?,?)", [(i, t) for t, i in text_ids.items()])
    counts = db.execute("SELECT chain, category, COUNT(*) FROM labels GROUP BY 1, 2").fetchall()
    # A mixer row ends a trace only at a pinned pool or router; the others are
    # kept as tags, and counted so a list filing wallets as pools is noticed.
    unpinned = sum(1 for raw, chain_id in db.execute("SELECT address, chain FROM labels WHERE category='mixer'")
                   if raw not in pinned_mixers(names[chain_id]))
    db.executemany("INSERT INTO counts VALUES (?,?,?)", [(names[c], cat, n) for c, cat, n in counts])
    db.executemany("INSERT INTO meta VALUES (?,?)", [
        ("schema_version", str(SCHEMA_VERSION)),
        ("built_from", csv_path.name),
        ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
        ("never_flag_refused", str(refused["rows"])),
        ("duplicates", str(merged["duplicates"])),
        ("conflicts", str(merged["conflicts"])),
        *lists.items(),
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
        "unpinned_mixers": unpinned,
        "duplicates": merged["duplicates"],
        "conflicts": merged["conflicts"],
        "strong_conflicts": merged["strong"],
        "strong_conflicts_shown": strong,
        "size_mb": round(out.stat().st_size / 1e6, 1),
        **lists,
    }
    return report


def problems(report: dict, args: argparse.Namespace) -> list[str]:
    """Why this build must not be released, if anything."""
    found = []
    if report["never_poison_lists"] == "none":
        found.append("no --never-poison list was given: the owner's never_poison_*.txt lists are kept with "
                     "the hunt, outside the repository, and stop exchange and service wallets being "
                     "called poisoners; pass each with --never-poison, or --without-never-poison on purpose")
    if not args.accept_refusals and report["refused_tier1"]:
        found.append(f"{report['refused_tier1']:,} government or court record(s) name an exchange, router, "
                     f"token or burn address; read {report['refused_out']}")
    if not args.accept_refusals and report["refused"] > args.max_refused:
        found.append(f"{report['refused']:,} rows name infrastructure (more than --max-refused "
                     f"{args.max_refused:,}): a detector or list may be misfiring; read {report['refused_out']}")
    if report["strong_conflicts"] and not args.allow_conflicts:
        found.append(f"{report['strong_conflicts']:,} addresses carry a government, court or issuer record "
                     "and a different category; the stronger was kept, but check them: "
                     + "; ".join(report["strong_conflicts_shown"]))
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
    ap.add_argument("--without-never-poison", action="store_true",
                    help="build with no never-poison list on purpose (a trial build); the store records it")
    ap.add_argument("--refused-out", type=Path, default=None,
                    help="where refused rows are listed (default: beside the CSV)")
    ap.add_argument("--max-refused", type=int, default=1000,
                    help="refuse the build when more rows than this name infrastructure")
    ap.add_argument("--allow-conflicts", action="store_true",
                    help="after checking them: release with a strong record and another category on one address")
    ap.add_argument("--accept-refusals", action="store_true",
                    help="after reading the refused list: release even with court records or many refusals in it")
    args = ap.parse_args(argv)
    report = build(args.csv.expanduser(), args.out, args.limit,
                   listed=[p.expanduser() for p in args.never_flag],
                   no_poisoning=[p.expanduser() for p in args.never_poison], refused_out=args.refused_out,
                   without_never_poison=args.without_never_poison)
    print(f"{report['rows']:,} labels, {report['size_mb']} MB -> {args.out}")
    for key, n in sorted(report["by_chain_category"].items()):
        print(f"  {key}: {n:,}")
    for reason, n in report["skipped"].items():
        print(f"  skipped {n:,}: {reason}")
    if report["refused"]:
        print(f"  {report['refused']:,} rows naming infrastructure refused, listed in {report['refused_out']}")
    if report["unpinned_mixers"]:
        print(f"  {report['unpinned_mixers']:,} mixer tags not on the pinned list (data/mixer_pools.json, "
              "threat_labels*.json): shown as tags, they do not stop a trace")
    if report["duplicates"]:
        print(f"  {report['duplicates']:,} duplicate rows merged (stronger evidence kept), "
              f"{report['conflicts']:,} with different categories")
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
