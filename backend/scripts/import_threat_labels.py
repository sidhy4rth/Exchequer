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

Scam lists
----------
`--scam-lists` adds reported phishing and scam wallets from three published
lists, all pinned: ScamSniffer's address blacklist (a Web3 security vendor,
updated daily, published with a 7-day delay), and two mirrors of Etherscan's
Phish/Hack label (dappcenter/etherscan-labels and Forta's labelled datasets).
They join the `stolen` category; each entry names the lists that report it.
The Etherscan lists are Ethereum's; ScamSniffer names no chain, so each of its
addresses is filed under every EVM chain it has been used on. Existing entries
are kept, and addresses already on a sanctions list are skipped. Progress is
checkpointed, so an interrupted run resumes.

    cd backend && .venv/bin/python -m scripts.import_threat_labels --scam-lists --checkpoint scam_check.jsonl
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


def used_on_ethereum(client: EtherscanClient, address: str) -> bool:
    """At least one transaction, ever: the address exists and has been used."""
    return bool(client.get_transactions(address, limit=1, sort="asc", include_internal=False))


def used_on_bsc(client: NoderealClient, address: str) -> bool:
    """A nonce, contract code or a balance: the address has been used on BSC."""
    if int(client._rpc("eth_getTransactionCount", [address, "latest"]) or "0x0", 16) > 0:
        return True
    if (client._rpc("eth_getCode", [address, "latest"]) or "0x") != "0x":
        return True
    return int(client._rpc("eth_getBalance", [address, "latest"]) or "0x0", 16) > 0


SCAMSNIFFER = ("scamsniffer/scam-database", "753310a5c8ae9b83d8d05ae21e3b2ae60bf87c98")
PHISH_HACK = ("dappcenter/etherscan-labels", "d547040b8bf65577945bcc53cec62a96945cc705")
FORTA = ("forta-network/labelled-datasets", "40a9c2f2bd7e9ddfdd0f3540db589f0288e1e88a")


def raw(repo_commit: tuple[str, str], path: str) -> bytes:
    repo, commit = repo_commit
    with urllib.request.urlopen(f"https://raw.githubusercontent.com/{repo}/{commit}/{path}", timeout=120) as r:
        return r.read()


def scam_candidates() -> dict[str, dict]:
    """{address: {tag, sources, etherscan}} across the three lists."""
    out: dict[str, dict] = {}

    def add(address: str, tag: str, source: str, etherscan: bool) -> None:
        addr = normalize_address(address)
        if not is_valid_address(addr):
            return
        row = out.setdefault(addr, {"tag": "", "sources": [], "etherscan": False})
        row["tag"] = row["tag"] or (tag or "").strip()
        if source not in row["sources"]:
            row["sources"].append(source)
        row["etherscan"] = row["etherscan"] or etherscan

    for address in json.loads(raw(SCAMSNIFFER, "blacklist/address.json")):
        add(address, "", f"ScamSniffer address blacklist @ {SCAMSNIFFER[1][:10]}", False)
    etherscan_src = "Etherscan Phish/Hack label"
    for row in json.loads(raw(PHISH_HACK, "src/hack-addresses.json")):
        add(row["address"], row.get("nameTag", ""), f"{etherscan_src}, via {PHISH_HACK[0]} @ {PHISH_HACK[1][:10]}", True)
    for path, key, tag_key in (("labels/1/phishing_scams.csv", "address", "etherscan_tag"),
                               ("labels/1/etherscan_malicious_labels.csv", "banned_address", "wallet_tag")):
        for row in csv.DictReader(io.StringIO(raw(FORTA, path).decode())):
            add(row[key], row.get(tag_key, ""), f"{etherscan_src}, via {FORTA[0]} @ {FORTA[1][:10]}", True)
    return out


def scam_entity(tag: str) -> tuple[str, str]:
    """(entity, label) for a reported scam wallet."""
    found = classify(tag) if tag else None
    if found and found[0] == STOLEN:
        return found[1], tag
    return "Reported phishing / scam wallet", tag or "Reported phishing / scam wallet"


def import_scam_lists(checkpoint: Path, dry_run: bool) -> int:
    from scripts.import_eth_labels import has_any_activity

    candidates = scam_candidates()
    listed: set[str] = set()
    documents: dict[str, dict] = {}
    for key in CHAIN_IDS:
        chain = config.CHAINS[key]
        for path in (chain.risk_labels_path, chain.intl_sanctions_path):
            if path and path.exists():
                listed |= set(json.loads(path.read_text())["labels"])
        documents[key] = json.loads(chain.threat_labels_path.read_text())
    have = set(documents["ethereum"]["labels"]) | set(documents["bsc"]["labels"])
    todo = sorted(a for a in candidates if a not in listed and a not in have)

    done: dict[str, list[str]] = {}
    if checkpoint.exists():
        for line in checkpoint.read_text().splitlines():
            row = json.loads(line)
            done[row["address"]] = row["chains"]
    remaining = [a for a in todo if a not in done]
    print(f"{len(candidates)} reported addresses; {len(todo)} new; "
          f"{len(todo) - len(remaining)} already checked; {len(remaining)} to check", flush=True)

    bsc = NoderealClient(chain_slug="bsc-mainnet") if config.NODEREAL_API_KEY else None
    try:
        with EtherscanClient(chain_id=1) as eth, checkpoint.open("a") as log:
            for n, addr in enumerate(remaining, 1):
                chains = []
                try:
                    if has_any_activity(eth, addr):
                        chains.append("ethereum")
                    # Etherscan's list is Ethereum's own; only ScamSniffer's needs BSC checked.
                    if bsc and not candidates[addr]["etherscan"] and used_on_bsc(bsc, addr):
                        chains.append("bsc")
                except (EtherscanError, NoderealError, ValueError) as exc:
                    print(f"  ! {addr}: {str(exc)[:60]}", flush=True)
                    continue
                done[addr] = chains
                log.write(json.dumps({"address": addr, "chains": chains}) + "\n")
                log.flush()
                if n % 250 == 0:
                    print(f"  checked {len(todo) - len(remaining) + n}/{len(todo)}", flush=True)
    finally:
        if bsc:
            bsc.close()

    unchecked = [a for a in todo if a not in done]
    added = Counter()
    for addr in todo:
        for chain_key in done.get(addr, []):
            entity, label = scam_entity(candidates[addr]["tag"])
            documents[chain_key]["labels"][addr] = {
                "category": STOLEN, "entity": entity, "label": label,
                "source": "; ".join(candidates[addr]["sources"]),
            }
            added[chain_key] += 1
    unused = sum(1 for a in todo if done.get(a) == [])
    print(f"\nadded {dict(added)}  never used={unused}  unchecked={len(unchecked)}")
    if dry_run:
        print("--dry-run: nothing written.")
        return 0
    if unchecked:
        print("Some addresses could not be checked; re-run to finish before writing.")
        return 1
    for chain_key, document in documents.items():
        labels = document["labels"]
        counts = Counter(m["category"] for m in labels.values())
        meta = document["_meta"]
        meta["counts"] = {STOLEN: counts[STOLEN], MIXER: counts[MIXER]}
        meta["last_reviewed"] = datetime.now(timezone.utc).date().isoformat()
        meta["scam_lists"] = (
            f"{added[chain_key]} reported phishing/scam wallets from ScamSniffer ({SCAMSNIFFER[0]} "
            f"@ {SCAMSNIFFER[1]}) and Etherscan's Phish/Hack label ({PHISH_HACK[0]} @ {PHISH_HACK[1]}; "
            f"{FORTA[0]} @ {FORTA[1]}), each confirmed used on this chain. A report on a list is an "
            "accusation by that list, not a finding. Regenerate: cd backend && .venv/bin/python -m "
            "scripts.import_threat_labels --scam-lists"
        )
        document["labels"] = dict(sorted(labels.items(), key=lambda kv: (kv[1]["category"], kv[1]["entity"], kv[1]["label"])))
        config.CHAINS[chain_key].threat_labels_path.write_text(json.dumps(document, indent=2) + "\n")
        print(f"Wrote {len(labels)} labels to {config.CHAINS[chain_key].threat_labels_path}")
    return 0


def verify_ethereum(candidates: list[tuple[str, dict]]) -> tuple[dict, list[str]]:
    kept, dropped = {}, []
    with EtherscanClient(chain_id=1) as client:
        for addr, meta in candidates:
            try:
                used = used_on_ethereum(client, addr)
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
                used = used_on_bsc(client, addr)
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
    parser.add_argument("--scam-lists", action="store_true", help="add reported phishing/scam wallets instead")
    parser.add_argument("--checkpoint", type=Path, default=Path("scam_check.jsonl"),
                        help="progress file for --scam-lists, so an interrupted run resumes")
    args = parser.parse_args()

    if args.scam_lists:
        return import_scam_lists(args.checkpoint, args.dry_run)

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
