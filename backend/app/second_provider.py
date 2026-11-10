"""Re-read transfers from a provider the trace did not use.

A case's arithmetic can be re-done from the case, but its inputs came from one
data provider at one moment. This asks a different one: for each transfer, did
it succeed, and did the named sender pay the named recipient that amount of
that asset?

    Trace read from   Re-read here from
    Etherscan         public Ethereum nodes (cloudflare-eth.com, eth.drpc.org)
    TronGrid          TronScan

Three outcomes, because the difference matters to anyone relying on this:

    confirmed   The second provider says the same thing.
    mismatch    It says something different, or does not have the transaction.
    unchecked   This run cannot tell: the provider failed, the chain is not covered,
                or the transfer was moved by a contract call, which a plain read of
                the transaction does not show.

Unchecked is never reported as confirmed. What this establishes: two independent
providers agree on these transactions. It does not establish who controls any
address.

scripts/verify_case.py runs it over a report's Appendix B from the command line.
POST /trace/{id}/recheck (routes/recheck.py) runs it over the transfers a case
cites on its way to the exchange (cited_transfers) -- at most
RECHECK_MAX_TRANSFERS of them, as "matches", "differs", "not_found" or "error".
Each read is charged to the provider's daily allowance, waits on the pacer the
site's other readers of that provider share, and is read to a size cap
(api_budget.read_capped): this runs inside the web server.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial
from typing import Any

import httpx

from . import api_budget, config, request_letters, tron_tags
from .input_rules import plain_text
from .report import attribution_kind

ETHEREUM_NODES = ("https://cloudflare-eth.com", "https://eth.drpc.org")
TRONSCAN = "https://apilist.tronscanapi.com/api/transaction-info"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"  # Transfer(address,address,uint256)
SECONDS_BETWEEN_READS = 0.3
# Amounts in a case are rounded when stored; one part in a million of a coin is
# well inside that and far below anything a reader would call a different amount.
AMOUNT_TOLERANCE = Decimal("0.000001")

CONFIRMED, MISMATCH, UNCHECKED = "confirmed", "mismatch", "unchecked"
NATIVE_DECIMALS = {"tron": 6}  # every other chain traced here counts its coin in 18 decimals
NOT_FOUND = "the second provider does not have this transaction"


@dataclass(frozen=True)
class Check:
    hash: str
    outcome: str
    detail: str = ""
    # (what, the case's value, the provider's) for each part of a mismatch.
    differences: tuple[tuple[str, str, str], ...] = ()


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


def _differences(transfer: dict[str, Any], sender: str | None, recipient: str | None,
                 amount: Decimal) -> tuple[tuple[str, str, str], ...]:
    """Where this reading disagrees with the case; () when it does not."""
    found = []
    if not _same_address(sender, transfer.get("from")):
        found.append(("sender", str(transfer.get("from")), str(sender)))
    if not _same_address(recipient, transfer.get("to")):
        found.append(("recipient", str(transfer.get("to")), str(recipient)))
    if not _same_amount(amount, transfer.get("value_native", 0)):
        found.append(("amount", str(transfer.get("value_native")), str(amount)))
    return tuple(found)


def _mismatch(digest: str, differences: tuple[tuple[str, str, str], ...]) -> Check:
    what, case_value, provider_value = differences[0]
    return Check(digest, MISMATCH, f"{what} is {provider_value}, the report says {case_value}", differences)


def check_ethereum(transfer: dict[str, Any], answer: dict[str, Any], token: Asset) -> Check:
    tx, receipt = answer.get("transaction"), answer.get("receipt")
    digest = transfer.get("hash")
    if not tx:
        return Check(digest, MISMATCH, NOT_FOUND)
    if transfer.get("internal"):
        return Check(digest, UNCHECKED, "the transaction exists, but it was moved by a contract call")
    if not receipt:
        # Without the receipt, success cannot be shown: a reverted transfer
        # carries the same from, to and value as one that went through.
        return Check(digest, UNCHECKED, "the second provider returned no receipt, so success cannot be confirmed")
    if receipt.get("status") == "0x0":
        return Check(digest, MISMATCH, "the transaction failed on chain", (("status", "succeeded", "failed"),))
    if receipt.get("status") != "0x1":
        return Check(digest, UNCHECKED, "the receipt does not say whether the transaction succeeded")
    if token.native:
        found = _differences(transfer, tx.get("from"), tx.get("to"),
                             Decimal(int(tx.get("value", "0x0"), 16)) / 10**token.decimals)
        return _mismatch(digest, found) if found else Check(digest, CONFIRMED)
    closest = Check(digest, MISMATCH, "no matching Transfer event in the transaction")
    for log in receipt.get("logs") or []:
        topics = log.get("topics") or []
        if len(topics) != 3 or topics[0] != TRANSFER_TOPIC or not _same_address(log.get("address"), token.address):
            continue
        found = _differences(transfer, "0x" + topics[1][-40:], "0x" + topics[2][-40:],
                             Decimal(int(log.get("data") or "0x0", 16)) / 10**token.decimals)
        if not found:
            return Check(digest, CONFIRMED)
        closest = _mismatch(digest, found)
    return closest


def check_tron(transfer: dict[str, Any], answer: dict[str, Any], token: Asset) -> Check:
    digest = transfer.get("hash")
    if not answer or answer.get("hash") != digest:
        return Check(digest, MISMATCH, NOT_FOUND)
    if answer.get("contractRet") != "SUCCESS":
        return Check(digest, MISMATCH, f"the transaction did not succeed: {answer.get('contractRet')}",
                     (("status", "SUCCESS", str(answer.get("contractRet"))),))
    if transfer.get("internal"):
        return Check(digest, UNCHECKED, "the transaction exists, but it was moved by a contract call")
    if token.native:
        return Check(digest, UNCHECKED, "native TRX is not reread yet")
    closest = Check(digest, MISMATCH, "no matching token transfer in the transaction")
    for item in answer.get("trc20TransferInfo") or []:
        if item.get("contract_address") != token.address:
            continue
        # The token's own decimals, never TronScan's: "decimals": 1000000000 is
        # a few bytes, and 10**it would hold the web server for minutes.
        decimals = item.get("decimals", token.decimals)
        if type(decimals) is not int or decimals != token.decimals:
            return Check(digest, UNCHECKED, "the second provider's answer is not in the shape expected")
        found = _differences(transfer, item.get("from_address"), item.get("to_address"),
                             Decimal(item.get("amount_str") or "0") / 10**token.decimals)
        if not found:
            return Check(digest, CONFIRMED)
        closest = _mismatch(digest, found)
    return closest


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
            response = api_budget.read_capped(http, "POST", node,
                                              json={"jsonrpc": "2.0", "id": 1, "method": method, "params": [digest]})
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError, api_budget.ResponseTooLarge) as exc:
            failures.append(f"{node}: {type(exc).__name__}")
            continue
        if not isinstance(body, dict) or "error" in body or "result" not in body:
            error = body.get("error") if isinstance(body, dict) else None
            failures.append(f"{node}: {error.get('message') if isinstance(error, dict) else 'no result'}")
            continue
        if body["result"] is not None and not isinstance(body["result"], dict):
            failures.append(f"{node}: the result is not a transaction or a receipt")
            continue
        if body["result"]:
            return body["result"]
    if failures:
        raise httpx.HTTPError(f"{method}: no clean answer ({'; '.join(failures)})")
    return None


def read_live(http: httpx.Client, chain_key: str, digest: str, token: Asset) -> dict[str, Any]:
    if chain_key == "tron":
        response = api_budget.read_capped(http, "GET", TRONSCAN, params={"hash": digest})
        response.raise_for_status()
        body = response.json()
        # {} is TronScan's "no such transaction"; a refusal can come as HTTP 200
        # with an error and no transaction, which is a failed read, not an answer.
        if not isinstance(body, dict):
            raise ValueError("TronScan's answer is not an object")
        error = body.get("Error") or body.get("error")
        if error and not body.get("hash"):
            raise httpx.HTTPError(f"TronScan refused: {str(error)[:60]}")
        return body
    answer = {"transaction": _ethereum_rpc(http, "eth_getTransactionByHash", digest)}
    answer["receipt"] = _ethereum_rpc(http, "eth_getTransactionReceipt", digest) if answer["transaction"] else None
    return answer


READ_FAILED = (httpx.HTTPError, ValueError, KeyError, api_budget.ResponseTooLarge)
# An answer whose parts are not the shape a provider gives (a log that is not
# an object, say) is a failed read, not a disagreement.
BAD_SHAPE = (TypeError, AttributeError, ArithmeticError)


def _failed(digest: Any, exc: Exception) -> Check:
    if isinstance(exc, BAD_SHAPE):
        return Check(digest, UNCHECKED, "the second provider's answer is not in the shape expected")
    return Check(digest, UNCHECKED, f"the second provider could not be read: {str(exc)[:80]}")


def check_transfers(chain_key: str | None, symbol: str | None, transfers: list[dict[str, Any]],
                    read: Callable[[str, str, Asset], dict[str, Any]], chain_label: Any = None) -> list[Check]:
    """One Check per transfer, in order, all moving `symbol` on `chain_key`.
    `read` gets (chain key, hash, token), once per distinct hash."""
    token = _asset(chain_key, symbol) if chain_key in config.CHAINS else None
    by_hash: dict[Any, list[int]] = {}
    for i, transfer in enumerate(transfers):
        by_hash.setdefault(transfer.get("hash"), []).append(i)
    checks: list[Check | None] = [None] * len(transfers)
    for digest, rows in by_hash.items():
        answer, failed = None, None
        if chain_key not in CHECKERS:
            failed = Check(digest, UNCHECKED, f"the recheck does not cover {chain_label or chain_key}")
        elif token is None:
            failed = Check(digest, UNCHECKED, f"unknown asset {symbol}")
        else:
            try:
                answer = read(chain_key, digest, token)
            except READ_FAILED + BAD_SHAPE as exc:
                failed = _failed(digest, exc)
        for i in rows:
            try:
                checks[i] = failed or CHECKERS[chain_key](transfers[i], answer, token)
            except READ_FAILED + BAD_SHAPE as exc:
                checks[i] = _failed(digest, exc)
    return checks  # type: ignore[return-value]


# -- a case's cited transfers (POST /trace/{id}/recheck) ---------------------------------
RECHECK_MAX_TRANSFERS = 40
RECHECK_SECONDS = 60  # the recheck's wall clock; a read after it is an error, never a wait
READ_TIMEOUT = 10.0
# The provider each chain is reread from: its allowance's name (api_budget) and how a recheck names it.
PROVIDERS = {"ethereum": ("ethereum-nodes", "public Ethereum nodes (cloudflare-eth.com, eth.drpc.org)"),
             "tron": ("tronscan", "TronScan")}
STATUS = {CONFIRMED: "matches", MISMATCH: "differs", UNCHECKED: "error"}
TRANSPORT: httpx.BaseTransport | None = None  # the network; the tests serve recordings here


def _chain_key(name: Any) -> str | None:
    try:
        return config.get_chain(name).key if name else None
    except config.UnknownChainError:
        return None


def _hops(steps: Any, rows: list[dict[str, Any]], asset: Any) -> list[list[dict[str, Any]]]:
    """Each hop's cited transfers, in path order, with the asset they moved: the
    rows between two steps whose hash the later step lists (tx_hashes, what the
    letters and the report print), or every row on a hop stored without the list."""
    path = [s for s in steps or [] if isinstance(s, dict)]
    out = []
    for before, step in zip(path, path[1:], strict=False):
        listed = step.get("tx_hashes")
        listed = set(listed) if isinstance(listed, list) else None
        pair = (before.get("address"), step.get("address"))
        out.append([{**t, "asset": asset} for t in rows
                     if (t.get("from"), t.get("to")) == pair and (listed is None or t.get("hash") in listed)])
    return out


def _in_turn(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Every row once, taking one from each group in turn, so the first rows reach every group."""
    out, seen, queues = [], set(), [iter(g) for g in groups]
    while queues:
        for queue in list(queues):
            for row in queue:
                key = (row.get("asset"), row.get("hash"), row.get("from"), row.get("to"), row.get("value_native"))
                if key not in seen:
                    seen.add(key)
                    out.append(row)
                    break
            else:
                queues.remove(queue)
    return out


