"""Measure, on chain, whether a role-less exchange contract_wallet is a sweep destination.

A `contract_wallet` row with no `role` is never a sweep destination in deposit
inference (app/deposit_inference.py): the label audit gave that type to deposit
forwarders too, and a wallet paying into a forwarder is the customer. A row
earns the role `hot_wallet` the way OKX's USDC consolidation proxy did (#248):
by measuring that many of the exchange's per-customer deposit addresses sweep
into it.

For each role-less contract_wallet on a chain this script reads keylessly from
Blockscout's public API (no key, no Etherscan):

  1. the wallet's most recent incoming ERC-20 transfers and native payments;
  2. a seeded random sample of their senders, leaving out any address an
     exchange label file names, any contract and anything Blockscout marks scam;
  3. each sampled sender's most recent outgoing ERC-20 transfers and payments.

A sampled sender is a sweeper when it sent the wallet at least two transfers
and sent value nowhere else, except to wallets the label files give to the
same exchange: the shape deposit inference reads as a deposit address. A wallet
with at least MIN_SWEEPERS sweepers is given `hot_wallet`; every other wallet
stays role-less, and the evidence file says why. A forwarder (by its recorded
code, scripts/check_label_code.py) is never given a role.

    cd backend && .venv/bin/python -m scripts.measure_contract_wallet_roles --record
    cd backend && .venv/bin/python -m scripts.measure_contract_wallet_roles --apply   # offline
    cd backend && .venv/bin/python -m scripts.measure_contract_wallet_roles --check   # offline

--record asks Blockscout and rewrites the evidence file; --apply writes its
roles into the label files; --check compares the two and writes nothing. Live data moves, so a
later --record can differ: the file keeps the date and the blocks it read.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.keccak import keccak256  # noqa: E402
from scripts import check_label_code as clc  # noqa: E402

EVIDENCE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "contract_wallet_roles.json"
# Ethereum only. On 15 and 16 Nov 2026 arbitrum.blockscout.com and polygon.blockscout.com
# answered every API call with a browser challenge (403), BSC has no Blockscout, and Routescan's
# keyless API answers "chain not supported" for all three. The keyless public nodes cannot do
# the method either: Arbitrum's refuses log reads without a token, and Polygon's and BSC's read
# logs only of one named contract over at most 10,000 or 50,000 blocks, so a sender's outflows in
# every token (and its native payments, which have no logs) cannot be read: "value nowhere
# else" could not be checked.
BLOCKSCOUT = {"ethereum": "https://eth.blockscout.com"}
MIN_SWEEPERS = 10   # #248's proxy had 31 in its sample; a single customer's forwarder has one
SAMPLE = 30         # senders read per wallet
WALLET_PAGES = 4    # 50 items a page: the wallet's newest 200 transfers in, and 200 payments in
SENDER_PAGES = 1    # the sender's newest 50 of each
PAUSE = 0.35
ROLE = "hot_wallet"
META_KEY = "contract_wallet_roles_2026_11_15"
# Measured, but the role is not set: a row another source owns exactly, or evidence too old to say
# what the wallet is today.
HELD = {
    "0x305dcaea67a9d4152e54e68060c89db05fd67a7b": (
        "its row comes from data/india_exchanges.json, which tests/test_india_exchanges.py holds to exactly "
        "exchange, label and type; giving it a role is a change to that seed, for the owner"),
    "0x51ca21ed46a9df3cb6f34624cbd482d312996730": (
        "every sweep read is from blocks 7.4M to 9.5M (2019-2020), so a hot role today would claim more "
        "than the reading shows (owner's decision, #262)"),
}


def roleless(chain: str) -> dict[str, dict[str, Any]]:
    """The contract wallets to measure: those with no role, and those whose role an earlier
    --apply set (listed in _meta), so a later --record measures them again."""
    document = json.loads(config.CHAINS[chain].labels_path.read_text(encoding="utf-8"))
    ours = document["_meta"].get(META_KEY, {}).get("given", {})
    return {a: m for a, m in document["labels"].items()
            if isinstance(m, dict) and m.get("type") == clc.CONTRACT_WALLET and (not m.get("role") or a in ours)}


CACHE: Path | None = None  # --cache DIR keeps every answer, so a re-run asks nothing twice
OFFLINE = False  # --offline: answer only from CACHE; a wallet with no cached answer is recorded as not measured yet
NOT_MEASURED_YET = "not measured yet: no cached Blockscout answer when this file was recorded offline"


class NotCached(Exception):
    """--offline and the cache has no answer for this request (never a RuntimeError: see measure)."""


def _get(base: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
    url = f"{base}/api/v2/{path}?{urllib.parse.urlencode(params)}"
    kept = CACHE / (keccak256(url.encode()).hex() + ".json") if CACHE else None
    if kept and kept.is_file():
        return json.loads(kept.read_text())
    if OFFLINE:
        raise NotCached(url)
    for attempt in range(5):
        time.sleep(PAUSE * (1 + 3 * attempt))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "label-check"}),
                                        timeout=60) as r:
                answer = json.loads(r.read())
            if kept:
                kept.write_text(json.dumps(answer))
            return answer
        except (urllib.error.URLError, TimeoutError, ValueError):
            continue
    raise RuntimeError(f"no answer from {base} for {path}")


def _pages(base: str, path: str, params: dict[str, Any], pages: int) -> tuple[list[dict], bool]:
    """Up to `pages` pages of items, and whether more were left unread."""
    items: list[dict] = []
    query = dict(params)
    for _ in range(pages):
        page = _get(base, path, query)
        items += page.get("items") or []
        if not page.get("next_page_params"):
            return items, False
        query = {**params, **page["next_page_params"]}
    return items, True


def _lower(party: dict | None) -> str:
    return ((party or {}).get("hash") or "").lower()


def _flows(base: str, address: str, direction: str, pages: int) -> tuple[list[dict], bool]:
    """Value transfers into or out of `address`: [{party, is_contract, is_scam, block}].

    A zero-value token transfer is left out: anyone can emit one "from" any
    address (address poisoning), so it says nothing about where it pays."""
    side = "from" if direction == "to" else "to"
    tokens, more_t = _pages(base, f"addresses/{address}/token-transfers", {"type": "ERC-20", "filter": direction}, pages)
    txs, more_x = _pages(base, f"addresses/{address}/transactions", {"filter": direction}, pages)
    out = [{"party": _lower(t.get(side)), "is_contract": bool((t.get(side) or {}).get("is_contract")),
            "is_scam": bool((t.get(side) or {}).get("is_scam")) or (t.get("token") or {}).get("reputation") not in (None, "ok"),
            "block": t.get("block_number")}
           for t in tokens if int((t.get("total") or {}).get("value") or 0) > 0]  # zero-value: address poisoning
    out += [{"party": _lower(x.get(side)), "is_contract": bool((x.get(side) or {}).get("is_contract")),
             "is_scam": bool((x.get(side) or {}).get("is_scam")), "block": x.get("block_number") or x.get("block")}
            for x in txs if int(x.get("value") or 0) > 0 and x.get("status") in (None, "ok")]
    return [f for f in out if f["party"]], more_t or more_x


def measure(chain: str, address: str, row: dict[str, Any], all_labels: dict[str, dict], code: Any) -> dict[str, Any]:
    if chain not in BLOCKSCOUT:
        return {"role": None, "why": f"not measured: no keyless indexer answered for {chain} (see BLOCKSCOUT)"}
    if code is not None and clc.classify(code)[0] == clc.FORWARDER:
        return {"role": None, "why": "not measured: a forwarder by its recorded code, never a sweep destination"}
    try:
        return _measured(chain, address, all_labels, BLOCKSCOUT[chain], row["exchange"])
    except NotCached:
        return {"role": None, "why": NOT_MEASURED_YET}


def _measured(chain: str, address: str, all_labels: dict[str, dict], base: str, exchange: str) -> dict[str, Any]:
    inflow, _ = _flows(base, address, "to", WALLET_PAGES)
    blocks = [f["block"] for f in inflow if f["block"]]
    senders = sorted({f["party"] for f in inflow if f["party"] != address and not f["is_contract"]
                      and not f["is_scam"] and f["party"] not in all_labels})
    sample = random.Random(f"{chain}:{address}").sample(senders, min(SAMPLE, len(senders)))
    sweepers, unread = [], 0
    for sender in sorted(sample):
        try:
            out, _ = _flows(base, sender, "from", SENDER_PAGES)
        except RuntimeError:  # Blockscout gave up on it: never counted as a sweeper
            unread += 1
            continue
        out = [f for f in out if not f["is_scam"]]
        to_wallet = sum(f["party"] == address for f in out)
        elsewhere = {f["party"] for f in out if f["party"] != address
                     and (all_labels.get(f["party"]) or {}).get("exchange") != exchange}
        if to_wallet >= 2 and not elsewhere:
            sweepers.append(sender)
    found = {"transfers_in_read": len(inflow), "blocks_read": [min(blocks), max(blocks)] if blocks else None,
             "unlabelled_senders": len(senders), "sampled": len(sample), "sweepers": len(sweepers)}
    if unread:
        found["senders_unread"] = unread
    if len(sweepers) >= MIN_SWEEPERS:
        why = f"{len(sweepers)} of {len(sample)} sampled senders sent it 2+ transfers and value nowhere else"
        if address in HELD:
            return {**found, "role": None, "sweeper_addresses": sweepers, "why": f"{why}; role not set: {HELD[address]}"}
        return {**found, "role": ROLE, "sweeper_addresses": sweepers, "why": why}
    why = ("no unlabelled sender among its newest transfers in" if not senders else
           f"{len(sweepers)} of {len(sample)} sampled senders swept only into it (needs {MIN_SWEEPERS})")
    return {**found, "role": None, "why": why}


WORKERS = 3  # wallets read at once


def record() -> dict[str, Any]:
    code = json.loads(clc.ANSWERS.read_text(encoding="utf-8"))["code"]
    jobs = []
    for chain, cfg in config.CHAINS.items():
        if cfg.address_family == "evm":
            all_labels = json.loads(cfg.labels_path.read_text(encoding="utf-8"))["labels"]
            jobs += [(chain, a, row, all_labels) for a, row in sorted(roleless(chain).items())]

    def one(job):
        chain, address, row, all_labels = job
        result = measure(chain, address, row, all_labels, code.get(address) if chain == "ethereum" else None)
        print(f"{chain:9} {address} {row['label'][:28]:28} {result['role'] or '-':10} {result['why']}", flush=True)
        return chain, address, {"label": row["label"], **result}

    out: dict[str, Any] = {"_meta": {"read": date.today().isoformat(), "source": "Blockscout public API v2, keyless",
                                     "min_sweepers": MIN_SWEEPERS, "sample": SAMPLE,
                                     "wallet_pages": WALLET_PAGES, "sender_pages": SENDER_PAGES}}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for chain, address, seen in pool.map(one, jobs):
            out.setdefault(chain, {})[address] = seen
    return out


def check(evidence: dict[str, Any]) -> list[str]:
    """Every contract_wallet the evidence measured: role in the label file == role measured."""
    problems = []
    for chain, rows in evidence.items():
        if chain.startswith("_"):
            continue
        labels = json.loads(config.CHAINS[chain].labels_path.read_text(encoding="utf-8"))["labels"]
        for address, seen in rows.items():
            have = (labels.get(address) or {}).get("role")
            if have != seen["role"]:
                problems.append(f"{chain} {address}: label role {have!r}, measured {seen['role']!r}")
    return problems


def dump(evidence: dict[str, Any]) -> str:
    """JSON with one line per wallet, so the file stays readable in a diff."""
    def line(value: Any) -> str:
        return json.dumps(value, sort_keys=True)
    parts = []
    for key in sorted(evidence):
        if key.startswith("_"):
            parts.append(f" {line(key)}: {line(evidence[key])}")
        else:
            rows = ",\n".join(f"  {line(a)}: {line(evidence[key][a])}" for a in sorted(evidence[key]))
            parts.append(f" {line(key)}: {{\n{rows}\n }}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def apply(evidence: dict[str, Any]) -> list[str]:
    """Write each measured role into its label file, with a note in _meta; returns the files written."""
    written = []
    for chain, rows in evidence.items():
        if chain.startswith("_") or not any(seen["role"] for seen in rows.values()):
            continue
        path = config.CHAINS[chain].labels_path
        text = path.read_text(encoding="utf-8")
        document = json.loads(text)
        given = {}
        for address, seen in rows.items():
            if seen["role"]:
                document["labels"][address]["role"] = seen["role"]
                given[address] = f"{seen['why']} ({seen['label']})"
        document["_meta"][META_KEY] = {
            "rule": ("A contract_wallet is given the role hot_wallet only when, read on chain, at least "
                     f"{MIN_SWEEPERS} unlabelled senders in a seeded sample of up to {SAMPLE} of its newest "
                     "incoming senders each sent it two or more transfers and sent value nowhere else (except to "
                     "the same exchange's labelled wallets): the sweep shape #248 used for OKX's USDC proxy. "
                     "Evidence: tests/fixtures/contract_wallet_roles.json, by "
                     "scripts/measure_contract_wallet_roles.py --record (Blockscout public API, keyless, "
                     f"read {evidence['_meta']['read']}). Every other contract_wallet stays role-less."),
            "given": dict(sorted(given.items())),
        }
        path.write_text(json.dumps(document, indent=clc._indent(text)) + "\n", encoding="utf-8")
        written.append(path.name)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--record", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true", help="write the evidence file's roles into the label files")
    parser.add_argument("--cache", type=Path, help="keep every Blockscout answer in this directory")
    parser.add_argument("--offline", action="store_true",
                        help="with --record and --cache: ask nothing; a wallet with no cached answer is not measured yet")
    args = parser.parse_args()
    global CACHE, OFFLINE
    if args.offline and not (args.record and args.cache):
        parser.error("--offline needs --record and --cache")
    OFFLINE = args.offline
    if args.cache:
        args.cache.mkdir(parents=True, exist_ok=True)
        CACHE = args.cache
    if args.record:
        EVIDENCE.write_text(dump(record()), encoding="utf-8")
        print(f"wrote {EVIDENCE}")
        return 0
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    if args.apply:
        print("wrote", ", ".join(apply(evidence)) or "nothing")
        return 0
    problems = check(evidence)
    print("\n".join(problems) or "label roles match the measured evidence")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
