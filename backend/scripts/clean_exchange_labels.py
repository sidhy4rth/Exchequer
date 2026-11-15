"""Clean the exchange label files: no token contract, no infrastructure, and
another firm's account attributed to the exchange that holds it.

An exchange match ends a trace and names where the funds were cashed out, so
each of these was a false or misleading attribution on the live site (15 Nov
2026 label-coverage audit):

  * Token contracts. 'Binance: BUSD Stablecoin' on BNB Smart Chain is the BUSD
    token contract (symbol BUSD), and 'Kanga Exchange 2' on Ethereum is the
    Kanga Exchange Token contract (symbol KNG); both are in
    data/never_flag_tokens.json. Funds sent to a token contract have not been
    cashed out anywhere. Every label whose address is a token contract by
    app/never_flag.tokens() -- each chain's traced tokens and the CoinGecko and
    Uniswap token lists -- is removed, on every chain, every time this runs.
  * Infrastructure (INFRASTRUCTURE below): wallets an exchange or its group
    runs that are not where a customer's funds are credited -- the peg-token
    reserve, a token-swap wallet, mining-pool payout wallets, a charity.
    Removed: there is no exchange-label kind for them, and the importers
    already refuse these tags (scripts/_tag_words.py), so a re-import would
    not bring them back.
  * Another firm's account at an exchange (FIRM_ACCOUNTS): 'Wintermute:
    Binance Deposit' is Wintermute's deposit address at Binance. Only Binance
    holds that account's records, so the label is attributed to Binance (the
    owner's rule, 15 Nov 2026); the label keeps the explorer's wording, which
    names the firm, and request_letters.py says the firm holds the account.
    Before this, eight of the nine were attributed to the firm. A firm's
    account is not one customer's deposit address (is_deposit_label), so the
    type stays exchange_wallet.

What each run changed is written into the file's _meta under REVIEW_KEY.

    cd backend && .venv/bin/python -m scripts.clean_exchange_labels --dry-run
    cd backend && .venv/bin/python -m scripts.clean_exchange_labels
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, never_flag  # noqa: E402
from app.exchange_matcher import INSTANT_EXCHANGERS_FILE  # noqa: E402

REVIEW_KEY = "review_2026_11_15"

# address -> why it is not a cash-out wallet. EVM addresses: removed on every chain that labels them.
INFRASTRUCTURE = {
    "0x47ac0fb4f2d84898e4d9e7b4dab3c24507a6d503":
        "Binance-Peg Tokens: the reserve behind Binance's peg tokens, not where a customer's funds are credited",
    "0xee62cbab44113b3d72cdc94980953c0b1a4f4d47":
        "Binance: AE Token Swap: a token-migration wallet, not where a customer's funds are credited",
    "0xc365c3315cf926351ccaf13fa7d19c8c4058c8e1":
        "Binance Pool: a mining pool's payout wallet, not where a customer's funds are credited",
    "0x9d6d492bd500da5b33cf95a5d610a73360fcaaa0":
        "Huobi Mining Pool: a mining pool's payout wallet, not where a customer's funds are credited",
    "0x8b99f3660622e21f2910ecca7fbe51d654a1517d":
        "Binance Charity: a charity's donation wallet, not an exchange's",
}

# address -> (the exchange that holds the account, the firm whose account it is)
FIRM_ACCOUNTS = {
    "0xb3f923eabaf178fc1bd8e13902fc5c61d3ddef5b": ("Binance", "Wintermute"),
    "0x0da044b16bb53ab6d6691e25b1ec7ad380fa5fa7": ("Binance", "AltCoinTrader"),
    "0xfcb7edb966d320c7f3ae1f751a8c86f30fa5ad37": ("Binance", "Bitcoin Suisse"),
    "0x50a3f3b8855c2da88e56c7b0ef6e0e4a79f853f9": ("Binance", "Delta Exchange"),
    "0x2953452df5d7285b9a3a8a1e876a4bacb09a976e": ("Binance", "eToro"),
    "0xb0afffd6f6ad77f61927803ade6dbd47f1a1c356": ("Cobo", "BTSE"),
    "0x9fae72d291949ed6fa8b74881328fdc123c645d3": ("Celsius Network", "Deribit"),
    "0x2cf4e5b4fa8afa15f8dc7b5ada853e42776f3455": ("Celsius Network", "AltCoinTrader"),
    "0xb61a16bda6d61d9b8ad493bf05962c5b98d1712f": ("Coinbase", "Deribit"),
    "0x6ba7fe01eec4c6a4308c8e2b35970e0488ce9a86": ("Huobi / HTX", "ChangeNOW"),
}


def clean(document: dict[str, Any], chain_key: str) -> dict[str, dict[str, str]]:
    """Clean one chain's label document in place; returns {"removed": {...}, "attributed_to_custodian": {...}}."""
    labels = document["labels"]
    tokens = never_flag.tokens(chain_key)
    removed, moved = {}, {}
    for address in list(labels):
        if address.startswith("_"):
            continue
        entry = labels[address]
        raw = never_flag._raw(chain_key, address)
        if raw is not None and raw in tokens:
            removed[address] = f"{entry.get('label')}: a token contract (app/never_flag.tokens), not a wallet"
        elif address in INFRASTRUCTURE:
            removed[address] = INFRASTRUCTURE[address]
        elif address in FIRM_ACCOUNTS and isinstance(entry, dict):
            holder, firm = FIRM_ACCOUNTS[address]
            if entry.get("exchange") != holder:
                moved[address] = f"{entry.get('label')}: {firm}'s account at {holder}, was attributed to {entry.get('exchange')}"
                entry["exchange"] = holder
            continue
        else:
            continue
        del labels[address]
    return {"removed": removed, "attributed_to_custodian": moved}


