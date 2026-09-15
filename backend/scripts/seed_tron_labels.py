"""Build data/exchange_labels_tron.json from TronScan's own address tags.

Tron is where this tool most needs good labels: TRM Labs put 58% of 2024
illicit crypto volume on Tron and UNODC calls USDT on Tron the "preferred
choice" of the cyber-fraud industry (RESEARCH.md), so a Tron trace that cannot
name the exchange at the end of it answers nothing.

Unlike Ethereum and BSC, the labels here are not taken from a third-party
scrape. TronScan publishes an address's official tag through its own public
API, so each label is read from the explorer that assigns it. That is the
strongest provenance available for free anywhere in this project.

Method
------
1. Candidates are the largest holders of USDT-TRC20 and the largest TRX
   accounts, paged from TronScan. Exchanges dominate both lists because they
   custody customer balances. Each row carries TronScan's `addressTag`.
2. Only tags that name a known centralised exchange are kept. An issuer's
   treasury, a bridge, a DeFi protocol or a token contract must never be
   attributed as a cash-out point; and a tag this script does not recognise is
   listed for a human to review rather than guessed at.
3. Every candidate must then prove itself on chain, by the same discipline
   the Ethereum importer applies:
     - no contract bytecode (TronGrid wallet/getcontract) -- an exchange
       wallet is an ordinary account, and a contract carrying an exchange's
       name is something else (a token, a bridge);
     - inbound value > 0 (a USDT-TRC20 or TRX transfer received) -- a wallet
       that has never received anything is not handling customer funds.

What this establishes: TronScan publicly identifies this address as belonging
to the named exchange, as of the recorded date, and the address is a live,
funded account. What it does NOT establish: who controls the funds. Only the
exchange can link a deposit address to a customer, via lawful request.

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
TRONGRID = "https://api.trongrid.io"
TRON = config.CHAINS["tron"]
USDT = TRON.find_token("USDT")
PAGE = 50  # TronScan's page size for both listings

# Tags that name something other than a place funds are cashed out at.
NOT_AN_EXCHANGE = re.compile(
    r"(treasury|token|contract|bridge|foundation|team|burn|blackhole|justlend|sunswap|dao|"
    r"multisig|deployer|staking|validator|sr\b|super representative)",
    re.IGNORECASE,
)

# Tag prefixes (lower-cased, punctuation stripped) that name a centralised
# exchange, folded to the company name. A tag whose head is not here is NOT
# kept: it is printed for review. Adding an exchange means adding a line here
# and re-running -- never typing an address.
CANONICAL: dict[str, str] = {
    "binance": "Binance", "okx": "OKX", "okex": "OKX", "bybit": "Bybit",
    "huobi": "Huobi / HTX", "htx": "Huobi / HTX", "kucoin": "KuCoin",
    "gate": "Gate.io", "gateio": "Gate.io", "mexc": "MEXC", "mxc": "MEXC",
    "bitget": "Bitget", "poloniex": "Poloniex", "kraken": "Kraken",
    "bitfinex": "Bitfinex", "coinbase": "Coinbase", "crypto": "Crypto.com",
    "cryptocom": "Crypto.com", "bitmart": "BitMart", "coindcx": "CoinDCX",
    "wazirx": "WazirX", "zebpay": "ZebPay", "giottus": "Giottus",
    "whitebit": "WhiteBIT", "bingx": "BingX", "lbank": "LBank", "hitbtc": "HitBTC",
    "upbit": "Upbit", "bithumb": "Bithumb", "coinex": "CoinEx", "xt": "XT.com",
    "phemex": "Phemex", "deepcoin": "Deepcoin", "bitstamp": "Bitstamp",
    "gemini": "Gemini", "bitkub": "Bitkub", "coinone": "Coinone", "korbit": "Korbit",
    "bitrue": "Bitrue", "hotbit": "Hotbit", "ascendex": "AscendEX", "bittrex": "Bittrex",
    "digifinex": "DigiFinex", "pionex": "Pionex", "toobit": "Toobit", "weex": "WEEX",
    "bitvavo": "Bitvavo", "bitpanda": "Bitpanda", "nexo": "Nexo", "backpack": "Backpack",
    "coinspot": "CoinSpot", "fixedfloat": "FixedFloat", "ueex": "UEEx",
}


def tag_head(tag: str) -> str:
    head = re.split(r"[-:_(]| hot| cold| wallet| exchange| deposit|\d", tag, maxsplit=1, flags=re.I)[0]
    head = re.sub(r"\.(com|io|net)$", "", head.strip().lower())
    return re.sub(r"[^a-z]", "", head)


def wallet_type(tag: str) -> str:
    lowered = tag.lower()
    if "cold" in lowered:
        return "cold_wallet"
    if "deposit" in lowered:
        return "deposit_wallet"
    if "hot" in lowered:
        return "hot_wallet"
    return "exchange_wallet"


def tagged_rows(client: httpx.Client, url: str, params: dict, key: str, count: int) -> list[tuple[str, str]]:
    """(address, tag) for every tagged row across `count` candidates, paged."""
    out = []
    for start in range(0, count, PAGE):
        try:
            body = client.get(url, params={**params, "start": start, "limit": PAGE}).json()
        except Exception as exc:  # noqa: BLE001 -- a bad page is reported, not fatal
            print(f"  ! page {start}: {str(exc)[:60]}")
            continue
        rows = body.get(key) or []
        for row in rows:
            address = row.get("holder_address") or row.get("address") or ""
            tag = (row.get("addressTag") or "").strip()
            if is_tron_address(address) and tag:
                out.append((address, tag))
        if not rows:
            break
        time.sleep(0.3)
    return out


def has_bytecode(client: httpx.Client, address: str, headers: dict) -> bool | None:
    try:
        body = client.post(f"{TRONGRID}/wallet/getcontract", headers=headers,
                           json={"value": address, "visible": True}).json()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! getcontract {address}: {str(exc)[:50]}")
        return None
    return bool(body.get("bytecode"))


def has_inbound(client: httpx.Client, address: str, headers: dict) -> bool | None:
    """One received USDT-TRC20 or TRX transfer is enough."""
    for path, params in (
        (f"/v1/accounts/{address}/transactions/trc20",
         {"only_to": "true", "limit": 1, "contract_address": USDT.address}),
        (f"/v1/accounts/{address}/transactions", {"only_to": "true", "limit": 1}),
    ):
        try:
            body = client.get(f"{TRONGRID}{path}", params=params, headers=headers).json()
        except Exception as exc:  # noqa: BLE001
            print(f"  ! inbound {address}: {str(exc)[:50]}")
            return None
        if body.get("data"):
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--holders", type=int, default=600, help="largest USDT-TRC20 holders to inspect")
    parser.add_argument("--accounts", type=int, default=300, help="largest TRX accounts to inspect")
    args = parser.parse_args()

    scan_headers = {"User-Agent": "Exchequer/1.0", "Accept": "application/json"}
    grid_headers = {"Accept": "application/json"}
    if config.TRONGRID_API_KEY:
        grid_headers["TRON-PRO-API-KEY"] = config.TRONGRID_API_KEY

    with httpx.Client(timeout=40, headers=scan_headers) as scan:
        print(f"Reading tags of the {args.holders} largest USDT-TRC20 holders ...")
        rows = tagged_rows(scan, f"{TRONSCAN}/api/token_trc20/holders",
                           {"contract_address": USDT.address}, "trc20_tokens", args.holders)
        print(f"Reading tags of the {args.accounts} largest TRX accounts ...")
        rows += tagged_rows(scan, f"{TRONSCAN}/api/account/list",
                            {"sort": "-balance"}, "data", args.accounts)

    candidates: dict[str, str] = {}
    for address, tag in rows:
        candidates.setdefault(address, tag)
    print(f"{len(candidates)} tagged candidates\n")

    kept: dict[str, dict[str, str]] = {}
    not_exchange: list[str] = []
    unknown: list[str] = []
    rejected: list[str] = []

    with httpx.Client(timeout=40) as grid:
        for address, tag in sorted(candidates.items(), key=lambda kv: kv[1]):
            if NOT_AN_EXCHANGE.search(tag):
                not_exchange.append(f"{address}  {tag}")
                continue
            company = CANONICAL.get(tag_head(tag))
            if company is None:
                unknown.append(f"{address}  {tag}")
                continue
            code = has_bytecode(grid, address, grid_headers)
            time.sleep(0.2)
            if code is not False:
                rejected.append(f"{address}  {tag}  ({'contract' if code else 'unverified'})")
                continue
            inbound = has_inbound(grid, address, grid_headers)
            time.sleep(0.2)
            if inbound is not True:
                rejected.append(f"{address}  {tag}  ({'no inbound value' if inbound is False else 'unverified'})")
                continue
            kept[address] = {"exchange": company, "label": tag, "type": wallet_type(tag)}
            print(f"  KEEP  {address}  {tag}")

    by_exchange: dict[str, int] = {}
    for meta in kept.values():
        by_exchange[meta["exchange"]] = by_exchange.get(meta["exchange"], 0) + 1

    print("\n" + "=" * 84)
    print(f"candidates={len(candidates)}  kept={len(kept)}  not_exchange={len(not_exchange)}  "
          f"unrecognised={len(unknown)}  rejected_on_chain={len(rejected)}")
    for name, count in sorted(by_exchange.items()):
        print(f"  {name:<14} {count}")
    if unknown:
        print("\nTags not recognised as an exchange (review; add to CANONICAL if one is):")
        for line in unknown:
            print("  ?", line)
    for line in rejected:
        print("  -", line)

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
                "of these is what lets Exchequer say 'the funds were cashed out "
                "here'."
            ),
            "provenance": (
                "Each label is TronScan's own published address tag, read from its "
                "public API (the addressTag on /api/token_trc20/holders and "
                "/api/account/list) by backend/scripts/seed_tron_labels.py. "
                "Candidates are the largest USDT-TRC20 holders and TRX accounts, "
                "since exchanges dominate both lists."
            ),
            "verification_note": (
                "TronScan publicly identifies these addresses as belonging to the "
                "named exchanges as of the review date. That is the explorer's own "
                "attribution, not an inference by this tool. Each address was then "
                "checked on chain: no contract bytecode (TronGrid wallet/getcontract) "
                "and at least one received USDT-TRC20 or TRX transfer. It does NOT "
                "establish who controls the funds -- only the exchange can link a "
                "deposit address to a customer, via lawful request. Tags naming "
                "issuers, bridges, protocols or contracts were excluded, and tags "
                "not recognised as an exchange were listed for review, not kept."
            ),
            "chain": "tron",
            "last_reviewed": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
            "regenerate_with": "cd backend && .venv/bin/python -m scripts.seed_tron_labels",
            "schema": "labels maps a Base58 address to {exchange, label, type}",
            "counts": {"labels": len(kept), "exchanges": len(by_exchange), "by_exchange": by_exchange},
            "excluded_not_exchange": not_exchange,
            "unrecognised_tags": unknown,
            "rejected_on_chain": rejected,
        },
        "labels": dict(sorted(kept.items(), key=lambda kv: (kv[1]["exchange"], kv[1]["label"]))),
    }
    TRON.labels_path.write_text(json.dumps(document, indent=2) + "\n")
    print(f"\nWrote {len(kept)} labels to {TRON.labels_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