def cited_transfers(result: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    """(chain key, the transfers the case cites on its way to the exchange), each
    with the "asset" it moved. Those are: every hash a letter or the report prints
    on the attributed trace's path; every deposit into the exchange's address when
    its letter lists them all (a company wallet); and after a swap, the swap and
    the route to it, in the asset sent. Nearest the exchange first and one hop at
    a time, so the first RECHECK_MAX_TRANSFERS always hold the hop into the
    exchange and reach every hop. Empty when the case reached no exchange."""
    found = request_letters._attribution(result)
    if found is None:
        return _chain_key(result.get("chain")), []
    trace, asset = found["trace"], found["asset"]
    exchange = trace.get("exchange_address")
    rows = [t for t in trace.get("transfers") or [] if isinstance(t, dict)]
    hops = _hops(trace.get("trace_path"), rows, asset)
    start = next((s for s in trace.get("trace_path") or [] if isinstance(s, dict)), {})
    if start.get("address") != exchange:  # the money ran toward the exchange: its hop is the last
        hops.reverse()
    groups = hops[:1]
    if attribution_kind(trace) in request_letters.COMPANY_WALLET_KINDS:
        groups.append([{**t, "asset": asset} for t in rows if t.get("to") == exchange])
    groups += hops[1:]
    swap = found["via_swap"] or {}
    if swap:
        asset_in = swap.get("asset_in") or result.get("asset")
        before = [t for t in result.get("transfers") or [] if isinstance(t, dict)]
        groups.append([{**t, "asset": asset_in} for t in before
                       if t.get("hash") == swap.get("tx") and t.get("from") == swap.get("sender")])
        groups += reversed(_hops(found["route"], before, asset_in))
    return _chain_key(trace.get("chain") or result.get("chain")), _in_turn(groups)


def rereadable(chain_key: str, cited: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cited transfers a reread can say something of. A transfer moved by a
    contract call, native TRX and an unknown asset stay unchecked whatever the
    provider answers (check_ethereum, check_tron), so they are not read at all."""
    def can(row: dict[str, Any]) -> bool:
        token = _asset(chain_key, row.get("asset"))
        return token is not None and not row.get("internal") and not (chain_key == "tron" and token.native)
    return [row for row in cited if can(row)]


def _credential(provider: str) -> str:
    return api_budget.credential(config.TRONSCAN_API_KEY if provider == "tronscan" else None)


def allowance_spent(chain_key: str, client: str | None) -> tuple[int, str] | None:
    """(seconds until it comes back, "site" or "client") when the provider's daily
    allowance is used up for this site, or this connection's share of it is."""
    provider = PROVIDERS[chain_key][0]
    meter = api_budget.get_meter(provider, _credential(provider))
    who = meter.spent(client=client)
    return (meter.seconds_to_reset(), who) if who else None


def _pacer(provider: str) -> api_budget.SharedPacer:
    """The pacer every reader of the provider shares: TronScan's is the one a
    live trace's tag lookups wait on for the same key (tron_tags.pacer)."""
    if provider == "tronscan":
        return tron_tags.pacer(config.TRONSCAN_API_KEY)
    return api_budget.get_pacer(provider, lambda: api_budget.SharedPacer(SECONDS_BETWEEN_READS, max_interval=2.0))


def _client(provider: str, budget: api_budget.TraceBudget) -> httpx.Client:
    """An HTTP client whose every request is first charged to the recheck's
    clock and the provider's daily allowance (api_budget.spend), then waits its
    turn on the shared pacer, with a timeout that cannot outlast the clock. A
    refused request fails like an unreachable provider, never as an answer."""
    credential, pacer = _credential(provider), _pacer(provider)

    def before(request: httpx.Request) -> None:
        try:
            api_budget.spend(provider, credential, 1, budget)
            pacer.wait()
            budget.check()
        except api_budget.TraceStopped as exc:
            raise httpx.RequestError(exc.reason, request=request) from exc
        request.extensions["timeout"] = httpx.Timeout(budget.timeout(READ_TIMEOUT)).as_dict()

    def after(response: httpx.Response) -> None:
        if response.status_code == 429:
            pacer.penalize()
        elif response.is_success:
            pacer.reward()

    headers = {"User-Agent": "Exchequer/1.0"}
    if provider == "tronscan" and config.TRONSCAN_API_KEY:
        headers["TRON-PRO-API-KEY"] = config.TRONSCAN_API_KEY
    return httpx.Client(timeout=READ_TIMEOUT, headers=headers, transport=TRANSPORT,
                        event_hooks={"request": [before], "response": [after]})


def _row(check: Check) -> dict[str, Any]:
    """One transfer's line; the provider's words pass through plain_text."""
    status = "not_found" if check.outcome == MISMATCH and check.detail == NOT_FOUND else STATUS[check.outcome]
    return {"hash": check.hash, "status": status,
            "differences": [{"field": what, "case": plain_text(ours, 100), "provider": plain_text(theirs, 100)}
                            for what, ours, theirs in check.differences],
            "detail": plain_text(check.detail, 200) or None}


def recheck(result: dict[str, Any], client: str | None) -> dict[str, Any]:
    """Reread a case's cited transfers (cited_transfers) for the connection
    `client`: the first RECHECK_MAX_TRANSFERS of those a reread can check;
    "skipped" counts the rest. The caller has checked the chain is in PROVIDERS."""
    chain_key, cited = cited_transfers(result)
    provider, name = PROVIDERS[chain_key]
    readable = rereadable(chain_key, cited)
    checked = readable[:RECHECK_MAX_TRANSFERS]
    budget = api_budget.TraceBudget(RECHECK_SECONDS, 0, client=client)
    rows: list[dict[str, Any]] = []
    with _client(provider, budget) as http:
        for asset in dict.fromkeys(t["asset"] for t in checked):  # a swap's route moved another asset
            moved = [t for t in checked if t["asset"] == asset]
            rows += [_row(c) for c in check_transfers(chain_key, asset, moved, partial(read_live, http))]
    counts = {status: sum(r["status"] == status for r in rows) for status in ("matches", "differs", "not_found", "error")}
    return {"chain": chain_key, "asset": request_letters._attribution(result)["asset"], "provider": name,
            "checked_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            "cited": len(cited), "checked": len(checked), "skipped": len(cited) - len(readable),
            "counts": counts, "transfers": rows}
