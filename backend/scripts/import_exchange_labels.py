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
    cd backend && .venv/bin/python -m scripts.import_exchange_labels --retype-deposits   # offline

A wallet is a customer deposit address only when its label says so explicitly
(app/exchange_matcher.is_deposit_label): "Deposit Funder", "Eth2 Depositor" and
"<A>: <B> Deposit" name the exchange's own wallets or another firm's account,
and a deposit type is what makes a letter ask for an account holder's KYC.
`--retype-deposits` re-types the held files' entries under that rule.
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
from app.etherscan_client import (  # noqa: E402
    EtherscanClient,
    EtherscanError,
    is_valid_address,
    normalize_address,
)
from app.exchange_matcher import DEPOSIT_WALLET, is_deposit_label  # noqa: E402
from app.tron_tags import clean_tag  # noqa: E402
from scripts._label_files import chain_regenerate  # noqa: E402
from scripts._tag_words import NOT_CASH_OUT, names_infrastructure  # noqa: E402,F401 -- NOT_CASH_OUT re-exported

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


# Labels in the exchange datasets that name something the exchange runs but
# that is not where customers' funds are cashed out (a contract, a deployer,
# the wallets that fund deposit addresses' gas, another firm's treasury):
# scripts/_tag_words, the one filter both importers read.


def is_cash_out_label(label: str) -> bool:
    """Whether a dataset label may name a cash-out wallet. Read after
    clean_tag (NFKC, invisible and format characters removed) and casefolded:
    'OKX: Rout\u200ber 2' and a full-width 'ＲＯＵＴＥＲ' passed the bare letters."""
    return not names_infrastructure(label)


def exchange_for(label: str, stem_exchange: str) -> str | None:
    """The exchange a dataset label names, from the label itself.

    The dataset file an address sits in is not proof of who runs it:
    'Tether: Treasury' sits in the Bitfinex set. So the exchange comes from
    the tag's name, before any ':' -- its leading whole words, longest
    first, matched to a known exchange ('Binance Dep: 0x..' and 'Binance-Hot
    3' -> Binance, wherever they sit; 'Gatekeeper' is never Gate.io). A tag
    whose name is no known exchange is no exchange wallet (None), unless it
    is the file's own exchange spelled out."""
    from scripts.import_eth_labels import CANONICAL

    name = clean_tag(label).split(":", 1)[0]
    words = [w for w in re.split(r"[\s._()/-]+", name.casefold()) if w and not w.isdigit()]
    own = re.sub(r"[^a-z]", "", stem_exchange.casefold())
    for n in range(len(words), 0, -1):
        letters = re.sub(r"[^a-z]", "", "".join(words[:n]))
        if letters in CANONICAL:
            return CANONICAL[letters]
        if letters and letters == own:
            return stem_exchange
    return None


def listed_elsewhere(chain_key: str = "ethereum") -> set[str]:
    """The chain's addresses another of the repository's files already
    names: its router, risk, threat, frozen and sanctions files, and every
    EVM chain's router file (a contract is the same contract on every EVM
    chain). None of them may come in as an exchange cash-out wallet."""
    chain = config.CHAINS[chain_key]
    paths = [chain.router_labels_path, chain.risk_labels_path, chain.threat_labels_path,
             chain.frozen_labels_path, chain.intl_sanctions_path]
    paths += [c.router_labels_path for c in config.CHAINS.values() if c.address_family == "evm"]
    found: set[str] = set()
    for path in {p for p in paths if p is not None and p.is_file()}:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"{path} is unreadable, so candidates cannot be checked against it: {exc}") from exc
        labels = document.get("labels", document) if isinstance(document, dict) else {}
        if isinstance(labels, dict):
            found |= {normalize_address(a) for a in labels if isinstance(a, str) and a.startswith("0x")}
    return found


