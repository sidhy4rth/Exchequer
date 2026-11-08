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
          "Attacker". Tags that only contain the word (a hackerspace
          charity, a "Hack Alert" contract) do not match, and "Compromised"
          wallets are left out: those are the victims. So are whitehat,
          rescue and bot tags ("Multichain Exploiter 4 (Whitehat)", "Uniswap
          V2: BOT"): they returned or front-ran funds, they did not steal them.
  scam    Etherscan's "Fake_Phishing" flag: a reported phishing wallet, not a
          named theft.
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
updated daily, published with a 7-day delay, open to community reports), and
two mirrors of Etherscan's Phish/Hack label (dappcenter/etherscan-labels and
Forta's labelled datasets). They are filed as `scam`, a report by that list;
only a tag naming a theft's perpetrator ("X Exploiter") is `stolen`. Each
entry names the lists that report it. The Etherscan lists are Ethereum's;
ScamSniffer names no chain, so each of its addresses is also filed under BSC
when the same account has been used there: it has sent a transaction (nonce
above zero) and holds no contract code, the rule port_evm_labels.py uses. Any
code at the address on BSC may be an unrelated contract, and a balance alone
is a dust send anyone can make. Existing entries
are kept, and addresses already on a sanctions list are skipped. Progress is
checkpointed, so an interrupted run resumes.

    cd backend && .venv/bin/python -m scripts.import_threat_labels --scam-lists --checkpoint scam_check.jsonl

`--recategorise` re-files the held threat files under the rules above, offline.
`--recheck-bsc --rpc URL` re-checks the BSC file's ScamSniffer-only entries
against the account rule through any BSC JSON-RPC endpoint (a keyless public
one is enough), and removes those that fail it.
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

from app import config, never_flag  # noqa: E402
from app.etherscan_client import (  # noqa: E402
    EtherscanClient,
    EtherscanError,
    is_valid_address,
    normalize_address,
)
from app.label_rules import ENTRYPOINTS, MIXER_SERVICE, POOL, SERVICE_NAME  # noqa: E402
from app.nodereal_client import NoderealClient, NoderealError  # noqa: E402
from app.risk_matcher import MIXER, SCAM, STOLEN  # noqa: E402
from scripts._label_files import ShrinkRefused, chain_regenerate, merge_owned  # noqa: E402

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
# Tags that name someone who rescued, returned or front-ran funds: never a thief or a scam.
EXCLUDED = re.compile(r"white ?hat|rescue|returned|\bbot\b|\bmev\b", re.IGNORECASE)



def classify(tag: str) -> tuple[str, str] | None:
    """(category, entity) for a tag this file should hold, else None."""
    tag = tag.strip()
    if EXCLUDED.search(tag):
        return None
    if PHISHING.match(tag):
        return SCAM, "Phishing wallet"
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


def account_used_on_bsc(client, address: str) -> bool:
    """The same key's account on BSC: it has sent a transaction (nonce > 0) and holds no code.

    Contract code there may be an unrelated contract at the same address, and a
    balance alone is a dust send anyone can make. A missing result is an error,
    never a "no".
    """
    nonce = client._rpc("eth_getTransactionCount", [address, "latest"])
    code = client._rpc("eth_getCode", [address, "latest"])
    if not isinstance(nonce, str) or not isinstance(code, str):
        raise NoderealError(f"no result for {address}")
    return int(nonce, 16) > 0 and code in ("0x", "0x0")


def used_on_bsc(client: NoderealClient, address: str) -> bool:
    """A nonce, contract code or a balance: the address has been used on BSC.

    For placing a government-listed address, not for copying a scam report
    (that is account_used_on_bsc). A missing result is an error, never a "no".
    """
    def ask(method: str) -> str:
        result = client._rpc(method, [address, "latest"])
        if not isinstance(result, str):
            raise NoderealError(f"{method}: no result for {address}")
        return result
    if int(ask("eth_getTransactionCount"), 16) > 0:
        return True
    if ask("eth_getCode") not in ("0x", "0x0"):
        return True
    return int(ask("eth_getBalance"), 16) > 0


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


GENERIC_SCAM = "Reported phishing / scam wallet"


