"""Build the Polygon and Arbitrum label files from wallets already verified on Ethereum.

Why a port, not a scrape
------------------------
The published explorer scrapes are thin on these chains -- brianleect's
Polygonscan exchange page holds seven wallets. But an exchange's hot wallet is
an ordinary account (an EOA): one private key, and the same key controls the
same 0x address on every EVM chain. Binance's 0xf977…acec is Binance's on
Ethereum, Polygon and Arbitrum alike. So the Ethereum label file, whose every
entry was checked on chain when it was imported, already names these
exchanges' wallets on the other chains -- provided the address really is an
account there, and really is used.

The rule, per address and per chain:
  1. it is not a per-customer deposit address and not a contract wallet in the
     Ethereum file (deposits are tens of thousands of addresses, too many for a
     free API tier; contract addresses mean nothing across chains);
  2. it has no contract code on the target chain -- a contract at the same
     address on another chain can be something else entirely;
  3. it has *sent* at least one transaction on the target chain (nonce > 0).
     Receiving proves nothing -- spam tokens are airdropped to every
     well-known address -- but only the key holder can send, so a sent
     transaction shows the same key is in use there.
Explorer-tagged wallets from the scrapes (dawsbot for Arbitrum, brianleect for
both) are added under the same two on-chain checks.

The same reasoning carries the sanctions lists over: a designated address is
the designated person's key on every EVM chain, so OFAC and other governments'
Ethereum-listed accounts are screened on Polygon and Arbitrum too, under the
same account-and-activity checks, with the source saying so.

What this establishes: the address is an account the exchange (or designated
entity) controls on Ethereum, and it is live on the target chain. What it
does NOT establish: that the target-chain activity is the exchange's own --
it almost always is, since only the key holder can send from it.

    cd backend && .venv/bin/python -m scripts.port_evm_labels --checkpoint port.jsonl
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import EtherscanClient, EtherscanError, is_valid_address, normalize_address  # noqa: E402
from scripts.import_eth_labels import (CANONICAL, DATASET_COMMIT, DATASET_REPO, SKIP_SLUG,  # noqa: E402
                                       SKIP_TAG, tag_head, wallet_type)

TARGETS = ("polygon", "arbitrum")
# BNB Smart Chain has its own importers and a label file of its own; the port
# only adds to it (never replaces an entry), and reads the chain through
# NodeReal, since Etherscan's free tier does not serve it.
MERGE_TARGETS = ("bsc",)
DAWS_CHAIN_ID = {"arbitrum": "42161"}
BRIAN = ("https://raw.githubusercontent.com/brianleect/etherscan-labels/"
         "923aba72c7e2d0682f7ae6194b6140bd90668dc9/data/{site}/accounts/exchange.json")
BRIAN_SITE = {"polygon": "polygonscan", "arbitrum": "arbiscan"}
DAWS = f"https://raw.githubusercontent.com/{DATASET_REPO}/{DATASET_COMMIT}/data/csv/accounts.csv"
SKIP_TYPES = {"deposit_wallet", "contract_wallet"}


def ethereum_candidates() -> dict[str, dict[str, str]]:
    labels = json.loads(config.CHAINS["ethereum"].labels_path.read_text())["labels"]
    return {a: {**m, "source": "ethereum"} for a, m in labels.items() if m.get("type") not in SKIP_TYPES}


def scrape_candidates(chain_key: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with urllib.request.urlopen(BRIAN.format(site=BRIAN_SITE[chain_key]), timeout=300) as response:
        for address, tag in json.loads(response.read()).items():
            exchange = CANONICAL.get(tag_head(tag))
            if exchange and is_valid_address(address) and not SKIP_TAG.search(tag):
                out[normalize_address(address)] = {"exchange": exchange, "label": tag,
                                                   "type": wallet_type(tag), "source": "brianleect"}
    if chain_key in DAWS_CHAIN_ID:
        with urllib.request.urlopen(DAWS, timeout=300) as response:
            for row in csv.DictReader(io.StringIO(response.read().decode())):
                if row["chainId"] != DAWS_CHAIN_ID[chain_key] or SKIP_SLUG.search(row["label"]):
                    continue
                tag = (row["nameTag"] or "").strip()
                if not tag or tag == "null" or SKIP_TAG.search(tag):
                    continue
                exchange = CANONICAL.get(tag_head(tag))
                address = normalize_address(row["address"])
                if exchange and is_valid_address(address):
                    out.setdefault(address, {"exchange": exchange, "label": tag,
                                             "type": wallet_type(tag), "source": "dawsbot"})
    return out


def sanctioned_candidates() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    eth = config.CHAINS["ethereum"]
    for path in (eth.risk_labels_path, eth.intl_sanctions_path):
        for address, meta in json.loads(path.read_text())["labels"].items():
            if meta.get("category") == "sanctioned" and address not in out:
                out[address] = meta
    return out


class NoderealProbe:
    """The two on-chain questions, asked of NodeReal instead of Etherscan."""

    def __init__(self) -> None:
        from app.nodereal_client import NoderealClient
        self._client = NoderealClient(chain_slug="bsc-mainnet", native_symbol="BNB")

    def __enter__(self) -> "NoderealProbe":
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def _request(self, params: dict) -> str:
        return self._client._rpc(params["action"], [params["address"], "latest"])


def is_account(client: EtherscanClient, address: str) -> bool:
    code = client._request({"module": "proxy", "action": "eth_getCode", "address": address, "tag": "latest"})
    return code in ("0x", "", None)


def has_sent(client: EtherscanClient, address: str) -> bool:
    """The account's nonce on this chain: above zero only if its key has sent."""
    nonce = client._request({"module": "proxy", "action": "eth_getTransactionCount",
                             "address": address, "tag": "latest"})
    return int(nonce or "0x0", 16) > 0


