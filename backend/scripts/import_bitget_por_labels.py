"""Label Bitget's own reserve wallets on the EVM chains from its proof-of-reserves API.

Bitget's proof-of-reserves page (https://www.bitget.com/promotion/proof-of-reserves)
lists, per audit, the wallets it calls its reserve wallets. The page reads them
from its own public API (no key, no login):

    POST https://www.bitget.com/v1/bill/proof/assets/public/queryReserveWalletDetail
         {"auditId": "<audit id>"}

The answer is JSON: one entry per wallet and coin, with the chain name, the
snapshot time and an explorer link (`walletUrl`) that names the address. For a
token the link is `/token/<token contract>?a=<wallet>`: the wallet is the `a=`
holder, never the token contract in the path.

This script reads answers saved by hand (it fetches nothing), picks for each
address on Ethereum, BNB Smart Chain, Polygon and Arbitrum the newest audit
that lists it, and adds it by the rules and with the helpers of
scripts/import_por_labels.py (#226): gather() leaves out conflicts with any
other file, a demo, a token list or the label store; check() reads it on chain
keylessly; verdict() types it exchange_wallet, or contract_wallet where it
holds contract code; numbering() gives it one "Bitget: Reserve Wallet N" on
every chain. Bitget gives no hot or cold role, so no `role` is set.

Each row cites the answer it was read from: `source` (the API URL), `source_audit`
(the audit id sent in the POST body), `source_sha256` (SHA-256 of the answer, byte
for byte as served), `source_date` (the audit's snapshot date, UTC) and `retrieved`.
An answer to a POST has no Internet Archive copy, so the answers cited are kept in
tests/fixtures/bitget_por/. The file's _meta[META_KEY] records every answer read.
Bitget's Tron wallets go through scripts/import_por_tron_labels.py (#221).

    cd backend && .venv/bin/python -m scripts.import_bitget_por_labels \\
        --audit Au2026111300=queryReserveWalletDetail_Au2026111300.json ... \\
        --checks bitget_checks.json --store label_store.db [--dry-run]

A saved answer's `<file>.meta.json`, if present, gives its retrieval time (UTC).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import import_por_labels as por  # noqa: E402

EXCHANGE = "Bitget"
URL = "https://www.bitget.com/v1/bill/proof/assets/public/queryReserveWalletDetail"
PAGE = "https://www.bitget.com/promotion/proof-of-reserves"
KIND = ("Bitget proof-of-reserves reserve wallet (its queryReserveWalletDetail answer for one audit; "
        "no hot or cold role given)")
META_KEY = "por_bitget_2026_11_15"
NETWORKS = {"Ethereum": "ethereum", "Binance Smart Chain": "bsc", "Polygon": "polygon", "Arbitrum One": "arbitrum"}
HOLDER = re.compile(r"[?&]a=(0x[0-9a-fA-F]{40})(?:[&#]|$)")
ACCOUNT = re.compile(r"/(?:address|account)/(0x[0-9a-fA-F]{40})(?:[/?#]|$)")


def address_of(wallet_url: str) -> str | None:
    """The wallet a Bitget explorer link names: the `a=` holder of a token link, else the address path."""
    found = HOLDER.search(wallet_url) or ACCOUNT.search(wallet_url)
    return found.group(1).lower() if found else None


def parse(data: bytes) -> tuple[str | None, dict[str, dict[str, set[str]]]]:
    """(snapshot date UTC, {chain: {address: {coin@height}}}) from one queryReserveWalletDetail answer."""
    entries = json.loads(data.decode("utf-8")).get("data") or []
    snapshots = {e.get("snapshotTime") for e in entries}
    if len(snapshots) > 1:
        raise ValueError(f"one audit, several snapshot times: {sorted(snapshots)}")
    found: dict[str, dict[str, set[str]]] = {c: {} for c in por.CHAINS}
    for entry in entries:
        chain = NETWORKS.get(entry.get("chainName", ""))
        address = address_of(entry.get("walletUrl", "")) if chain else None
        if chain and address:
            found[chain].setdefault(address, set()).add(f"{entry.get('coinName')}@{entry.get('height')}")
    when = next(iter(snapshots), None)
    date = datetime.fromtimestamp(int(when) / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if when else None
    return date, found


def newest(audits: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    """{chain: {address: audit id}}: the newest audit (by snapshot) that lists each address."""
    out: dict[str, dict[str, str]] = {c: {} for c in por.CHAINS}
    for audit_id, audit in sorted(audits.items(), key=lambda kv: kv[1]["snapshot"] or ""):
        for chain, found in audit["found"].items():
            for address in found:
                out[chain][address] = audit_id
    return out


def rows(candidates: dict[str, dict[str, dict]], accounts: dict[str, dict], cited: dict[str, dict[str, str]],
         audits: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, dict]], dict[str, list[dict]]]:
    """({chain: {address: label row}}, {chain: [left out on chain]})."""
    kept, left = [], {c: [] for c in candidates}
    for chain, found in candidates.items():
        for address in sorted(found):
            kind, why = por.verdict(accounts.get(f"{chain}:{address}"))
            if why:
                left[chain].append({"address": address, "exchange": EXCHANGE, "why": why})
            else:
                kept.append((chain, address, kind))
    numbers = por.numbering(EXCHANGE, (a for _, a, _ in kept))
    out: dict[str, dict[str, dict]] = {c: {} for c in candidates}
    for chain, address, kind in kept:
        audit = audits[cited[chain][address]]
        out[chain][address] = {
            "exchange": EXCHANGE, "label": por.LABEL.format(exchange=EXCHANGE, n=numbers[address]), "type": kind,
            "source_kind": KIND, "source": URL, "source_audit": cited[chain][address],
            "source_sha256": audit["sha256"], "source_date": audit["snapshot"], "retrieved": audit["retrieved"][:10]}
    return out, left


def read_audit(audit_id: str, path: Path, retrieved: str) -> dict[str, Any]:
    data = path.read_bytes()
    sidecar = path.with_name(path.name + ".meta.json")
    meta = json.loads(sidecar.read_text()) if sidecar.is_file() else {}
    if meta.get("request_body", {}).get("auditId", audit_id) != audit_id:
        raise ValueError(f"{path.name}: its .meta.json names another audit")
    snapshot, found = parse(data)
    return {"snapshot": snapshot, "found": found, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "retrieved": meta.get("retrieved_utc", retrieved), "wallet_entries": len(json.loads(data).get("data") or [])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audit", action="append", default=[], metavar="ID=PATH", required=True,
                        help="a saved queryReserveWalletDetail answer for that audit id")
    parser.add_argument("--retrieved", default=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
                        help="retrieval date when an answer has no .meta.json (default today, UTC)")
    parser.add_argument("--checks", type=Path, required=True, help="checkpoint of the on-chain reads")
    parser.add_argument("--store", type=Path, help="a label-store release to check for rows on these addresses")
    parser.add_argument("--report", type=Path, help="write counts, conflicts and the left-out list here")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    audits = {}
    for item in args.audit:
        audit_id, _, path = item.partition("=")
        audits[audit_id] = read_audit(audit_id, Path(path).expanduser(), args.retrieved)
    cited = newest(audits)
    found = {EXCHANGE: {c: {a: {f"{s}@{i}" for i, au in audits.items() for s in au["found"][c].get(a, ())}
                            for a in cited[c]} for c in por.CHAINS}}
    candidates, conflicts, counts = por.gather(found, store=args.store)
    accounts = por.check(candidates, args.checks)
    new_rows, left = rows(candidates, accounts, cited, audits)
    report = {"counts": counts, "conflicts": conflicts, "left_out_on_chain": left,
              "added": {c: len(r) for c, r in new_rows.items()}}
    if args.report:
        args.report.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    if args.dry_run:
        return 0
    note = {
        "rule": "scripts/import_bitget_por_labels.py: Bitget's own proof-of-reserves reserve-wallet list, per audit "
                "(a first-party source, as the por_2026_11_15 rows); each address cites the newest audit that "
                "lists it; the rules of scripts/import_por_labels.py: a conflict with any other file, a demo or "
                "the label store is left out, never overwritten; a token contract or an address with no activity "
                "on this chain is left out; contract code -> contract_wallet, with no role (Bitget gives none)",
        "source": {"url": URL, "request": 'POST {"auditId": "<audit id>"}', "page": PAGE, "archive": None,
                   "archive_note": "an answer to a POST has no Internet Archive copy; the answers cited are kept "
                                   "byte for byte in backend/tests/fixtures/bitget_por/"},
    }
    written = {c: r for c, r in new_rows.items() if r}
    by_chain = {}
    for chain, found in written.items():
        ids = sorted({r["source_audit"] for r in found.values()}, reverse=True)
        by_chain[chain] = {**note, "audits_cited": {
            i: {"snapshot_date": audits[i]["snapshot"], "retrieved_utc": audits[i]["retrieved"],
                "sha256": audits[i]["sha256"], "bytes": audits[i]["bytes"]} for i in ids},
            "audits_read": {i: a["sha256"] for i, a in sorted(audits.items(), reverse=True)},
            "left_out": left[chain] + conflicts[chain]}
    for chain, found in written.items():
        print(por.apply({chain: found}, by_chain[chain], meta_key=META_KEY))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