def clean_instant_seed(document: dict[str, Any], labels_by_chain: dict[str, dict[str, Any]]) -> list[str]:
    """Drop seed rows whose address the label file no longer names under that service; returns them."""
    kept, dropped = [], []
    for row in document.get("rows", []):
        entry = labels_by_chain.get(row.get("chain"), {}).get(row.get("address"))
        if entry is not None and entry.get("exchange") != row.get("service"):
            dropped.append(f"{row['chain']} {row['address']}: no longer labelled {row['service']} "
                           f"(now {entry.get('exchange')})")
        elif entry is None and row.get("chain") in labels_by_chain:
            dropped.append(f"{row['chain']} {row['address']}: no longer in the label file")
        else:
            kept.append(row)
    document["rows"] = kept
    return dropped


def _indent(text: str) -> int:
    second = text.split("\n", 2)[1] if "\n" in text else ""
    return max(1, len(second) - len(second.lstrip(" ")))


def _write(path: Path, document: dict[str, Any], indent: int) -> None:
    path.write_text(json.dumps(document, indent=indent) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    labels_by_chain = {}
    for chain in config.CHAINS.values():
        path = chain.labels_path
        text = path.read_text(encoding="utf-8")
        document = json.loads(text)
        changes = clean(document, chain.key)
        labels_by_chain[chain.key] = document["labels"]
        for kind, rows in changes.items():
            for address, why in rows.items():
                print(f"{chain.key:9} {kind:24} {address}  {why}")
        if any(changes.values()) and not args.dry_run:
            review = document["_meta"].setdefault(REVIEW_KEY, {
                "date": "2026-11-15",
                "rule": "scripts/clean_exchange_labels.py: token contracts and infrastructure removed; "
                        "another firm's account attributed to the exchange that holds it",
            })
            for kind, rows in changes.items():
                if rows:
                    review.setdefault(kind, {}).update(rows)
            _write(path, document, _indent(text))

    seed_path = config.DATA_DIR / INSTANT_EXCHANGERS_FILE
    seed_text = seed_path.read_text(encoding="utf-8")
    seed = json.loads(seed_text)
    dropped = clean_instant_seed(seed, labels_by_chain)
    for line in dropped:
        print(f"instant   dropped                  {line}")
    if dropped and not args.dry_run:
        seed["_meta"].setdefault(REVIEW_KEY, []).extend(d for d in dropped if d not in seed["_meta"].get(REVIEW_KEY, []))
        _write(seed_path, seed, _indent(seed_text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
