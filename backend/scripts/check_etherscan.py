"""Live smoke test for the Etherscan integration (build step 2).

Run it before anything else is built, to prove the API key and client work:

    cd backend
    .venv/bin/python -m scripts.check_etherscan

Optionally pass an address to check:

    .venv/bin/python -m scripts.check_etherscan 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import EtherscanClient, EtherscanError  # noqa: E402

# vitalik.eth -- a real, permanently active mainnet address, ideal for proving
# the integration returns genuine data.
DEFAULT_ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"


def main() -> int:
    address = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS

    print(f"Endpoint : {config.ETHERSCAN_BASE_URL}  (chainid={config.ETHERSCAN_CHAIN_ID})")
    print(f"API key  : {'set' if config.ETHERSCAN_API_KEY else 'NOT SET -- this will fail'}")
    print(f"Address  : {address}\n")

    try:
        with EtherscanClient() as client:
            txs = client.get_transactions(address, limit=10)
            outgoing = client.get_outgoing_transactions(address, limit=10)
    except EtherscanError as exc:
        print(f"FAILED: {exc}")
        return 1
    except ValueError as exc:
        print(f"FAILED: {exc}")
        return 1

    if not txs:
        print("Connected successfully, but this address has no transactions.")
        return 0

    print(f"Pulled {len(txs)} transactions ({len(outgoing)} outgoing with value).\n")
    print(f"{'timestamp':<20} {'from':<12} {'to':<12} {'ETH':>14}  hash")
    print("-" * 92)
    for tx in txs[:10]:
        when = datetime.fromtimestamp(tx.timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        to = tx.to_address or "(contract create)"
        print(
            f"{when:<20} {tx.from_address[:10]:<12} {to[:10]:<12} "
            f"{tx.value_native:>14.6f}  {tx.hash[:18]}..."
        )

    print("\nOK: Etherscan integration confirmed against real chain data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
