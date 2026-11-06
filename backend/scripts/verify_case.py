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
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.report import build_report  # noqa: E402

ETHEREUM_NODES = ("https://cloudflare-eth.com", "https://eth.drpc.org")
TRONSCAN = "https://apilist.tronscanapi.com/api/transaction-info"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"  # Transfer(address,address,uint256)
SECONDS_BETWEEN_READS = 0.3
# Amounts in a report are rounded when stored; one part in a million of a coin is
# well inside that and far below anything a reader would call a different amount.
AMOUNT_TOLERANCE = Decimal("0.000001")

CONFIRMED, MISMATCH, UNCHECKED = "confirmed", "mismatch", "unchecked"
NATIVE_DECIMALS = {"tron": 6}  # every other chain traced here counts its coin in 18 decimals


@dataclass(frozen=True)
class Check:
    hash: str
    outcome: str
    detail: str = ""


@dataclass(frozen=True)
class Asset:
    """What a transfer moved: config.Token covers tokens, not a chain's own coin."""
    address: str | None  # None for the chain's own coin
    decimals: int

    @property
    def native(self) -> bool:
        return self.address is None


def _asset(chain_key: str, symbol: str | None) -> Asset | None:
    chain = config.CHAINS[chain_key]
    if symbol == chain.native_symbol:
        return Asset(None, NATIVE_DECIMALS.get(chain_key, 18))
    token = chain.find_token(symbol or "")
    return Asset(token.address, token.decimals) if token else None


