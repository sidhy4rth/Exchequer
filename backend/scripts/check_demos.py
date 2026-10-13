"""Re-run the DEMO.md traces against the live site and report any that drifted.

The demos run on live blockchain data, and live data moves: a busy wallet on a
path gains transfers, a trace reads its newest ones, and an attribution that
held yesterday can change. DEMO.md trace 3 did exactly that between a morning
and an evening. A judge who picks a demo should never be the first to find out.

Each demo is traced with `save: false`, so the check never adds cases to the
history or makes a demo look like a repeat complaint. It compares, per demo:

  exchange             must be the same (including "none")
  follow-on exchange   the same, for the swap demo
  confidence           within +/- TOLERANCE of what DEMO.md quotes

and exits 1 if anything drifted, which fails the scheduled GitHub Action and
e-mails the repository owner.

A demo marked `"volatile": true` in the expectations file is one whose whole
point is that it moves (DEMO.md trace 3). A new exchange or score there is
printed as a note, not a failure; it fails only if it stops reaching an
exchange at all or cannot be traced -- and, with --state, only when that
happens on two runs in a row. A single day without an exchange is the demo
doing what it demonstrates (a newer transfer pushed the cash-out out of the
window the trace reads); it is printed as a warning and remembered. Otherwise it would e-mail every time the
chain did the thing the demo exists to show. Standard library only, so the Action installs
nothing and needs no API keys: the live site does the tracing.

    python backend/scripts/check_demos.py                  # check against expectations
    python backend/scripts/check_demos.py --record         # re-record after updating DEMO.md
    python backend/scripts/check_demos.py --base http://localhost:8000
    python backend/scripts/check_demos.py --state demo_state.json   # the Action
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

LIVE = "https://exchequer-production.up.railway.app"
EXPECTATIONS = Path(__file__).resolve().parent.parent / "data" / "demo_expectations.json"
TOLERANCE = 0.05


def trace(base: str, demo: dict) -> dict:
    body = {k: demo[k] for k in ("address", "chain", "asset", "max_depth", "direction")}
    request = urllib.request.Request(
        f"{base}/trace", data=json.dumps({**body, "save": False}).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=400) as response:
        return json.loads(response.read())


def trace_with_retry(base: str, demo: dict, wait: float = 15.0) -> dict:
    """One retry for a request lost in transit.

    The live site has answered a trace that never reached this script (a
    one-off stall between the host's edge and the runner); failing the job and
    e-mailing over that says nothing about the demo. A second failure does.
    """
    try:
        return trace(base, demo)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"  demo {demo['demo']:>2}  retrying after: {exc}")
        time.sleep(wait)
        return trace(base, demo)


def observed(result: dict) -> dict:
    followed = result.get("followed_attribution") or {}
    return {
        "exchange": result.get("exchange"),
        "followed_exchange": followed.get("exchange"),
        "confidence": result.get("confidence"),
    }


def drift(expected: dict, seen: dict, volatile: bool = False) -> list[str]:
    """What stops this demo matching DEMO.md; empty when it still does.

    For a volatile demo only losing the attribution altogether counts.
    """
    if volatile:
        if expected.get("exchange") and not seen.get("exchange"):
            return [f"exchange {expected['exchange']!r} -> None (a moving demo must still reach an exchange)"]
        return []
    problems = []
    for key in ("exchange", "followed_exchange"):
        if expected.get(key) != seen.get(key):
            problems.append(f"{key} {expected.get(key)!r} -> {seen.get(key)!r}")
    a, b = expected.get("confidence"), seen.get("confidence")
    if (a is None) != (b is None) or (a is not None and abs(a - b) > TOLERANCE):
        problems.append(f"confidence {a} -> {b}")
    return problems


def load_state(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {}


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=LIVE)
    parser.add_argument("--record", action="store_true", help="overwrite expectations with what is seen now")
    parser.add_argument("--state", type=Path, help="remember volatile misses between runs in this file")
    args = parser.parse_args()

    demos = json.loads(EXPECTATIONS.read_text())
    state = load_state(args.state)
    missed_before = set(state.get("volatile_misses", []))
    missed_now: set[str] = set()
    failures = 0
    for demo in demos:
        started = time.monotonic()
        try:
            seen = observed(trace_with_retry(args.base, demo))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"✗ demo {demo['demo']:>2}  could not trace, twice: {exc}")
            failures += 1
            continue
        took = time.monotonic() - started
        if args.record:
            demo["expect"] = seen
            print(f"• demo {demo['demo']:>2}  recorded {seen}  ({took:.0f}s)")
            continue
        volatile = bool(demo.get("volatile"))
        problems = drift(demo["expect"], seen, volatile)
        if volatile and problems and args.state is not None:
            key = str(demo["demo"])
            missed_now.add(key)
            if key not in missed_before:
                print(f"! demo {demo['demo']:>2}  {'; '.join(problems)} -- first miss, a warning; "
                      f"fails if the next run misses too  ({took:.0f}s)")
                print(f"::warning::Demo {demo['demo']} reached no exchange today (first miss)")
                continue
        moved = volatile and not problems and drift(demo["expect"], seen)
        mark = "✗" if problems else ("~" if moved else "✓")
        detail = "; ".join(problems) if problems else f"{seen['exchange'] or 'no exchange'} at {seen['confidence']}"
        if moved:
            detail += f"  (moved: {'; '.join(moved)} -- expected for this demo; refresh DEMO.md when convenient)"
        print(f"{mark} demo {demo['demo']:>2}  {detail}  ({took:.0f}s)")
        failures += bool(problems)

    if args.record:
        EXPECTATIONS.write_text(json.dumps(demos, indent=1, ensure_ascii=False) + "\n")
        print(f"\nWrote {EXPECTATIONS.name}. Check it against DEMO.md before committing.")
        return 0
    if args.state is not None:
        save_state(args.state, {"volatile_misses": sorted(missed_now)})
    print(f"\n{len(demos) - failures} of {len(demos)} demos as documented.")
    if failures:
        print("Update DEMO.md for what changed, then re-record with --record.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
