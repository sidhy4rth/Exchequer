"""Sanity-check every address in data/exchange_labels.json against the chain.

This does NOT prove who operates an address -- no free API exposes Etherscan's
label data. What it proves is that each entry is a real address with a genuine
history of value-bearing transfers, which catches the failure that actually
matters for an attribution tool: a typo'd or fabricated address sitting
silently in the database, ready to produce a false attribution.

The metric is deliberately *inbound value*, not nonce. An exchange deposit
wallet receives constantly and may almost never send, so a low nonce says
nothing. Zero lifetime value, by contrast, means the address is not handling
customer funds -- it is spam or a mistake.

    cd backend && .venv/bin/python -m scripts.verify_labels
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import EtherscanClient, EtherscanError, normalize_address  # noqa: E402

SAMPLE_SIZE = 200
# Flag anything dormant for more than roughly two years -- still a valid label,
# but worth knowing the exchange may have rotated away from it.
DORMANT_DAYS = 730


def main() -> int:
    data = json.loads(config.EXCHANGE_LABELS_PATH.read_text())
    labels = data["labels"]
    print(f"Verifying {len(labels)} labelled addresses against Ethereum mainnet")
    print(f"(sampling the {SAMPLE_SIZE} most recent transactions of each)\n")
    print(f"{'address':<44} {'exchange':<14} {'sampled':>8} {'value ETH':>14} {'last active':>12}  status")
    print("-" * 104)

    rejected: list[str] = []
    dormant: list[str] = []
    errors: list[str] = []
    now = datetime.now(tz=timezone.utc)

    with EtherscanClient() as client:
        for address, meta in labels.items():
            exchange = meta["exchange"] if isinstance(meta, dict) else meta
            addr = normalize_address(address)
            try:
                txs = client.get_transactions(addr, limit=SAMPLE_SIZE, sort="desc")
            except (EtherscanError, ValueError) as exc:
                print(f"{address:<44} {exchange:<14} {'ERROR':>8}  {str(exc)[:40]}")
                errors.append(address)
                continue

            value = sum(t.value_native for t in txs if t.value_native > 0)

            # A wallet that is merely dormant will show zero value in its most
            # recent window because address-poisoning spam is all that still
            # arrives. Check the earliest window too before rejecting it -- a
            # false reject silently removes a real exchange from attribution.
            if txs and value <= 0:
                try:
                    early = client.get_transactions(addr, limit=SAMPLE_SIZE, sort="asc")
                    value = sum(t.value_native for t in early if t.value_native > 0)
                    if value > 0:
                        txs = early
                except (EtherscanError, ValueError):
                    pass

            if not txs or value <= 0:
                # No value has ever moved here -> not an exchange wallet.
                status = "REJECT"
                rejected.append(f"{address} ({exchange}): no value-bearing transfers")
                last_active = "-"
            else:
                last_ts = max(t.timestamp for t in txs)
                last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc)
                last_active = last_dt.strftime("%Y-%m-%d")
                if (now - last_dt).days > DORMANT_DAYS:
                    status = "dormant"
                    dormant.append(f"{address} ({exchange}): last active {last_active}")
                else:
                    status = "ok"

            print(f"{address:<44} {exchange:<14} {len(txs):>8} {value:>14,.3f} {last_active:>12}  {status}")

    print("\n" + "=" * 104)
    ok = len(labels) - len(rejected) - len(dormant) - len(errors)
    print(f"checked={len(labels)}  ok={ok}  dormant={len(dormant)}  rejected={len(rejected)}  errors={len(errors)}")
    for item in dormant:
        print(f"  DORMANT (still valid, exchange may have rotated): {item}")
    for item in rejected:
        print(f"  REJECTED (remove from labels): {item}")

    # Only a rejected address is a real failure -- dormant is informational.
    return 1 if (rejected or errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
