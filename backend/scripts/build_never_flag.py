"""Build data/never_flag_tokens.json: token contracts no screening list may name.

The input is a plain list of token contract addresses, one per line, as kept by
the label hunt (never_flag_tokens.txt: the CoinGecko and Uniswap token lists).
Each line must be a valid EVM or Tron address; anything else stops the build.
The output is sorted and deduplicated, so the same input always gives the same
file. A reviewed exception already in the file's "allow" map is kept.

    cd backend && .venv/bin/python -m scripts.build_never_flag --from never_flag_tokens.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import is_evm_address, is_tron_address, normalize_address  # noqa: E402
from app.never_flag import NEVER_FLAG_FILE  # noqa: E402


def build(lines: list[str], allow: dict[str, str], source: str) -> dict:
    tokens = set()
    for n, line in enumerate(lines, 1):
        text = line.strip()
        if not text:
            continue
        if not (is_evm_address(text) or is_tron_address(text)):
            raise ValueError(f"line {n} is not an address: {text[:60]!r}")
        tokens.add(normalize_address(text))
    evm = sum(1 for t in tokens if t.startswith("0x"))
    return {
        "_meta": {
            "description": ("Token contract addresses that no sanctions, freeze, scam or threat label may name: "
                            "a token contract is on the path of every holder, not a party. Read by "
                            "app/never_flag.py with the router and exchange label files."),
            "provenance": f"The CoinGecko and Uniswap token lists, as collected for the 5 Nov 2026 label review ({source}).",
            "generated": datetime.now(timezone.utc).date().isoformat(),
            "counts": {"tokens": len(tokens), "evm": evm, "tron": len(tokens) - evm, "allow": len(allow)},
            "regenerate_with": "cd backend && .venv/bin/python -m scripts.build_never_flag --from <list>",
            "schema": "tokens: sorted addresses (EVM lowercase); allow: {address: reviewed reason it may be labelled}",
        },
        "tokens": sorted(tokens),
        "allow": dict(sorted(allow.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="source", type=Path, required=True, help="one address per line")
    args = parser.parse_args()
    out = config.DATA_DIR / NEVER_FLAG_FILE
    allow = {}
    if out.exists():
        allow = json.loads(out.read_text()).get("allow") or {}
    document = build(args.source.read_text().splitlines(), allow, args.source.name)
    out.write_text(json.dumps(document, indent=0) + "\n")
    print(f"Wrote {document['_meta']['counts']} to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