def _same_address(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.lower() == b.lower() if a.startswith("0x") else a == b


def _same_amount(amount: Decimal, stored: Any) -> bool:
    return abs(amount - Decimal(str(stored))) <= AMOUNT_TOLERANCE


def _names(transfer: dict[str, Any], sender: str | None, recipient: str | None, amount: Decimal) -> str | None:
    """Why this reading disagrees with the report, or None if it does not."""
    if not _same_address(sender, transfer.get("from")):
        return f"sender is {sender}, the report says {transfer.get('from')}"
    if not _same_address(recipient, transfer.get("to")):
        return f"recipient is {recipient}, the report says {transfer.get('to')}"
    if not _same_amount(amount, transfer.get("value_native", 0)):
        return f"amount is {amount}, the report says {transfer.get('value_native')}"
    return None


def check_ethereum(transfer: dict[str, Any], answer: dict[str, Any], token: Asset) -> Check:
    tx, receipt = answer.get("transaction"), answer.get("receipt")
    digest = transfer.get("hash")
    if not tx:
        return Check(digest, MISMATCH, "the second provider does not have this transaction")
    if transfer.get("internal"):
        return Check(digest, UNCHECKED, "the transaction exists, but it was moved by a contract call")
    if not receipt:
        # Without the receipt, success cannot be shown: a reverted transfer
        # carries the same from, to and value as one that went through.
        return Check(digest, UNCHECKED, "the second provider returned no receipt, so success cannot be confirmed")
    if receipt.get("status") == "0x0":
        return Check(digest, MISMATCH, "the transaction failed on chain")
    if receipt.get("status") != "0x1":
        return Check(digest, UNCHECKED, "the receipt does not say whether the transaction succeeded")
    if token.native:
        problem = _names(transfer, tx.get("from"), tx.get("to"), Decimal(int(tx.get("value", "0x0"), 16)) / 10**token.decimals)
        return Check(digest, MISMATCH, problem) if problem else Check(digest, CONFIRMED)
    closest = "no matching Transfer event in the transaction"
    for log in receipt.get("logs") or []:
        topics = log.get("topics") or []
        if len(topics) != 3 or topics[0] != TRANSFER_TOPIC or not _same_address(log.get("address"), token.address):
            continue
        problem = _names(transfer, "0x" + topics[1][-40:], "0x" + topics[2][-40:],
                         Decimal(int(log.get("data") or "0x0", 16)) / 10**token.decimals)
        if problem is None:
            return Check(digest, CONFIRMED)
        closest = problem
    return Check(digest, MISMATCH, closest)


def check_tron(transfer: dict[str, Any], answer: dict[str, Any], token: Asset) -> Check:
    digest = transfer.get("hash")
    if not answer or answer.get("hash") != digest:
        return Check(digest, MISMATCH, "the second provider does not have this transaction")
    if answer.get("contractRet") != "SUCCESS":
        return Check(digest, MISMATCH, f"the transaction did not succeed: {answer.get('contractRet')}")
    if transfer.get("internal"):
        return Check(digest, UNCHECKED, "the transaction exists, but it was moved by a contract call")
    if token.native:
        return Check(digest, UNCHECKED, "native TRX is not read by this script yet")
    closest = "no matching token transfer in the transaction"
    for item in answer.get("trc20TransferInfo") or []:
        if item.get("contract_address") != token.address:
            continue
        problem = _names(transfer, item.get("from_address"), item.get("to_address"),
                         Decimal(item.get("amount_str") or "0") / 10**int(item.get("decimals", token.decimals)))
        if problem is None:
            return Check(digest, CONFIRMED)
        closest = problem
    return Check(digest, MISMATCH, closest)


CHECKERS: dict[str, Callable[[dict[str, Any], dict[str, Any], Asset], Check]] = {
    "ethereum": check_ethereum, "tron": check_tron,
}


# -- reading ---------------------------------------------------------------------
def _ethereum_rpc(http: httpx.Client, method: str, digest: str) -> dict[str, Any] | None:
    """The first node with an answer: one without old history returns null for a real transaction.

    None only when every node gave a clean null. A JSON-RPC error (how public
    nodes answer when they rate-limit, with HTTP 200) is a failed node, not
    "no such transaction": if any node failed and none answered, this raises,
    and the transfer is unchecked rather than a mismatch."""
    failures: list[str] = []
    for node in ETHEREUM_NODES:
        try:
            response = http.post(node, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": [digest]})
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            failures.append(f"{node}: {type(exc).__name__}")
            continue
        if not isinstance(body, dict) or "error" in body or "result" not in body:
            error = body.get("error") if isinstance(body, dict) else None
            failures.append(f"{node}: {error.get('message') if isinstance(error, dict) else 'no result'}")
            continue
        if body["result"]:
            return body["result"]
    if failures:
        raise httpx.HTTPError(f"{method}: no clean answer ({'; '.join(failures)})")
    return None


def read_live(http: httpx.Client, chain_key: str, digest: str, token: Asset) -> dict[str, Any]:
    if chain_key == "tron":
        response = http.get(TRONSCAN, params={"hash": digest})
        response.raise_for_status()
        return response.json()
    answer = {"transaction": _ethereum_rpc(http, "eth_getTransactionByHash", digest)}
    answer["receipt"] = _ethereum_rpc(http, "eth_getTransactionReceipt", digest) if answer["transaction"] else None
    return answer


def _chain_key(report: dict[str, Any]) -> str | None:
    name = (report.get("case") or {}).get("chain")
    return next((key for key, chain in config.CHAINS.items() if name in (chain.name, key)), None)


def verify(report: dict[str, Any], read: Callable[[str, str, Asset], dict[str, Any]]) -> list[Check]:
    """One Check per transfer in the report's Appendix B. `read` gets (chain key, hash, token)."""
    transfers = (report.get("appendix") or {}).get("transactions") or []
    chain_key = _chain_key(report)
    token = _asset(chain_key, (report.get("case") or {}).get("asset")) if chain_key else None
    checks = []
    for transfer in transfers:
        digest = transfer.get("hash")
        if chain_key not in CHECKERS:
            checks.append(Check(digest, UNCHECKED, f"this script does not cover {(report.get('case') or {}).get('chain')}"))
        elif token is None:
            checks.append(Check(digest, UNCHECKED, f"unknown asset {(report.get('case') or {}).get('asset')}"))
        else:
            try:
                checks.append(CHECKERS[chain_key](transfer, read(chain_key, digest, token), token))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                checks.append(Check(digest, UNCHECKED, f"the second provider could not be read: {str(exc)[:80]}"))
    return checks


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
                return saved.get(digest) or {}
            answer = read_live(http, chain_key, digest, token)
            recorded[digest] = answer
            time.sleep(SECONDS_BETWEEN_READS)
            return answer

        checks = verify(report, read)

    for check in checks:
        print(f"{check.outcome:<10} {check.hash}" + (f"  {check.detail}" if check.detail else ""))
    tally = {o: sum(c.outcome == o for c in checks) for o in (CONFIRMED, MISMATCH, UNCHECKED)}
    print(f"\n{len(checks)} transfers: {tally[CONFIRMED]} confirmed, {tally[MISMATCH]} mismatch, {tally[UNCHECKED]} unchecked")
    if report.get("follow_ons"):
        print("Follow-on traces after a swap are not in Appendix B, so they were not checked.")
    if args.record:
        args.record.write_text(json.dumps(recorded, indent=1) + "\n", encoding="utf-8")
        print(f"Saved {len(recorded)} responses to {args.record}")
    return exit_code(checks)


if __name__ == "__main__":
    raise SystemExit(main())
