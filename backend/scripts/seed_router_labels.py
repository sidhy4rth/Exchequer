"""Build data/router_labels*.json: DEX routers and aggregators, verified on chain.

A transfer into a swap router is not a payment. The sender gets the money
back in a different asset in the same transaction, so a trace that follows one
asset sees the trail end at the router. Knowing which addresses are routers
lets the trace say "the funds were swapped here" instead of "the funds went
nowhere known" -- and, since the OKX DEX router was once found carrying an
exchange's name in the attribution file, it keeps swaps from ever being
reported as cash-outs.

Source: the same pinned brianleect/etherscan-labels dataset the exchange
importer uses, categories that hold the explorers' own router labels. Only
entries whose Etherscan name ends in "Router" (or is 0x's Exchange Proxy) are
taken: executors, governors, allowance targets and price aggregators carry the
protocol's name but are not the contract a swap is sent to.

Verification is the mirror image of the exchange importer's: a router MUST
have contract bytecode. An externally-owned account labelled as a router would
be a data error, and following its "swaps" would invent transactions.

    cd backend && .venv/bin/python -m scripts.seed_router_labels

A check that fails (an expired key, a rate limit) is unknown, not "no
bytecode": that chain's file is left as it is and the run exits 1. The files
also hold routers added by hand (the OKX DEX routers), so a run replaces only
the routers its source names and keeps the rest.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import EtherscanClient, EtherscanError, is_evm_address, normalize_address  # noqa: E402
from app.nodereal_client import NoderealClient, NoderealError  # noqa: E402
from scripts._label_files import ShrinkRefused, merge_owned  # noqa: E402

DATASET_REPO = "brianleect/etherscan-labels"
DATASET_COMMIT = "923aba72c7e2d0682f7ae6194b6140bd90668dc9"
BASE = f"https://raw.githubusercontent.com/{DATASET_REPO}/{DATASET_COMMIT}/data"

# chain key -> (explorer folder, categories). PancakeSwap's category is empty
# in this dataset commit and SunSwap has no Etherscan-style label source, so
# neither is here; the README says so.
SOURCES: dict[str, tuple[str, list[str]]] = {
    "ethereum": ("etherscan", ["dex", "1inch", "okx", "router"]),
    "bsc": ("bscscan", ["dex"]),
}

ROUTER_NAME = re.compile(r"(router(\s*v?\d+)?$|^0x: exchange proxy$)", re.IGNORECASE)


def protocol_of(name: str) -> str:
    """'Uniswap V3: Router 2' -> 'Uniswap'; '1inch v5: Aggregation Router' -> '1inch'."""
    head = name.split(":")[0].strip()
    head = re.sub(r"\s+v\d.*$", "", head, flags=re.IGNORECASE)
    head = re.sub(r"\s+V\d.*$", "", head)
    return head.strip()


def fetch_category(folder: str, category: str) -> dict[str, str]:
    url = f"{BASE}/{folder}/accounts/{category}.json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = json.load(response)
    except Exception as exc:  # noqa: BLE001 -- a missing category is reported, not fatal
        print(f"  ! {category}: {exc}")
        return {}
    out = {}
    for address, meta in raw.items():
        name = meta.get("name", "") if isinstance(meta, dict) else str(meta)
        if is_evm_address(address) and ROUTER_NAME.search(name):
            out[normalize_address(address)] = name
    return out


def has_code_ethereum(client: EtherscanClient, address: str) -> bool | None:
    try:
        code = client._request({"module": "proxy", "action": "eth_getCode",
                                "address": address, "tag": "latest"})
    except (EtherscanError, ValueError) as exc:
        print(f"  ! {address}: {str(exc)[:60]}")
        return None
    return isinstance(code, str) and len(code) > 2


def has_code_bsc(client: NoderealClient, address: str) -> bool | None:
    try:
        code = client._rpc("eth_getCode", [address, "latest"])
    except NoderealError as exc:
        print(f"  ! {address}: {str(exc)[:60]}")
        return None
    return isinstance(code, str) and len(code) > 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-shrink", action="store_true",
                        help="let a run remove more than a handful of the routers its source names")
    args = parser.parse_args()

    status = 0
    for chain_key, (folder, categories) in SOURCES.items():
        chain = config.CHAINS[chain_key]
        print(f"\n{chain.name}")
        candidates: dict[str, str] = {}
        for category in categories:
            found = fetch_category(folder, category)
            print(f"  {category}: {len(found)} router-named entries")
            candidates.update(found)

        if chain_key == "ethereum":
            if not config.ETHERSCAN_API_KEY:
                print("  ETHERSCAN_API_KEY is not set; cannot verify")
                continue
            client = EtherscanClient(chain_id=1)
            check = lambda a, c=client: has_code_ethereum(c, a)  # noqa: E731
        else:
            if not config.NODEREAL_API_KEY:
                print("  NODEREAL_API_KEY is not set; cannot verify")
                continue
            client = NoderealClient(chain_slug="bsc-mainnet")
            check = lambda a, c=client: has_code_bsc(c, a)  # noqa: E731

        labels: dict[str, dict[str, str]] = {}
        rejected: list[str] = []
        unverified: list[str] = []
        with client:
            for address, name in sorted(candidates.items()):
                verdict = check(address)
                if verdict is True:
                    labels[address] = {"exchange": protocol_of(name), "label": name, "type": "router"}
                elif verdict is False:
                    rejected.append(f"{address}  {name}  (no bytecode)")
                else:
                    unverified.append(f"{address}  {name}")
        for line in rejected:
            print("  -", line)
        print(f"  accepted {len(labels)} routers across "
              f"{len({m['exchange'] for m in labels.values()})} protocols")
        if unverified:
            print(f"  {len(unverified)} could not be checked; {chain.router_labels_path} left as it is")
            status = 1
            continue
        held = {}
        if chain.router_labels_path and chain.router_labels_path.exists():
            held = json.loads(chain.router_labels_path.read_text()).get("labels", {})
        try:
            labels, merge = merge_owned(held, labels, owned=lambda a, _e, mine=candidates: a in mine,
                                        allow_shrink=args.allow_shrink)
        except ShrinkRefused as exc:
            print(f"  refused, nothing written: {exc}")
            status = 1
            continue
        print(f"  merged: {dict(merge)}")
        if not labels:
            print("  nothing accepted; not writing an empty router file")
            status = 1
            continue

        document = {
            "_meta": {
                "description": (
                    "DEX routers and aggregators. A transfer into one of these is a swap, "
                    "not a payment or a cash-out: the sender received a different asset "
                    "back in the same transaction."
                ),
                "chain": chain_key,
                "provenance": (
                    f"Imported from {DATASET_REPO} @ {DATASET_COMMIT}, a published scrape "
                    f"of the explorer's own label pages, categories {categories}; only "
                    "entries whose explorer name ends in 'Router' (or 0x's Exchange Proxy) "
                    "were taken, and each was verified to carry contract bytecode."
                ),
                "generated": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                "regenerate_with": "cd backend && .venv/bin/python -m scripts.seed_router_labels",
                "rejected": rejected,
                "count": len(labels),
            },
            "labels": dict(sorted(labels.items())),
        }
        if args.dry_run or not chain.router_labels_path:
            continue
        chain.router_labels_path.write_text(json.dumps(document, indent=2) + "\n")
        print(f"  wrote {chain.router_labels_path}")
    return status


if __name__ == "__main__":
    sys.exit(main())
