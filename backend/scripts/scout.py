"""Try candidate addresses for a live demo without storing a case.

    .venv/bin/python -m scripts.scout ADDRESS [ADDRESS ...] [--depth 3] [--direction outgoing] [--chain ethereum] [--asset ETH]
    .venv/bin/python -m scripts.scout --file candidates.txt

Runs each address through the same code as POST /trace and prints one line:
how long it took, how big the graph is, what it reached and what fired. Nothing
is written to the case store, so a scouting run never shows up in Related
cases. The responses are cached, so an address chosen from this list traces
in under a second on the day if the same instance is used.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import TraceRequest, run_trace  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("addresses", nargs="*")
    parser.add_argument("--file", help="one address per line; '#' starts a comment")
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--direction", default="outgoing", choices=["outgoing", "incoming"])
    parser.add_argument("--chain", default="ethereum")
    parser.add_argument("--asset", default=None)
    args = parser.parse_args()

    addresses = list(args.addresses)
    if args.file:
        for line in Path(args.file).read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                addresses.append(line)
    if not addresses:
        parser.error("give at least one address, or --file")

    logging.disable(logging.WARNING)
    print(f"{'address':14} {'dir':3} d  {'secs':>5}  {'nodes':>5} {'edges':>5}  {'exchange':12} {'conf':>5}  notes")
    for address in addresses:
        started = time.time()
        try:
            r = run_trace(TraceRequest(address=address, chain=args.chain, asset=args.asset,
                                       direction=args.direction, max_depth=args.depth))
        except Exception as exc:  # noqa: BLE001 -- keep scouting
            print(f"{address[:14]} {args.direction[:3]} {args.depth}  {time.time() - started:5.1f}  FAILED {str(exc)[:90]}")
            continue
        notes = []
        if r.get("attribution_inferred"):
            notes.append("inferred deposit")
        notes += r.get("flags", [])
        notes += [f"RISK:{f}" for f in r.get("risk_flags", [])]
        if r.get("swaps"):
            notes.append(f"{len(r['swaps'])} swap(s)")
        if r.get("truncated"):
            notes.append("truncated")
        conf = r.get("confidence")
        print(
            f"{address[:14]} {args.direction[:3]} {args.depth}  {time.time() - started:5.1f}  "
            f"{len(r['graph']['nodes']):5} {len(r['graph']['edges']):5}  "
            f"{str(r.get('exchange') or '—'):12} {('%.2f' % conf) if conf is not None else '  n/a':>5}  {', '.join(notes)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