def scam_entity(tag: str) -> tuple[str, str, str] | None:
    """(category, entity, label) for a wallet a scam list reports, or None to leave it out.

    A list's report is `scam`. Only a tag naming a theft's perpetrator makes it
    `stolen`; a whitehat, rescue or bot tag is no one to accuse.
    """
    if tag and EXCLUDED.search(tag):
        return None
    found = classify(tag) if tag else None
    if found and found[0] == STOLEN:
        return STOLEN, found[1], tag
    if found and found[0] == SCAM:
        return SCAM, found[1], tag
    return SCAM, GENERIC_SCAM, tag or GENERIC_SCAM


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
    # A list is wrong about an exchange wallet, router, token contract, casino
    # or burn address, whatever it says; skipped before any call is spent.
    infrastructure = {a for a in candidates
                      if any(never_flag.kind(key, a, with_gambling=True) for key in CHAIN_IDS)}
    if infrastructure:
        print(f"{len(infrastructure)} listed addresses are exchanges, routers, tokens or casinos; left out")
    todo = sorted(a for a in candidates if a not in listed and a not in have and a not in infrastructure)

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
                    if bsc and not candidates[addr]["etherscan"] and account_used_on_bsc(bsc, addr):
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
        filed = scam_entity(candidates[addr]["tag"])
        if filed is None:
            continue  # a whitehat, rescue or bot tag
        category, entity, label = filed
        for chain_key in done.get(addr, []):
            documents[chain_key]["labels"][addr] = {
                "category": category, "entity": entity, "label": label,
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
        meta = document["_meta"]
        meta["counts"] = _counts(labels)
        meta["category_note"] = CATEGORY_NOTE
        meta["regenerate_with"] = chain_regenerate(meta.get("regenerate_with"), BASE_RUN, SCAM_RUN)
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


CATEGORY_NOTE = (
    "'stolen' marks wallets a tag names as the perpetrator of a hack or exploit; 'scam' marks "
    "wallets a published scam or phishing list reports (an accusation by that list); a trace "
    "continues through both. 'mixer' marks pools where deposits commingle; a trace stops there."
)


def _counts(labels: dict[str, dict]) -> dict[str, int]:
    counts = Counter(m["category"] for m in labels.values())
    return {STOLEN: counts[STOLEN], SCAM: counts[SCAM], MIXER: counts[MIXER]}


def _ordered(labels: dict[str, dict]) -> dict[str, dict]:
    return dict(sorted(labels.items(), key=lambda kv: (kv[1]["category"], kv[1]["entity"], kv[1]["label"])))


def refile(entry: dict) -> dict | None:
    """One held entry under today's rules, or None to remove it. No network."""
    label = entry.get("label") or ""
    if EXCLUDED.search(label):
        return None
    found = classify(label)
    if found and found[0] in (STOLEN, MIXER):
        return {**entry, "category": found[0]}
    if entry["category"] == MIXER:
        return entry
    return {**entry, "category": SCAM}


def recategorise(dry_run: bool) -> int:
    """Re-file the held threat files under the rules above. Reads and writes local files only."""
    today = datetime.now(timezone.utc).date().isoformat()
    for chain_key in CHAIN_IDS:
        path = config.CHAINS[chain_key].threat_labels_path
        document = json.loads(path.read_text())
        before = Counter(m["category"] for m in document["labels"].values())
        labels, removed = {}, {}
        for address, entry in document["labels"].items():
            new = refile(entry)
            if new is None:
                removed[address] = entry["label"]
            else:
                labels[address] = new
        meta = document["_meta"]
        meta["counts"] = _counts(labels)
        meta["category_note"] = CATEGORY_NOTE
        meta["recategorised"] = {
            "date": today,
            "before": dict(before),
            "removed": removed,
            "note": ("Re-filed by import_threat_labels --recategorise: a scam or phishing list's report "
                     "is 'scam', not 'stolen'; only a tag naming a theft's perpetrator stays 'stolen'; "
                     "whitehat, rescue and bot tags are removed."),
        }
        document["labels"] = _ordered(labels)
        print(f"{chain_key}: {dict(before)} -> {meta['counts']}; removed {len(removed)}: {sorted(removed.values())}")
        if not dry_run:
            path.write_text(json.dumps(document, indent=2) + "\n")
    return 0


class PlainRpc:
    """A bare JSON-RPC client for --recheck-bsc, so it can use a keyless public endpoint."""

    def __init__(self, url: str) -> None:
        self.url = url

    def _rpc(self, method: str, params: list) -> object:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        # A name of its own: public endpoints (publicnode) refuse urllib's default with 403.
        request = urllib.request.Request(self.url, data=body, headers={
            "Content-Type": "application/json", "User-Agent": "Exchequer-list-import"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                reply = json.loads(response.read().decode())
        except (OSError, ValueError) as exc:
            raise NoderealError(f"{method}: {exc}") from exc
        if not isinstance(reply, dict) or "error" in reply:
            raise NoderealError(f"{method}: {reply.get('error') if isinstance(reply, dict) else reply}")
        return reply.get("result")


def recheck_bsc(client, dry_run: bool) -> int:
    """Remove BSC entries filed on ScamSniffer's word alone that fail account_used_on_bsc.

    An entry whose check errors is kept and listed: unknown is never "no".
    """
    path = config.CHAINS["bsc"].threat_labels_path
    document = json.loads(path.read_text())
    labels = document["labels"]
    only_scamsniffer = sorted(a for a, m in labels.items()
                              if m["source"].startswith("ScamSniffer") and ";" not in m["source"])
    removed, errors = [], []
    for n, address in enumerate(only_scamsniffer, 1):
        try:
            if not account_used_on_bsc(client, address):
                removed.append(address)
        except (NoderealError, ValueError) as exc:
            errors.append(f"{address}: {str(exc)[:60]}")
        if n % 100 == 0:
            print(f"  checked {n}/{len(only_scamsniffer)}", flush=True)
    for address in removed:
        del labels[address]
    print(f"checked {len(only_scamsniffer)}; removed {len(removed)}; errors {len(errors)} (kept)")
    for line in errors:
        print(f"  ! {line}")
    document["_meta"]["counts"] = _counts(labels)
    document["_meta"]["scam_lists_bsc_recheck"] = {
        "date": datetime.now(timezone.utc).date().isoformat(), "checked": len(only_scamsniffer),
        "removed": len(removed), "errors_kept": len(errors),
        "rule": "nonce > 0 and no contract code on BSC (import_threat_labels.account_used_on_bsc)",
    }
    if not dry_run:
        path.write_text(json.dumps(document, indent=2) + "\n")
    return 1 if errors else 0


BASE_RUN = "cd backend && .venv/bin/python -m scripts.import_threat_labels"
SCAM_RUN = "cd backend && .venv/bin/python -m scripts.import_threat_labels --scam-lists"
# How the explorer-tag run's own entries name their source; the scam lists' do not.
OWN_SOURCE = f"via {DATASET_REPO}"


def verify_ethereum(candidates: list[tuple[str, dict]]) -> tuple[dict, list[str], list[str]]:
    """(kept, dropped, errors): an address whose check failed is in `errors`, never dropped."""
    kept, dropped, errors = {}, [], []
    with EtherscanClient(chain_id=1) as client:
        for addr, meta in candidates:
            try:
                used = used_on_ethereum(client, addr)
            except (EtherscanError, ValueError) as exc:
                print(f"{addr}  {meta['label']:<36} ERROR {str(exc)[:40]}")
                errors.append(addr)
                continue
            print(f"{addr}  {meta['label']:<36} {'ok' if used else 'UNUSED'}")
            if used:
                kept[addr] = meta
            else:
                dropped.append(f"{addr} {meta['label']}: no transactions")
    return kept, dropped, errors


def verify_bsc(candidates: list[tuple[str, dict]]) -> tuple[dict, list[str], list[str]]:
    """(kept, dropped, errors), as verify_ethereum."""
    kept, dropped, errors = {}, [], []
    client = NoderealClient(chain_slug="bsc-mainnet")
    try:
        for addr, meta in candidates:
            try:
                used = used_on_bsc(client, addr)
            except (NoderealError, ValueError) as exc:
                print(f"{addr}  {meta['label']:<36} ERROR {str(exc)[:40]}")
                errors.append(addr)
                continue
            print(f"{addr}  {meta['label']:<36} {'ok' if used else 'UNUSED'}")
            if used:
                kept[addr] = meta
            else:
                dropped.append(f"{addr} {meta['label']}: never used")
    finally:
        client.close()
    return kept, dropped, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chain", choices=[*CHAIN_IDS, "all"], default="all")
    parser.add_argument("--dry-run", action="store_true", help="verify but do not write")
    parser.add_argument("--scam-lists", action="store_true", help="add reported phishing/scam wallets instead")
    parser.add_argument("--checkpoint", type=Path, default=Path("scam_check.jsonl"),
                        help="progress file for --scam-lists, so an interrupted run resumes")
    parser.add_argument("--recategorise", action="store_true", help="re-file the held files under today's rules, offline")
    parser.add_argument("--recheck-bsc", action="store_true",
                        help="re-check the BSC file's ScamSniffer-only entries (needs --rpc)")
    parser.add_argument("--rpc", help="with --recheck-bsc: a BSC JSON-RPC URL (a keyless public one will do)")
    parser.add_argument("--allow-shrink", action="store_true",
                        help="let the explorer-tag run remove more than a handful of its own entries")
    args = parser.parse_args()

    if args.recategorise:
        return recategorise(args.dry_run)
    if args.recheck_bsc:
        if not args.rpc:
            parser.error("--recheck-bsc needs --rpc")
        return recheck_bsc(PlainRpc(args.rpc), args.dry_run)
    if args.scam_lists:
        return import_scam_lists(args.checkpoint, args.dry_run)

    chains = list(CHAIN_IDS) if args.chain == "all" else [args.chain]
    if "bsc" in chains and not config.NODEREAL_API_KEY:
        print("NODEREAL_API_KEY is not set; BSC cannot be queried.")
        return 1

    print(f"Dataset: {DATASET_REPO} @ {DATASET_COMMIT[:10]}")
    found = candidates_by_chain()

    status = 0
    for chain_key in chains:
        chain = config.CHAINS[chain_key]
        sanctioned = set(json.loads(chain.risk_labels_path.read_text())["labels"])
        ordered = sorted(
            (a, m) for a, m in found[chain_key].items() if a not in sanctioned
        )
        print(f"\n== {chain_key}: {len(ordered)} candidates "
              f"({len(found[chain_key]) - len(ordered)} already on the OFAC file)\n")
        verify = verify_ethereum if chain_key == "ethereum" else verify_bsc
        kept, dropped, errors = verify(ordered)

        counts = Counter(m["category"] for m in kept.values())
        print(f"\n{chain_key}: kept={len(kept)} ({counts[STOLEN]} stolen, {counts[SCAM]} scam, {counts[MIXER]} mixer)  "
              f"dropped={len(dropped)}  errors={len(errors)}")
        for line in dropped:
            print(f"  - {line}")

        # The file also holds what --scam-lists merged in: this run replaces only
        # its own entries (the explorer tags), and a failed check keeps the old one.
        path = chain.threat_labels_path
        document = json.loads(path.read_text()) if path.exists() else {"_meta": {}, "labels": {}}
        held = document["labels"]
        new_unchecked = [a for a in errors if a not in held]
        if new_unchecked:
            print(f"{len(new_unchecked)} new candidates could not be checked; re-run to finish before writing.")
            status = 1
            continue
        try:
            labels, merge = merge_owned(
                held, kept, owned=lambda a, e, mine=found[chain_key]: a in mine or OWN_SOURCE in e.get("source", ""),
                unknown=set(errors), allow_shrink=args.allow_shrink)
        except ShrinkRefused as exc:
            print(f"{chain_key}: refused, nothing written: {exc}")
            status = 1
            continue
        print(f"{chain_key}: {dict(merge)}")
        if args.dry_run:
            continue
        if not labels:
            print("Nothing verified; not writing an empty file.")
            continue

        meta = document.setdefault("_meta", {})
        meta.update({
            "description": (
                "Wallets tied to known hacks, reported phishing and scam "
                "wallets, and mixer pools, that Exchequer screens a trace "
                "against. OFAC lists none of them, so this file fills the gap "
                "the sanctions file leaves."
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
            "category_note": CATEGORY_NOTE,
            "chain": chain_key,
            "last_reviewed": datetime.now(timezone.utc).date().isoformat(),
            "counts": _counts(labels),
            "regenerate_with": chain_regenerate(meta.get("regenerate_with"), BASE_RUN, SCAM_RUN),
            "schema": "labels maps an address to {category, entity, label, source}",
        })
        document["labels"] = _ordered(labels)
        path.write_text(json.dumps(document, indent=2) + "\n")
        print(f"Wrote {len(labels)} labels to {path}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
