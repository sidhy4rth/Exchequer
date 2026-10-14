"""Record every DEMO.md trace into data/recorded_demos.json.

The app serves these at /demo/<n> beside the live trace, so a demo whose live
answer has moved can still be shown as it was written about. Each trace runs
with `save: false` against the live site (or --base), exactly as the daily demo
check does, so recording adds nothing to the case history.

Record from a build whose label files are the ones deployed: a recording made
with local, unreleased labels would show answers the live site cannot give.

    python backend/scripts/record_demos.py
    python backend/scripts/record_demos.py --only 3 6   # re-record some
    python backend/scripts/record_demos.py --base http://localhost:8000
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

from check_demos import EXPECTATIONS, LIVE, trace_with_retry

RECORDED = Path(__file__).resolve().parent.parent / "data" / "recorded_demos.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=LIVE)
    parser.add_argument("--only", type=int, nargs="+", help="demo numbers to re-record")
    args = parser.parse_args()

    existing = {row["demo"]: row for row in json.loads(RECORDED.read_text())} if RECORDED.is_file() else {}
    for demo in json.loads(EXPECTATIONS.read_text()):
        if args.only and demo["demo"] not in args.only:
            continue
        started = time.monotonic()
        result = trace_with_retry(args.base, demo)
        recorded_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        existing[demo["demo"]] = {"demo": demo["demo"], "recorded_at": recorded_at, "result": result}
        print(f"• demo {demo['demo']:>2}  {result.get('exchange') or 'no exchange'} at "
              f"{result.get('confidence')}  ({time.monotonic() - started:.0f}s)")

    rows = [existing[n] for n in sorted(existing)]
    RECORDED.write_text(json.dumps(rows, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"\nWrote {len(rows)} recordings to {RECORDED.name} ({RECORDED.stat().st_size // 1024} KB).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