def check(client: EtherscanClient, address: str) -> str:
    """'ok', 'contract' or 'inactive' -- the send test first, as most fail there."""
    if not has_sent(client, address):
        return "inactive"
    return "ok" if is_account(client, address) else "contract"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkpoint", type=Path, default=Path("port_evm.jsonl"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    done: dict[tuple[str, str, str], str] = {}
    if args.checkpoint.exists():
        for line in args.checkpoint.read_text().splitlines():
            r = json.loads(line)
            done[(r["chain"], r["kind"], r["address"])] = r["result"]

    eth_exchanges, sanctioned = ethereum_candidates(), sanctioned_candidates()
    today = datetime.now(timezone.utc).date().isoformat()
    with args.checkpoint.open("a") as log:
        for chain_key in (*TARGETS, *MERGE_TARGETS):
            chain = config.CHAINS[chain_key]
            merge = chain_key in MERGE_TARGETS
            exchanges = eth_exchanges if merge else {**scrape_candidates(chain_key), **eth_exchanges}
            work = [("exchange", a) for a in exchanges] + ([] if merge else [("sanctioned", a) for a in sanctioned])
            todo = [w for w in work if (chain_key, *w) not in done]
            print(f"{chain.name}: {len(exchanges)} exchange + {len(sanctioned)} sanctioned candidates, "
                  f"{len(todo)} left to check", flush=True)
            opened = NoderealProbe() if chain_key in MERGE_TARGETS else EtherscanClient(chain_id=chain.chain_id)
            with opened as client:
                for i, (kind, address) in enumerate(todo, 1):
                    try:
                        result = check(client, address)
                    except EtherscanError as exc:
                        result = f"error: {exc}"[:120]
                    done[(chain_key, kind, address)] = result
                    log.write(json.dumps({"chain": chain_key, "kind": kind, "address": address,
                                          "result": result}) + "\n")
                    log.flush()
                    if i % 50 == 0 or i == len(todo):
                        ok = sum(1 for (c, k, _), r in done.items() if c == chain_key and r == "ok")
                        print(f"  {i}/{len(todo)} checked · {ok} accepted so far", flush=True)

            accepted = {a: m for a, m in exchanges.items() if done.get((chain_key, "exchange", a)) == "ok"}
            listed = {a: m for a, m in sanctioned.items() if done.get((chain_key, "sanctioned", a)) == "ok"}
            by_source = {s: sum(1 for m in accepted.values() if m["source"] == s)
                         for s in ("ethereum", "dawsbot", "brianleect")}
            print(f"  accepted {len(accepted)} exchange wallets {by_source}, "
                  f"{len(listed)} sanctioned accounts", flush=True)
            if args.dry_run:
                continue
            if chain_key in MERGE_TARGETS:
                document = json.loads(chain.labels_path.read_text())
                held = document["labels"]
                added = {a: {k: v for k, v in m.items() if k != "source"}
                         for a, m in accepted.items() if a not in held}
                held.update(added)
                document["labels"] = dict(sorted(held.items()))
                document["_meta"]["ported_from_ethereum"] = (
                    f"{len(added)} Ethereum-labelled exchange accounts added {today} by "
                    "backend/scripts/port_evm_labels.py: each has no contract code on BNB Smart "
                    "Chain and has sent a transaction there (nonce > 0), read through NodeReal."
                )
                chain.labels_path.write_text(json.dumps(document, indent=1) + "\n")
                print(f"  added {len(added)} to {chain.labels_path.name}", flush=True)
                continue
            chain.labels_path.write_text(json.dumps({
                "_meta": {
                    "description": f"Exchange wallets on {chain.name}.",
                    "provenance": (
                        "Ethereum-labelled exchange accounts (non-deposit, non-contract) carried over "
                        "because one key controls one address on every EVM chain, plus explorer-tagged "
                        f"wallets from {DATASET_REPO} @ {DATASET_COMMIT[:10]} and brianleect/etherscan-labels "
                        "@ 923aba72. Built by backend/scripts/port_evm_labels.py."
                    ),
                    "verification_note": (
                        f"Every address has no contract code on {chain.name} and has sent at least one "
                        "transaction there (nonce > 0), which only its key holder can do. Re-check on the explorer before evidentiary use."
                    ),
                    "chain": chain_key, "last_reviewed": today, "counts": by_source,
                    "regenerate_with": "cd backend && .venv/bin/python -m scripts.port_evm_labels",
                },
                "labels": {a: {k: v for k, v in m.items() if k != "source"}
                           for a, m in sorted(accepted.items())},
            }, indent=1) + "\n")
            chain.risk_labels_path.write_text(json.dumps({
                "_meta": {
                    "description": f"Sanctioned accounts screened on {chain.name}.",
                    "provenance": (
                        "Ethereum addresses on OFAC's SDN list and other governments' lists, carried over "
                        "because a designated account is the same key on every EVM chain. Built by "
                        "backend/scripts/port_evm_labels.py."
                    ),
                    "verification_note": f"Each has no contract code on {chain.name} and has sent a transaction there.",
                    "chain": chain_key, "last_reviewed": today,
                },
                "labels": {a: {**m, "source": f"{m['source']} (listed as an Ethereum address; "
                                              f"the same account on {chain.name})"}
                           for a, m in sorted(listed.items())},
            }, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