def gather(fetched: list[tuple[str, str, dict]], have: set[str],
           refused: set[str] | None = None) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    """(new candidates, how many were skipped and why) from the fetched
    dataset files, as (file stem, its exchange, {address: label}).

    A label is cleaned first, then must name a cash-out wallet, and the
    exchange is the one the label names. An address held already, or named
    by the router, risk, threat, frozen or sanctions files, is skipped."""
    refused = listed_elsewhere() if refused is None else refused
    counts = {"malformed": 0, "not_cash_out": 0, "no_exchange": 0, "refused_listed": 0}
    candidates: dict[str, dict[str, str]] = {}
    for _stem, stem_exchange, raw in fetched:
        for address, raw_label in (raw.items() if isinstance(raw, dict) else ()):
            addr = normalize_address(address) if isinstance(address, str) else ""
            if not is_valid_address(addr):
                counts["malformed"] += 1
                continue
            if addr in have or addr in candidates:
                continue
            if addr in refused:
                counts["refused_listed"] += 1
                continue
            label = clean_tag(raw_label)
            if not is_cash_out_label(label):
                counts["not_cash_out"] += 1
                continue
            exchange = exchange_for(label, stem_exchange) if label else stem_exchange
            if exchange is None:
                counts["no_exchange"] += 1
                continue
            candidates[addr] = {"exchange": exchange, "label": label or exchange, "type": classify(label)}
    return candidates, counts


def classify(label: str) -> str:
    """Wallet role, stated only when the label itself says so.

    Etherscan's labels distinguish cold storage explicitly, and a per-customer
    deposit address only in the explicit forms is_deposit_label reads. Everything
    else is recorded as a generic exchange wallet rather than guessed at --
    claiming a wallet is "hot" on no evidence would put an unsupported detail in
    a report.
    """
    lowered = label.lower()
    if "cold" in lowered:
        return "cold_wallet"
    if is_deposit_label(label):
        return DEPOSIT_WALLET
    return "exchange_wallet"


def retype_deposits(dry_run: bool) -> int:
    """Re-type every held entry typed a deposit whose label does not say so. Offline."""
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    for chain in config.CHAINS.values():
        path = chain.labels_path
        if not path.exists():
            continue
        text = path.read_text()
        document = json.loads(text)
        retyped = {}
        for address, meta in document["labels"].items():
            if isinstance(meta, dict) and meta.get("type") == DEPOSIT_WALLET and not is_deposit_label(meta.get("label")):
                meta["type"] = classify(meta.get("label") or "")
                retyped[address] = meta.get("label")
        print(f"{chain.key}: {len(retyped)} re-typed from deposit_wallet")
        if not retyped or dry_run:
            continue
        document.setdefault("_meta", {})["deposits_retyped"] = {
            "date": today, "count": len(retyped), "labels": dict(sorted(retyped.items())),
            "rule": ("deposit_wallet only when the label says so ('X Dep: 0x..', 'X: Deposit Address'); "
                     "an exchange's Deposit Funder or Eth2 Depositor, or another firm's account at it, "
                     "is not one customer's deposit address"),
        }
        indent = 1 if text.startswith('{\n "') else 2
        path.write_text(json.dumps(document, indent=indent) + "\n")
    return 0


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
    parser.add_argument("--retype-deposits", action="store_true",
                        help="re-type held entries typed deposit_wallet whose label does not say so, offline")
    args = parser.parse_args()
    if args.retype_deposits:
        return retype_deposits(args.dry_run)

    path = config.CHAINS["ethereum"].labels_path
    document = json.loads(path.read_text())
    existing: dict[str, dict] = document["labels"]
    have = {normalize_address(a) for a in existing}

    # -- gather candidates ------------------------------------------------
    fetched: list[tuple[str, str, dict]] = []
    for stem, exchange in SOURCES.items():
        try:
            fetched.append((stem, exchange, fetch(stem)))
        except Exception as exc:  # a missing file must not abort the import
            print(f"  ! could not fetch {stem}: {exc}")
    candidates, skipped = gather(fetched, have)
    skipped_malformed = skipped["malformed"]

    ordered = sorted(candidates.items())
    if args.limit:
        ordered = ordered[: args.limit]

    print(f"Dataset   : {DATASET_REPO} @ {DATASET_COMMIT[:10]}")
    print(f"Existing  : {len(existing)} labels (left untouched)")
    print(f"Candidates: {len(ordered)} new addresses to verify")
    if skipped_malformed:
        print(f"Skipped   : {skipped_malformed} malformed addresses")
    print(f"Refused   : {skipped['not_cash_out']} not cash-out wallets, {skipped['no_exchange']} naming no "
          f"exchange, {skipped['refused_listed']} already in a router/risk/threat/frozen/sanctions file")
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
    meta["regenerate_with"] = chain_regenerate(meta.get("regenerate_with"),
                                               "cd backend && .venv/bin/python -m scripts.import_exchange_labels")

    path.write_text(json.dumps(document, indent=2) + "\n")
    print(f"\nWrote {len(merged)} labels to {path} (+{len(accepted)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
