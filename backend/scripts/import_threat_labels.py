"""Build data/threat_labels*.json: hack/phishing wallets and mixer pools.

The OFAC file answers "did the money touch a designated party". It cannot
answer the two questions a fraud investigator asks next, because OFAC lists
neither: did the money pass through a known theft (the WazirX or Bybit
exploiter wallets), and was it laundered through a mixer (Tornado Cash has
been off the SDN list since March 2025, but its pools still commingle funds).

Source
------
dawsbot/eth-labels, pinned to a commit: a published scrape of Etherscan's and
BscScan's own address tags, the same source import_eth_labels.py uses for
exchanges. These are the explorer's attributions, not government
designations, and every entry says so in its `source`.

Selection
---------
  stolen  A tag naming the perpetrator of a theft -- "Exploiter", "Hacker",
          "Attacker" -- or Etherscan's "Fake_Phishing" flag. Tags that only
          contain the word (a hackerspace charity, a "Hack Alert" contract)
          do not match, and "Compromised" wallets are left out: those are
          the victims.
  mixer   Only the pools and the router that deposits into them -- the
          contracts where funds actually commingle. A mixer's governance,
          token, vesting and verifier contracts are not a laundering hop.

An address already on the OFAC file is skipped: the designation is the
stronger fact and the risk matcher would ignore this entry anyway.

Verification
------------
Each address must exist on chain as something that has been used: at least
one transaction on Ethereum; a nonce, contract code or balance on BSC. The
check is deliberately about existence, not recency -- a 2021 exploiter wallet
that has gone quiet is exactly as relevant to a trace that reaches it.

    cd backend && .venv/bin/python -m scripts.import_threat_labels
    cd backend && .venv/bin/python -m scripts.import_threat_labels --chain bsc --dry-run
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import (  # noqa: E402
    EtherscanClient,
    EtherscanError,
    is_valid_address,
    normalize_address,
)
from app.nodereal_client import NoderealClient, NoderealError  # noqa: E402
from app.risk_matcher import MIXER, STOLEN  # noqa: E402

DATASET_REPO = "dawsbot/eth-labels"
DATASET_COMMIT = "14247ba8cf4686b747938248bee34c66089fa9d9"
SOURCE_URL = (
    f"https://raw.githubusercontent.com/{DATASET_REPO}/{DATASET_COMMIT}"
    "/data/csv/accounts.csv"
)

CHAIN_IDS = {"ethereum": "1", "bsc": "56"}
EXPLORER = {"ethereum": "Etherscan", "bsc": "BscScan"}

THIEF = re.compile(r"^(?P<name>.+?)\s+(?P<role>exploiter|hacker|attacker)\b", re.IGNORECASE)
PHISHING = re.compile(r"^fake_phishing\d*$", re.IGNORECASE)
NOT_A_THIEF = re.compile(r"endaoment|avs operator|hack alert", re.IGNORECASE)

MIXER_SERVICE = re.compile(
    r"^(?P<service>Tornado\.Cash|Typhoon\.Cash|Typhoon Network|Privacy Pools):?\s+(?P<part>.+)$"
)
# "100 ETH", "5,000,000 cDAI", "10,000 DAI 2": a fixed-denomination pool.
POOL = re.compile(r"^[\d.,]+\s+[A-Za-z]+(\s+\d+)?$")
ENTRYPOINTS = {"Router", "Proxy", "Old Proxy", "Mixer 1", "Mixer 2", "Deposit", "Simple"}
SERVICE_NAME = {"Tornado.Cash": "Tornado Cash", "Typhoon.Cash": "Typhoon Cash",
                "Typhoon Network": "Typhoon Network", "Privacy Pools": "Privacy Pools"}


def classify(tag: str) -> tuple[str, str] | None:
    """(category, entity) for a tag this file should hold, else None."""
    tag = tag.strip()
    if PHISHING.match(tag):
        return STOLEN, "Phishing wallet"
    thief = THIEF.match(tag)
    if thief and not NOT_A_THIEF.search(tag):
        role = "hack" if thief["role"].lower() == "hacker" else thief["role"].lower()
        role = {"exploiter": "exploit", "attacker": "attack"}.get(role, role)
        return STOLEN, f"{thief['name'].strip()} {role}"
    mixer = MIXER_SERVICE.match(tag)
    if mixer and (POOL.match(mixer["part"]) or mixer["part"] in ENTRYPOINTS):
        return MIXER, SERVICE_NAME[mixer["service"]]
    return None


def candidates_by_chain() -> dict[str, dict[str, dict[str, str]]]:
    with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:
        rows = csv.DictReader(io.StringIO(response.read().decode()))
        wanted = {cid: key for key, cid in CHAIN_IDS.items()}
        out: dict[str, dict[str, dict[str, str]]] = {key: {} for key in CHAIN_IDS}
        for row in rows:
            chain_key = wanted.get(row["chainId"])
            addr = normalize_address(row["address"])
            found = classify(row["nameTag"] or "") if chain_key else None
            if found is None or not is_valid_address(addr):
                continue
            category, entity = found
            out[chain_key][addr] = {
                "category": category,
                "entity": entity,
                "label": row["nameTag"].strip(),
                "source": (
                    f"{EXPLORER[chain_key]} address tag, via {DATASET_REPO} "
                    f"@ {DATASET_COMMIT[:10]}"
                ),
            }
    # One incident, one name: the tags spell "Bybit" and "ByBit" both, and a
    # report grouping by entity must not split them. The commonest spelling wins.
    spellings = Counter(m["entity"] for labels in out.values() for m in labels.values())
    canonical = {}
    for name, _ in spellings.most_common():
        canonical.setdefault(name.lower(), name)
    for labels in out.values():
        for meta in labels.values():
            meta["entity"] = canonical[meta["entity"].lower()]
    return out


def verify_ethereum(candidates: list[tuple[str, dict]]) -> tuple[dict, list[str]]:
    kept, dropped = {}, []
    with EtherscanClient(chain_id=1) as client:
        for addr, meta in candidates:
            try:
                used = bool(client.get_transactions(addr, limit=1, sort="asc", include_internal=False))
            except (EtherscanError, ValueError) as exc:
                dropped.append(f"{addr} {meta['label']}: {str(exc)[:40]}")
                continue
            print(f"{addr}  {meta['label']:<36} {'ok' if used else 'UNUSED'}")
            if used:
                kept[addr] = meta
            else:
                dropped.append(f"{addr} {meta['label']}: no transactions")
    return kept, dropped


def verify_bsc(candidates: list[tuple[str, dict]]) -> tuple[dict, list[str]]:
    kept, dropped = {}, []
    client = NoderealClient(chain_slug="bsc-mainnet")
    try:
        for addr, meta in candidates:
            try:
                used = int(client._rpc("eth_getTransactionCount", [addr, "latest"]) or "0x0", 16) > 0
                if not used:
                    used = (client._rpc("eth_getCode", [addr, "latest"]) or "0x") != "0x"
                if not used:
                    used = int(client._rpc("eth_getBalance", [addr, "latest"]) or "0x0", 16) > 0
            except (NoderealError, ValueError) as exc:
                dropped.append(f"{addr} {meta['label']}: {str(exc)[:40]}")
                continue
            print(f"{addr}  {meta['label']:<36} {'ok' if used else 'UNUSED'}")
            if used:
                kept[addr] = meta
            else:
                dropped.append(f"{addr} {meta['label']}: never used")
    finally:
        client.close()
    return kept, dropped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chain", choices=[*CHAIN_IDS, "all"], default="all")
    parser.add_argument("--dry-run", action="store_true", help="verify but do not write")
    args = parser.parse_args()

    chains = list(CHAIN_IDS) if args.chain == "all" else [args.chain]
    if "bsc" in chains and not config.NODEREAL_API_KEY:
        print("NODEREAL_API_KEY is not set; BSC cannot be queried.")
        return 1

    print(f"Dataset: {DATASET_REPO} @ {DATASET_COMMIT[:10]}")
    found = candidates_by_chain()

    for chain_key in chains:
        chain = config.CHAINS[chain_key]
        sanctioned = set(json.loads(chain.risk_labels_path.read_text())["labels"])
        ordered = sorted(
            (a, m) for a, m in found[chain_key].items() if a not in sanctioned
        )
        print(f"\n== {chain_key}: {len(ordered)} candidates "
              f"({len(found[chain_key]) - len(ordered)} already on the OFAC file)\n")
        verify = verify_ethereum if chain_key == "ethereum" else verify_bsc
        kept, dropped = verify(ordered)

        counts = Counter(m["category"] for m in kept.values())
        print(f"\n{chain_key}: kept={len(kept)} ({counts[STOLEN]} stolen, {counts[MIXER]} mixer)  "
              f"dropped={len(dropped)}")
        for line in dropped:
            print(f"  - {line}")
        if args.dry_run:
            continue
        if not kept:
            print("Nothing verified; not writing an empty file.")
            continue

        document = {
            "_meta": {
                "description": (
                    "Wallets tied to known hacks and phishing thefts, and mixer "
                    "pools, that Exchequer screens a trace against. OFAC lists "
                    "neither, so this file fills the gap the sanctions file "
                    "leaves."
                ),
                "provenance": (
                    f"The block explorer's own address tags ({EXPLORER[chain_key]}), "
                    f"from {DATASET_REPO} @ {DATASET_COMMIT}, a published scrape of "
                    "them, selected and verified by "
                    "backend/scripts/import_threat_labels.py."
                ),
                "verification_note": (
                    "Every address was confirmed to exist and to have been used "
                    "on chain. The attribution itself is the explorer's -- strong, "
                    "public, but not a government designation. A match means the "
                    "funds touched a wallet the explorer ties to a theft or a "
                    "mixer; it does NOT mean any counterparty took part in it. "
                    "Re-check the tag on the explorer before evidentiary use."
                ),
                "category_note": (
                    "'stolen' marks wallets run by the perpetrator of a hack or a "
                    "phishing campaign; a trace continues through them. 'mixer' "
                    "marks pools where deposits commingle; a trace stops there."
                ),
                "chain": chain_key,
                "last_reviewed": datetime.now(timezone.utc).date().isoformat(),
                "counts": {STOLEN: counts[STOLEN], MIXER: counts[MIXER]},
                "regenerate_with": (
                    "cd backend && .venv/bin/python -m scripts.import_threat_labels"
                ),
                "schema": "labels maps an address to {category, entity, label, source}",
            },
            "labels": dict(sorted(kept.items(), key=lambda kv: (kv[1]["category"], kv[1]["entity"], kv[1]["label"]))),
        }
        chain.threat_labels_path.write_text(json.dumps(document, indent=2) + "\n")
        print(f"Wrote {len(kept)} labels to {chain.threat_labels_path}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
