"""Re-read every transfer a report cites from a provider the trace did not use.

A report's arithmetic can be re-done from the report, but its inputs came from one
data provider at one moment. This asks a different one: for each transaction in
Appendix B, did it succeed, and did the named sender pay the named recipient that
amount of that asset?

    Trace read from   Re-read here from
    Etherscan         public Ethereum nodes (cloudflare-eth.com, eth.drpc.org)
    TronGrid          TronScan

Three outcomes, because the difference matters to anyone relying on this:

    confirmed   The second provider says the same thing.
    mismatch    It says something different, or does not have the transaction.
    unchecked   This run cannot tell: the provider failed, the chain is not covered,
                or the transfer was moved by a contract call, which a plain read of
                the transaction does not show.

Unchecked is never reported as confirmed. Exit code 0 means every transfer was
confirmed, 1 that at least one is a mismatch, 2 that none is but some went unchecked.
The checks live in app/second_provider.py, which POST /trace/{id}/recheck runs
over the transfers a case's route to the exchange cites.

What this establishes: two independent providers agree on these transactions. It
does not establish who controls any address. Follow-on traces after a swap are not
in Appendix B, so they are not covered.

    cd backend && python -m scripts.verify_case --report report.json
    cd backend && python -m scripts.verify_case --demo 12
    cd backend && python -m scripts.verify_case --demo 12 --record responses.json
    cd backend && python -m scripts.verify_case --report report.json --recorded responses.json

--recorded reads saved responses and makes no network call; the tests use it. Their
fixtures, in tests/fixtures/verify_case/, are regenerated with:

    python -m scripts.verify_case --demo 12 --record tests/fixtures/verify_case/demo_12_tron.json
    python -m scripts.verify_case --demo 1 --record tests/fixtures/verify_case/demo_1_ethereum.json
    python -m scripts.verify_case --demo 3 --follow-on --record tests/fixtures/verify_case/demo_3_follow_on_usdt.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.report import build_report  # noqa: E402
# The checks themselves live in the app, which POST /trace/{id}/recheck runs too.
from app.second_provider import (CONFIRMED, ETHEREUM_NODES, MISMATCH, SECONDS_BETWEEN_READS,  # noqa: E402,F401
                                 UNCHECKED, Asset, Check, check_transfers, read_live)


def _chain_key(report: dict[str, Any]) -> str | None:
    name = (report.get("case") or {}).get("chain")
    return next((key for key, chain in config.CHAINS.items() if name in (chain.name, key)), None)


def verify(report: dict[str, Any], read: Callable[[str, str, Asset], dict[str, Any]]) -> list[Check]:
    """One Check per transfer in the report's Appendix B. `read` gets (chain key, hash, token)."""
    case = report.get("case") or {}
    transfers = (report.get("appendix") or {}).get("transactions") or []
    return check_transfers(_chain_key(report), case.get("asset"), transfers, read, case.get("chain"))


def appendix_note(report: dict[str, Any]) -> str | None:
    """What a capped Appendix B leaves unchecked (pipeline._appendix), or None."""
    appendix = report.get("appendix") or {}
    if not appendix.get("transactions_omitted"):
        return None
    return (f"The report lists {len(appendix.get('transactions') or [])} of the trace's "
            f"{appendix.get('transactions_total')} transfers; the other {appendix['transactions_omitted']} "
            "are not in Appendix B, so they were not checked.")


def exit_code(checks: list[Check]) -> int:
    if any(c.outcome == MISMATCH for c in checks):
        return 1
    return 2 if any(c.outcome == UNCHECKED for c in checks) or not checks else 0


def _demo_report(number: int, follow_on: bool = False) -> dict[str, Any]:
    from app.models import Case

    rows = json.loads((Path(config.DATA_DIR) / "recorded_demos.json").read_text(encoding="utf-8"))
    result = next(row for row in rows if row["demo"] == number)["result"]
    if follow_on:
        follow = result["follow_ons"][0]
        return {"case": {"chain": follow["result"]["chain_name"], "asset": follow["asset"]},
                "appendix": {"transactions": follow["result"]["transfers"]}}
    return build_report(Case(id=f"demo-{number}", address=result["address"], created_at=result["created_at"],
                             result_json=json.dumps(result)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--report", type=Path, help="a report saved from /trace/{id}/report (JSON)")
    source.add_argument("--demo", type=int, help="a recorded demo's number")
    parser.add_argument("--follow-on", action="store_true", help="with --demo: its first follow-on trace")
    parser.add_argument("--recorded", type=Path, help="read saved responses; no network")
    parser.add_argument("--record", type=Path, help="save the responses read here, for --recorded")
    args = parser.parse_args()

    report = (_demo_report(args.demo, args.follow_on) if args.demo
              else json.loads(args.report.read_text(encoding="utf-8")))
    saved = json.loads(args.recorded.read_text(encoding="utf-8")) if args.recorded else {}
    recorded: dict[str, Any] = {}

    with httpx.Client(timeout=30, headers={"User-Agent": "Exchequer verify_case"}) as http:
        def read(chain_key: str, digest: str, token: Asset) -> dict[str, Any]:
            if args.recorded:
                if digest not in saved:
                    # --record saves only the reads that worked: a missing one failed.
                    raise ValueError("this transfer is not in the recording")
                return saved[digest]
            answer = read_live(http, chain_key, digest, token)
            recorded[digest] = answer
            time.sleep(SECONDS_BETWEEN_READS)
            return answer

        checks = verify(report, read)

    for check in checks:
        print(f"{check.outcome:<10} {check.hash}" + (f"  {check.detail}" if check.detail else ""))
    tally = {o: sum(c.outcome == o for c in checks) for o in (CONFIRMED, MISMATCH, UNCHECKED)}
    print(f"\n{len(checks)} transfers: {tally[CONFIRMED]} confirmed, {tally[MISMATCH]} mismatch, {tally[UNCHECKED]} unchecked")
    if appendix_note(report):
        print(appendix_note(report))
    if report.get("follow_ons"):
        print("Follow-on traces after a swap are not in Appendix B, so they were not checked.")
    if args.record:
        args.record.write_text(json.dumps(recorded, indent=1) + "\n", encoding="utf-8")
        print(f"Saved {len(recorded)} responses to {args.record}")
    return exit_code(checks)


if __name__ == "__main__":
    raise SystemExit(main())
