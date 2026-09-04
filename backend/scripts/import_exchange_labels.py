"""Expand data/exchange_labels.json from a published label set, with on-chain proof.

Attribution is the one thing this tool must not guess. A mistyped address does
not fail loudly -- it sits in the database and one day names the wrong company
in a report that goes to police. So labels are never hand-entered here. They
are imported from a published dataset and every new address must then prove
itself against live chain data before it is accepted.

Source
------
brianleect/etherscan-labels, a public scrape of Etherscan's own address label
pages (etherscan.io/accounts/label/*) -- the same origin as the labels already
in the file. The dataset commit is pinned below and recorded in the output, so
any entry can be traced back to exactly what was imported and when.

Verification
------------
Every *new* candidate is checked for a real history of value-bearing transfers.
The metric is inbound value, not nonce: an exchange deposit wallet receives
constantly and may almost never send, so a low nonce proves nothing, whereas
zero lifetime value means the address is not handling customer funds.
Candidates that fail are dropped and listed, not silently included.

Addresses already in the file are left untouched -- they were verified when
they were added, and re-verifying them would burn API budget to learn nothing.

    cd backend && .venv/bin/python -m scripts.import_exchange_labels
    cd backend && .venv/bin/python -m scripts.import_exchange_labels --dry-run
"""
from __future__ import annotations

import argparse
import json
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

# Pinned so a re-run imports the same data rather than whatever the dataset
# happens to say today.
DATASET_REPO = "brianleect/etherscan-labels"
DATASET_COMMIT = "923aba72c7e2d0682f7ae6194b6140bd90668dc9"
DATASET_URL = (
    f"https://raw.githubusercontent.com/{DATASET_REPO}/{DATASET_COMMIT}"
    "/data/etherscan/accounts"
)

# Which label files to import, and the canonical exchange name for each. Only
# centralised exchanges are listed: those are the ones that can answer a legal
# request, which is the entire point of attributing a cash-out.
SOURCES: dict[str, str] = {
    "binance": "Binance",
    "binance-deposit": "Binance",
    "bitfinex": "Bitfinex",
    "bithumb": "Bithumb",
    "bitstamp": "Bitstamp",
    "bittrex": "Bittrex",
    "coinbase": "Coinbase",
    "crypto-com": "Crypto.com",
    "gate-io": "Gate.io",
    "gemini": "Gemini",
    "hitbtc": "HitBTC",
    "huobi": "Huobi / HTX",
    "kraken": "Kraken",
    "kucoin": "KuCoin",
    "okx": "OKX",
    "poloniex": "Poloniex",
    "remitano": "Remitano",
    "upbit": "Upbit",
}

SAMPLE_SIZE = 200


def fetch(stem: str) -> dict[str, str]:
    """One label file from the pinned dataset commit."""
    url = f"{DATASET_URL}/{stem}.json"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode())


def classify(label: str) -> str:
    """Wallet role, stated only when the label itself says so.

    Etherscan's labels distinguish cold storage explicitly. Everything else is
    recorded as a generic exchange wallet rather than guessed at -- claiming a
    wallet is "hot" on no evidence would put an unsupported detail in a report.
    """
    lowered = label.lower()
    if "cold" in lowered:
        return "cold_wallet"
    if "deposit" in lowered:
        return "deposit_wallet"
    return "exchange_wallet"


