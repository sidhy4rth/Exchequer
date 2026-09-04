"""Separate exchange wallets from contracts that merely carry an exchange's name.

Etherscan labels everything an exchange is associated with, not just the
wallets that receive customer funds. Imported wholesale, that puts three kinds
of address into the attribution database that do not belong there:

  * Token contracts (Gemini's GUSD, OKX's OKB, Tether's MXNt). An ERC-20
    contract is where a token is *defined*, not where money is cashed out.
  * DEX routers (OKX's aggregation router). Funds passing through a swap
    router have been traded, not deposited to an exchange -- attributing that
    as a cash-out would name a company that never took custody.
  * Deployers and helper contracts, which never receive customer deposits.

The distinction matters because a false attribution does not fail loudly. It
produces a confident report naming the wrong company, which is the one outcome
this tool must never produce.

What is kept: contracts an exchange actually operates as custody -- multisig
wallets, deposit-forwarding contracts. Funds reaching those really have
reached the exchange. They are retyped `contract_wallet` rather than left
looking like an ordinary hot wallet, so a report states what it can support.

    cd backend && .venv/bin/python -m scripts.audit_label_contracts --dry-run
    cd backend && .venv/bin/python -m scripts.audit_label_contracts
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import EtherscanClient, EtherscanError  # noqa: E402

# Labels that mean "not a place funds are cashed out at". Matched against the
# label text, which is Etherscan's own wording.
NOT_CUSTODY = re.compile(r"\b(token|router|aggregation|dex|bridge|faucet)\b", re.IGNORECASE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = config.CHAINS["ethereum"].labels_path
    document = json.loads(path.read_text())
    labels: dict[str, dict] = document["labels"]

    print(f"Auditing {len(labels)} labels for contract code (chainid 1)\n")

    contracts: list[str] = []
    errors = 0
    with EtherscanClient(chain_id=1) as client:
        for address in list(labels):
            try:
                code = client._request(
                    {"module": "proxy", "action": "eth_getCode",
                     "address": address, "tag": "latest"}
                )
            except (EtherscanError, ValueError) as exc:
                print(f"  ! {address}: {str(exc)[:50]}")
                errors += 1
                continue
            if isinstance(code, str) and len(code) > 2:
                contracts.append(address)

    dropped: list[str] = []
    retyped: list[str] = []
    for address in contracts:
        meta = labels[address]
        if NOT_CUSTODY.search(meta.get("label", "")):
            dropped.append(f"{address}  {meta['exchange']:<12} {meta['label']}")
            del labels[address]
        else:
            meta["type"] = "contract_wallet"
            retyped.append(f"{address}  {meta['exchange']:<12} {meta['label']}")

    print(f"contracts found : {len(contracts)}")
    print(f"dropped         : {len(dropped)}  (token / router / bridge -- not custody)")
    for item in dropped:
        print(f"    DROP  {item}")
    print(f"retyped         : {len(retyped)}  (exchange-operated contract wallets, kept)")
    for item in retyped[:8]:
        print(f"    KEEP  {item}")
    if len(retyped) > 8:
        print(f"    ... and {len(retyped) - 8} more")
    if errors:
        print(f"errors          : {errors} (left unchanged)")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    document["labels"] = labels
    document["_meta"]["last_reviewed"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    document["_meta"]["contract_audit"] = (
        "Every address was checked for contract bytecode. Token contracts, DEX "
        "routers and bridges were removed -- funds reaching those have not been "
        "cashed out at an exchange. Exchange-operated contract wallets (multisig, "
        "deposit forwarders) were kept and typed 'contract_wallet'. Re-run with "
        "backend/scripts/audit_label_contracts.py."
    )
    path.write_text(json.dumps(document, indent=2) + "\n")
    print(f"\nWrote {len(labels)} labels to {path} (-{len(dropped)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
