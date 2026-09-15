"""Build data/exchange_labels_bsc.json from BscScan's labels, with on-chain proof.

BNB Smart Chain needs its own label file. Binance's hot wallet on Ethereum and
Binance's hot wallet on BSC are different addresses, and matching an address
seen on one chain against the other chain's labels would manufacture an
attribution no transaction supports.

Source
------
brianleect/etherscan-labels, pinned to a commit, specifically its scrape of
BscScan's own "exchange" label page. Same provenance model as the Ethereum
file: a published mirror of the explorer's own labels.

Verification
------------
Each candidate must show real economic activity on BSC before it is accepted.
An exchange hot wallet moves customer funds daily, so recent activity is a
strong signal and its absence is a reason to leave the address out. Both
native BNB and BEP-20 stablecoin transfers count, because a wallet may serve
only one of them. Current balance is used as a secondary signal so a wallet
that is quiet this month but plainly holds funds is not discarded.

What this establishes: the address is real and handles money on BSC.
What it does NOT establish: which company operates it. No free API exposes
BscScan's label data, so the operator name is inherited from the published
scrape and must be re-checked on bscscan.com before evidentiary use.

    cd backend && .venv/bin/python -m scripts.seed_bsc_labels
    cd backend && .venv/bin/python -m scripts.seed_bsc_labels --dry-run
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
from app.etherscan_client import is_valid_address, normalize_address  # noqa: E402
from app.nodereal_client import NoderealClient, NoderealError  # noqa: E402

DATASET_REPO = "brianleect/etherscan-labels"
DATASET_COMMIT = "923aba72c7e2d0682f7ae6194b6140bd90668dc9"
SOURCE_URL = (
    f"https://raw.githubusercontent.com/{DATASET_REPO}/{DATASET_COMMIT}"
    "/data/bscscan/accounts/exchange.json"
)

BSC = config.CHAINS["bsc"]
# How far back activity counts as evidence. ~35 days of BSC blocks: an exchange
# hot wallet that has moved nothing in that time is not a live cash-out point.
ACTIVITY_LOOKBACK = 1_000_000

# Names normalised to match the Ethereum file, so a case that crosses chains
# reads consistently.
CANONICAL = {
    "binance": "Binance", "coinbase": "Coinbase", "okx": "OKX", "okex": "OKX",
    "huobi": "Huobi / HTX", "htx": "Huobi / HTX", "kucoin": "KuCoin",
    "gate": "Gate.io", "crypto": "Crypto.com", "bitfinex": "Bitfinex",
    "kraken": "Kraken", "bybit": "Bybit", "mexc": "MEXC", "bitget": "Bitget",
    "poloniex": "Poloniex", "bithumb": "Bithumb", "upbit": "Upbit",
    "gemini": "Gemini", "bitmart": "BitMart", "azbit": "Azbit",
    "coindcx": "CoinDCX", "fixedfloat": "FixedFloat", "wazirx": "WazirX",
}


def exchange_name(label: str) -> str:
    """Company name from a BscScan label like 'Binance: Hot Wallet 3'.

    BscScan's labels are not uniform -- 'Binance: Hot Wallet 10',
    'Binance Hot Wallet 10', 'Mexc.com 3' and 'CoinDCX 2' all name the same
    kinds of thing in different shapes. Attribution groups by this name, so
    leaving 'Mexc.com 3' and 'mexc.com' as separate exchanges would split one
    company into two in every report.
    """
    head = label.split(":")[0].strip()
    # Drop a wallet-role suffix: "Binance Hot Wallet 10" -> "Binance"
    head = re.sub(r"\s+(hot|cold|deposit|wallet|exchange)\b.*$", "", head, flags=re.I)
    # Drop a trailing index: "CoinDCX 2" -> "CoinDCX"
    head = re.sub(r"[\s_-]*\d+$", "", head).strip()
    # Fold domain suffixes so "Mexc.com" and "MEXC" are one exchange.
    key = re.sub(r"\.(com|io|net|org|exchange)$", "", head.lower()).strip()
    return CANONICAL.get(key, head or "Unknown")


def wallet_type(label: str) -> str:
    lowered = label.lower()
    if "cold" in lowered:
        return "cold_wallet"
    if "deposit" in lowered:
        return "deposit_wallet"
    if "hot" in lowered:
        return "hot_wallet"
    return "exchange_wallet"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not config.NODEREAL_API_KEY:
        print("NODEREAL_API_KEY is not set; BSC cannot be queried.")
        return 1

    with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
        raw = json.loads(response.read().decode())

    candidates: dict[str, dict[str, str]] = {}
    for address, label in raw.items():
        addr = normalize_address(address)
        if not is_valid_address(addr):
            continue
        label = (label or "").strip()
        candidates[addr] = {
            "exchange": exchange_name(label),
            "label": label or exchange_name(label),
            "type": wallet_type(label),
        }

    print(f"Source    : {DATASET_REPO} @ {DATASET_COMMIT[:10]} (bscscan/exchange)")
    print(f"Candidates: {len(candidates)} addresses to verify on {BSC.name}\n")
    print(f"{'address':<44} {'exchange':<14} {'activity':>9} {'balance BNB':>13}  status")
    print("-" * 92)

    usdt = BSC.find_token("USDT")
    kept: dict[str, dict[str, str]] = {}
    dropped: list[str] = []
    errors: list[str] = []

    native = NoderealClient(chain_slug="bsc-mainnet", lookback_blocks=ACTIVITY_LOOKBACK)
    token = NoderealClient(
        chain_slug="bsc-mainnet",
        contract_addresses=[usdt.address],
        asset_symbol="USDT",
        lookback_blocks=ACTIVITY_LOOKBACK,
        client=native._client,
    )

    try:
        head = native.head_block()
        floor = max(0, head - ACTIVITY_LOOKBACK)
        for address, meta in sorted(candidates.items()):
            try:
                # Inbound is the better signal: a deposit wallet receives
                # constantly and may almost never send.
                moves = 0
                for client, category in ((native, ["external"]), (token, ["20"])):
                    params = {
                        "category": category,
                        "fromBlock": hex(floor),
                        "toBlock": hex(head),
                        "toAddress": address,
                        "maxCount": "0x5",
                        "order": "desc",
                    }
                    if category == ["20"]:
                        params["contractAddresses"] = [usdt.address]
                    result = client._rpc("nr_getAssetTransfers", [params]) or {}
                    moves += len(result.get("transfers") or [])
                    if moves:
                        break

                balance_raw = native._rpc("eth_getBalance", [address, "latest"])
                balance = int(balance_raw, 16) / 10**18 if isinstance(balance_raw, str) else 0.0
            except (NoderealError, ValueError) as exc:
                print(f"{address:<44} {meta['exchange']:<14} {'ERROR':>9} {'-':>13}  {str(exc)[:24]}")
                errors.append(f"{address}: {exc}")
                continue

            active = moves > 0 or balance > 0.01
            status = "keep" if active else "skip (no BSC activity)"
            print(f"{address:<44} {meta['exchange']:<14} {moves:>9} {balance:>13,.3f}  {status}")
            if active:
                kept[address] = meta
            else:
                dropped.append(f"{address} ({meta['exchange']})")
    finally:
        native.close()

    print("\n" + "=" * 92)
    print(f"candidates={len(candidates)}  kept={len(kept)}  inactive={len(dropped)}  errors={len(errors)}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0
    if not kept:
        print("\nNothing verified; refusing to write an empty label file.")
        return 1

    document = {
        "_meta": {
            "description": (
                "Known centralised-exchange wallets on BNB Smart Chain. A match "
                "against one of these is what lets Exchequer say 'the funds "
                "were cashed out here'."
            ),
            "provenance": (
                f"Imported from {DATASET_REPO} @ {DATASET_COMMIT}, a published "
                "scrape of BscScan's own exchange label pages, by "
                "backend/scripts/seed_bsc_labels.py."
            ),
            "verification_note": (
                "Every address below was confirmed against live BNB Smart Chain "
                "data to be economically active -- recent BNB or BEP-20 USDT "
                "transfers, or a non-trivial BNB balance. That proves the address "
                "is real and handles funds; it does NOT independently confirm "
                "which company operates it, since no free API exposes BscScan's "
                "label data. Re-verify on bscscan.com before evidentiary use."
            ),
            "chain": "bsc",
            "chain_id": BSC.chain_id,
            "last_reviewed": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
            "regenerate_with": "cd backend && .venv/bin/python -m scripts.seed_bsc_labels",
            "schema": "labels maps a lowercase address to {exchange, label, type}",
        },
        "labels": dict(sorted(kept.items(), key=lambda kv: (kv[1]["exchange"], kv[1]["label"]))),
    }
    BSC.labels_path.write_text(json.dumps(document, indent=2) + "\n")
    print(f"\nWrote {len(kept)} labels to {BSC.labels_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