def has_value_history(client: EtherscanClient, address: str) -> tuple[bool, float, str | None]:
    """(handles value, total seen, last-active date) for one address.

    Checks the most recent window first, then the earliest: a wallet the
    exchange has rotated away from shows only address-poisoning spam recently,
    while its real history sits at the other end of its life.
    """
    txs = client.get_transactions(address, limit=SAMPLE_SIZE, sort="desc")
    value = sum(t.value_native for t in txs if t.value_native > 0)

    if txs and value <= 0:
        try:
            early = client.get_transactions(address, limit=SAMPLE_SIZE, sort="asc")
            early_value = sum(t.value_native for t in early if t.value_native > 0)
            if early_value > 0:
                txs, value = early, early_value
        except (EtherscanError, ValueError):
            pass

    if not txs or value <= 0:
        return False, value, None
    last = datetime.fromtimestamp(max(t.timestamp for t in txs), tz=timezone.utc)
    return True, value, last.strftime("%Y-%m-%d")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import and verify exchange labels")
    parser.add_argument("--dry-run", action="store_true", help="verify but do not write")
    parser.add_argument("--limit", type=int, default=None, help="cap candidates (for testing)")
    args = parser.parse_args()

    path = config.CHAINS["ethereum"].labels_path
    document = json.loads(path.read_text())
    existing: dict[str, dict] = document["labels"]
    have = {normalize_address(a) for a in existing}

    # -- gather candidates ------------------------------------------------
    candidates: dict[str, dict[str, str]] = {}
    skipped_malformed = 0
    for stem, exchange in SOURCES.items():
        try:
            raw = fetch(stem)
        except Exception as exc:  # a missing file must not abort the import
            print(f"  ! could not fetch {stem}: {exc}")
            continue
        for address, label in raw.items():
            addr = normalize_address(address)
            if not is_valid_address(addr):
                skipped_malformed += 1
                continue
            if addr in have or addr in candidates:
                continue
            candidates[addr] = {
                "exchange": exchange,
                "label": (label or exchange).strip(),
                "type": classify(label or ""),
            }

    ordered = sorted(candidates.items())
    if args.limit:
        ordered = ordered[: args.limit]

    print(f"Dataset   : {DATASET_REPO} @ {DATASET_COMMIT[:10]}")
    print(f"Existing  : {len(existing)} labels (left untouched)")
    print(f"Candidates: {len(ordered)} new addresses to verify")
    if skipped_malformed:
        print(f"Skipped   : {skipped_malformed} malformed addresses")
    print(f"\n{'address':<44} {'exchange':<14} {'value ETH':>14} {'last active':>12}  status")
    print("-" * 96)

    accepted: dict[str, dict[str, str]] = {}
    rejected: list[str] = []
    errors: list[str] = []

    with EtherscanClient(chain_id=1) as client:
        for addr, meta in ordered:
            try:
                ok, value, last_active = has_value_history(client, addr)
            except (EtherscanError, ValueError) as exc:
                print(f"{addr:<44} {meta['exchange']:<14} {'ERROR':>14} {'-':>12}  {str(exc)[:28]}")
                errors.append(f"{addr} ({meta['exchange']}): {exc}")
                continue

            if not ok:
                print(f"{addr:<44} {meta['exchange']:<14} {value:>14,.3f} {'-':>12}  REJECT")
                rejected.append(f"{addr} ({meta['exchange']}): no value-bearing transfers")
                continue

            print(f"{addr:<44} {meta['exchange']:<14} {value:>14,.3f} {last_active:>12}  ok")
            accepted[addr] = meta

    print("\n" + "=" * 96)
    print(f"verified={len(ordered)}  accepted={len(accepted)}  "
          f"rejected={len(rejected)}  errors={len(errors)}")
    for item in rejected[:20]:
        print(f"  REJECTED: {item}")
    if len(rejected) > 20:
        print(f"  ... and {len(rejected) - 20} more rejected")
    for item in errors[:10]:
        print(f"  ERROR: {item}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0
    if not accepted:
        print("\nNothing new passed verification; file unchanged.")
        return 0

    merged = {**existing, **accepted}
    document["labels"] = dict(sorted(merged.items(), key=lambda kv: (kv[1]["exchange"], kv[1]["label"])))
    meta = document.setdefault("_meta", {})
    meta["last_reviewed"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    meta["provenance"] = (
        "Addresses originate from Etherscan's own public address labels "
        "(etherscan.io/accounts/label/*). The initial set was transcribed by "
        f"hand; the remainder was imported from {DATASET_REPO} @ "
        f"{DATASET_COMMIT}, a published scrape of those same pages, via "
        "backend/scripts/import_exchange_labels.py."
    )
    meta["verification_note"] = (
        "Every address was checked against live mainnet data before being "
        "added: each has a real history of value-bearing transfers, consistent "
        "with exchange operation. That confirms the address is real and "
        "economically active -- it does NOT independently re-confirm which "
        "company operates it, and no free API exposes Etherscan's label data. "
        "Re-verify on etherscan.io before any evidentiary use. Candidates whose "
        "entire history was zero-value address-poisoning spam were rejected."
    )
    meta["regenerate_with"] = "cd backend && .venv/bin/python -m scripts.import_exchange_labels"

    path.write_text(json.dumps(document, indent=2) + "\n")
    print(f"\nWrote {len(merged)} labels to {path} (+{len(accepted)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
