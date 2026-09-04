"""Build data/exchange_labels_tron.json from TronScan's own address tags.

Tron is where this tool most needs good labels: USDT-TRC20 is the dominant
rail for moving scam proceeds out of India, so a Tron trace that cannot name
the exchange at the end of it answers nothing.

Unlike Ethereum and BSC, the labels here are not taken from a third-party
scrape. TronScan exposes an address's official tag through its own public API
(`/api/account?address=...` -> `addressTag`), so each label is read live from
the explorer that assigns it. That is the strongest provenance available for
free anywhere in this project.

Method
------
1. Take the largest holders of USDT-TRC20. Exchanges dominate that list
   because they custody customer balances.
2. Ask TronScan for each holder's official tag. Untagged addresses are
   discarded -- an unlabelled whale is not an attribution.
3. Discard tags that are not exchanges. "Tether Treasury" is the token issuer,
   not a cash-out point; attributing a trace to it would be as wrong as
   attributing one to a token contract.

What this establishes: TronScan publicly identifies this address as belonging
to the named exchange, as of the recorded date.
What it does NOT establish: who controls the funds. Only the exchange can link
a deposit address to a customer, via lawful request.

    cd backend && .venv/bin/python -m scripts.seed_tron_labels
    cd backend && .venv/bin/python -m scripts.seed_tron_labels --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import is_tron_address  # noqa: E402

TRONSCAN = "https://apilist.tronscanapi.com"
TRON = config.CHAINS["tron"]
USDT = TRON.find_token("USDT")

# Tags that name something other than a place funds are cashed out at. An
# issuer's treasury, a bridge or a token contract must never be attributed as
# an exchange -- the same rule applied to Ethereum's token contracts.
NOT_AN_EXCHANGE = re.compile(
    r"(treasury|token|contract|bridge|foundation|team|burn|blackhole|justlend|sunswap|dao)",
    re.IGNORECASE,
)

# Tags are free text ("Binance-Hot 7", "OKX Hot Wallet 8"). Fold them to the
# company so attribution groups correctly.
CANONICAL = {
    "binance": "Binance", "okx": "OKX", "okex": "OKX", "bybit": "Bybit",
    "huobi": "Huobi / HTX", "htx": "Huobi / HTX", "kucoin": "KuCoin",
    "gate": "Gate.io", "mexc": "MEXC", "bitget": "Bitget", "poloniex": "Poloniex",
    "kraken": "Kraken", "bitfinex": "Bitfinex", "coinbase": "Coinbase",
    "crypto": "Crypto.com", "bitmart": "BitMart", "coindcx": "CoinDCX",
    "wazirx": "WazirX", "whitebit": "WhiteBIT", "bingx": "BingX",
}


def exchange_name(tag: str) -> str:
    head = re.split(r"[-:_]| hot| cold| wallet|\d", tag, maxsplit=1, flags=re.I)[0]
    key = re.sub(r"\.(com|io|net)$", "", head.strip().lower())
    return CANONICAL.get(key, head.strip() or tag)


def wallet_type(tag: str) -> str:
    lowered = tag.lower()
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
    parser.add_argument("--holders", type=int, default=60, help="how many top holders to inspect")
    args = parser.parse_args()

    headers = {"User-Agent": "TraceChain/1.0", "Accept": "application/json"}
    kept: dict[str, dict[str, str]] = {}
    skipped_untagged = 0
    skipped_not_exchange: list[str] = []

    with httpx.Client(timeout=40, headers=headers) as client:
        response = client.get(
            f"{TRONSCAN}/api/token_trc20/holders",
            params={"contract_address": USDT.address, "limit": args.holders, "start": 0},
        )
        holders = response.json().get("trc20_tokens") or []
        print(f"Inspecting {len(holders)} largest USDT-TRC20 holders\n")
        print(f"{'address':<36} {'balance USDT':>18}  tag")
        print("-" * 84)

        for holder in holders:
            address = holder.get("holder_address") or holder.get("address") or ""
            if not is_tron_address(address):
                continue
            try:
                account = client.get(
                    f"{TRONSCAN}/api/account", params={"address": address}
                ).json()
            except Exception as exc:  # one bad lookup must not end the run
                print(f"{address:<36} {'-':>18}  ERROR {str(exc)[:24]}")
                continue

            tag = (account.get("addressTag") or account.get("accountName") or "").strip()
            balance = float(holder.get("balance") or 0) / 10**USDT.decimals

            if not tag:
                skipped_untagged += 1
            elif NOT_AN_EXCHANGE.search(tag):
                skipped_not_exchange.append(f"{address} ({tag})")
                print(f"{address:<36} {balance:>18,.0f}  skip — not an exchange: {tag}")
            else:
                kept[address] = {
                    "exchange": exchange_name(tag),
                    "label": tag,
                    "type": wallet_type(tag),
                }
                print(f"{address:<36} {balance:>18,.0f}  KEEP  {tag}")
            time.sleep(0.25)

    print("\n" + "=" * 84)
    print(f"inspected={len(holders)}  kept={len(kept)}  untagged={skipped_untagged}  "
          f"not_exchange={len(skipped_not_exchange)}")
    for item in skipped_not_exchange:
        print(f"  EXCLUDED: {item}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0
    if not kept:
        print("\nNothing verified; refusing to write an empty label file.")
        return 1

    document = {
        "_meta": {
            "description": (
                "Known centralised-exchange wallets on Tron. A match against one "
                "of these is what lets TraceChain say 'the funds were cashed out "
                "here'."
            ),
            "provenance": (
                "Each label is TronScan's own published address tag, read live "
                "from its public API (/api/account -> addressTag) by "
                "backend/scripts/seed_tron_labels.py. Candidates are the largest "
                "USDT-TRC20 holders, since exchanges dominate that list."
            ),
            "verification_note": (
                "TronScan publicly identifies these addresses as belonging to the "
                "named exchanges as of the review date. That is the explorer's "
                "own attribution, not an inference by this tool. It does NOT "
                "establish who controls the funds -- only the exchange can link a "
                "deposit address to a customer, via lawful request. Tags naming "
                "issuers, bridges or contracts were excluded: funds reaching "
                "those have not been cashed out."
            ),
            "chain": "tron",
            "last_reviewed": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
            "regenerate_with": "cd backend && .venv/bin/python -m scripts.seed_tron_labels",
            "schema": "labels maps a Base58 address to {exchange, label, type}",
        },
        "labels": dict(sorted(kept.items(), key=lambda kv: (kv[1]["exchange"], kv[1]["label"]))),
    }
    TRON.labels_path.write_text(json.dumps(document, indent=2) + "\n")
    print(f"\nWrote {len(kept)} labels to {TRON.labels_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
