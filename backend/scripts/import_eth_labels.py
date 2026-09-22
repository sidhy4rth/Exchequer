"""Add exchange wallets from dawsbot/eth-labels to the Ethereum and BSC label files.

The other importers draw on brianleect/etherscan-labels, whose last scrape is
from October 2023. Exchanges that grew after that -- Bitget, MEXC, CoinEx,
and CoinDCX, an Indian exchange this project most needs -- are thin or
missing there. dawsbot/eth-labels is a newer published scrape of the same
explorer label pages (Etherscan, BscScan), so it closes that gap on the same
provenance footing. The commit is pinned below and recorded in the output.

Selection
---------
The dataset's category slugs are unreliable (its 'bilaxy' slug holds 5,000
Binance deposit addresses), so the exchange is read from the explorer's own
name tag instead: 'CoinDCX 12' -> CoinDCX. A tag is kept only if its head
names a centralised exchange, instant-swap service or fiat gateway in
CANONICAL -- the places that can answer a legal request. Deployers, deposit
funders, contracts and other exchange infrastructure are left out, and so are
per-customer deposit addresses ('Bitget Dep: 0x...'): there are tens of
thousands of them, too many to verify on a free API tier.

Verification
------------
Addresses already in a label file are left untouched. Every new candidate
must prove itself on chain by the same test its chain's original importer
applies: value-bearing transfers on Ethereum (import_exchange_labels), recent
activity or a non-trivial balance on BSC (seed_bsc_labels). Failures are
listed, never silently kept.

What this establishes: the explorer publicly tags the address with this
exchange's name, and the address is real and handles funds. What it does NOT
establish: that the tag is correct -- re-check on the explorer before
evidentiary use.

    cd backend && .venv/bin/python -m scripts.import_eth_labels
    cd backend && .venv/bin/python -m scripts.import_eth_labels --chain bsc --dry-run
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.request
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
from scripts.import_exchange_labels import has_value_history  # noqa: E402
from scripts.seed_bsc_labels import ACTIVITY_LOOKBACK, bsc_activity  # noqa: E402
from scripts.seed_tron_labels import CANONICAL as TRON_CANONICAL  # noqa: E402

DATASET_REPO = "dawsbot/eth-labels"
DATASET_COMMIT = "14247ba8cf4686b747938248bee34c66089fa9d9"
SOURCE_URL = (
    f"https://raw.githubusercontent.com/{DATASET_REPO}/{DATASET_COMMIT}"
    "/data/csv/accounts.csv"
)

CHAIN_IDS = {"ethereum": "1", "bsc": "56"}

# The Tron importer's exchange list, plus names that only appear on EVM
# explorers. Keys are the lower-cased, letters-only head of a name tag.
# Lenders, custodians, market makers and stablecoin issuers are deliberately
# absent: none of them is where a fraud victim's money gets cashed out.
CANONICAL: dict[str, str] = {
    **TRON_CANONICAL,
    "coinsquare": "Coinsquare", "coinw": "CoinW", "deribit": "Deribit", "ftx": "FTX",
    "altcointrader": "AltCoinTrader", "bitcoinsuisse": "Bitcoin Suisse",
    "gmocoin": "GMO Coin", "btcturk": "BtcTurk", "bitvenus": "BitVenus",
    "changenow": "ChangeNOW", "btse": "BTSE", "coinhako": "Coinhako", "liquid": "Liquid",
    "alphapo": "AlphaPo", "coinspaid": "CoinsPaid", "maskex": "MaskEX",
    "bitbank": "Bitbank", "bitpay": "BitPay", "coinmetro": "Coinmetro",
    "paribu": "Paribu", "revolut": "Revolut", "azbit": "Azbit", "bilaxy": "Bilaxy",
    "bitflyer": "bitFlyer", "coincheck": "Coincheck", "coinlist": "CoinList",
    "indodax": "Indodax", "shakepay": "Shakepay", "bullish": "Bullish",
    "coinjar": "CoinJar", "coinsbit": "Coinsbit", "fairdesk": "Fairdesk",
    "remitano": "Remitano", "kryptono": "Kryptono", "yunbi": "Yunbi", "abcc": "ABCC",
    "allbit": "Allbit", "bgogo": "Bgogo", "bigone": "BigONE", "bitmex": "BitMEX",
    "catex": "Catex", "cobinhood": "Cobinhood", "coinstore": "Coinstore",
    "difx": "DIFX", "fastex": "Fastex", "luno": "Luno", "firi": "Firi",
    "kanga": "Kanga", "tidex": "Tidex", "uphold": "Uphold", "topbtc": "TopBTC",
    "anycoindirect": "Anycoin Direct", "bity": "Bity", "coinify": "Coinify",
    "dextrade": "Dex-Trade", "digitalsurge": "Digital Surge", "etoro": "eToro",
    "coinbene": "Coinbene", "coinfield": "CoinField",
    "oobit": "Oobit", "delta": "Delta Exchange", "blofin": "BloFin",
}

# Dataset slugs whose rows are never exchange wallets, whatever the tag says.
SKIP_SLUG = re.compile(
    r"exploit|ofac|charity|mixer|tornado|sybil|airdrop|nonprofit|take-action|endaoment|scam|heist|compromised"
)
# Tags that name exchange infrastructure or a customer, not a cash-out wallet.
SKIP_TAG = re.compile(
    r"\bdep\b|deployer|funder|contract|token|charity|exploit|multisig|vesting|treasury|"
    r"staking|bridge|swap|launchpad|operator|registry|^\.|^bitget wallet",
    re.IGNORECASE,
)


def tag_head(tag: str) -> str:
    """'Binance: Hot Wallet 3' -> 'binance', 'Mexc.com 3' -> 'mexc'."""
    head = re.split(r"[:(]| hot| cold| wallet| exchange| deposit", tag, maxsplit=1, flags=re.I)[0]
    head = re.sub(r"[\s_-]*\d+$", "", head.strip())
    head = re.sub(r"\.(com|io|net|org)$", "", head.lower())
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


def candidates_by_chain() -> dict[str, dict[str, dict[str, str]]]:
    with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:
        rows = csv.DictReader(io.StringIO(response.read().decode()))
        out: dict[str, dict[str, dict[str, str]]] = {key: {} for key in CHAIN_IDS}
        wanted = {cid: key for key, cid in CHAIN_IDS.items()}
        for row in rows:
            chain_key = wanted.get(row["chainId"])
            if chain_key is None or SKIP_SLUG.search(row["label"]):
                continue
            tag = (row["nameTag"] or "").strip()
            if not tag or tag == "null" or SKIP_TAG.search(tag):
                continue
            exchange = CANONICAL.get(tag_head(tag))
            addr = normalize_address(row["address"])
            if exchange is None or not is_valid_address(addr):
                continue
            out[chain_key][addr] = {"exchange": exchange, "label": tag, "type": wallet_type(tag)}
    return out


def verify_ethereum(candidates: list[tuple[str, dict]]) -> tuple[dict, list[str], list[str]]:
    accepted, rejected, errors = {}, [], []
    with EtherscanClient(chain_id=1) as client:
        for addr, meta in candidates:
            try:
                ok, value, last_active = has_value_history(client, addr)
            except (EtherscanError, ValueError) as exc:
                print(f"{addr:<44} {meta['exchange']:<16} {'ERROR':>14}  {str(exc)[:28]}")
                errors.append(f"{addr} ({meta['exchange']}): {exc}")
                continue
            if not ok:
                print(f"{addr:<44} {meta['exchange']:<16} {value:>14,.3f}  REJECT")
                rejected.append(f"{addr} ({meta['exchange']}): no value-bearing transfers")
                continue
            print(f"{addr:<44} {meta['exchange']:<16} {value:>14,.3f}  ok  {last_active}")
            accepted[addr] = meta
    return accepted, rejected, errors


def verify_bsc(candidates: list[tuple[str, dict]]) -> tuple[dict, list[str], list[str]]:
    bsc = config.CHAINS["bsc"]
    usdt = bsc.find_token("USDT")
    accepted, rejected, errors = {}, [], []
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
        for addr, meta in candidates:
            try:
                moves, balance = bsc_activity(native, token, usdt.address, head, floor, addr)
            except (NoderealError, ValueError) as exc:
                print(f"{addr:<44} {meta['exchange']:<16} {'ERROR':>14}  {str(exc)[:28]}")
                errors.append(f"{addr} ({meta['exchange']}): {exc}")
                continue
            if moves == 0 and balance <= 0.01:
                print(f"{addr:<44} {meta['exchange']:<16} {balance:>14,.3f}  REJECT")
                rejected.append(f"{addr} ({meta['exchange']}): no recent BSC activity")
                continue
            print(f"{addr:<44} {meta['exchange']:<16} {balance:>14,.3f}  ok  {moves} recent")
            accepted[addr] = meta
    finally:
        native.close()
    return accepted, rejected, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chain", choices=[*CHAIN_IDS, "all"], default="all")
    parser.add_argument("--dry-run", action="store_true", help="verify but do not write")
    parser.add_argument("--limit", type=int, default=None, help="cap candidates per chain (for testing)")
    args = parser.parse_args()

    chains = list(CHAIN_IDS) if args.chain == "all" else [args.chain]
    if "bsc" in chains and not config.NODEREAL_API_KEY:
        print("NODEREAL_API_KEY is not set; BSC cannot be queried.")
        return 1

    print(f"Dataset: {DATASET_REPO} @ {DATASET_COMMIT[:10]}")
    found = candidates_by_chain()

    for chain_key in chains:
        path = config.CHAINS[chain_key].labels_path
        document = json.loads(path.read_text())
        existing: dict[str, dict] = document["labels"]
        have = {normalize_address(a) for a in existing}
        ordered = sorted((a, m) for a, m in found[chain_key].items() if a not in have)
        if args.limit:
            ordered = ordered[: args.limit]

        print(f"\n== {chain_key}: {len(existing)} existing labels (left untouched), "
              f"{len(ordered)} new candidates to verify\n")
        verify = verify_ethereum if chain_key == "ethereum" else verify_bsc
        accepted, rejected, errors = verify(ordered)

        print(f"\n{chain_key}: verified={len(ordered)}  accepted={len(accepted)}  "
              f"rejected={len(rejected)}  errors={len(errors)}")
        for item in rejected:
            print(f"  REJECTED: {item}")
        for item in errors:
            print(f"  ERROR: {item}")

        if args.dry_run or not accepted:
            continue

        merged = {**existing, **accepted}
        document["labels"] = dict(
            sorted(merged.items(), key=lambda kv: (kv[1]["exchange"], kv[1]["label"]))
        )
        meta = document.setdefault("_meta", {})
        meta["last_reviewed"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        meta["supplemented_from"] = (
            f"{len(accepted)} further labels imported from {DATASET_REPO} @ "
            f"{DATASET_COMMIT}, a newer published scrape of the same explorer "
            "label pages, and verified on chain the same way, by "
            "backend/scripts/import_eth_labels.py."
        )
        meta["regenerate_with"] = (
            f"{meta.get('regenerate_with', '').split(' && then ')[0]} && then "
            f"cd backend && .venv/bin/python -m scripts.import_eth_labels --chain {chain_key}"
        )
        path.write_text(json.dumps(document, indent=2) + "\n")
        print(f"\nWrote {len(merged)} labels to {path} (+{len(accepted)})")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
