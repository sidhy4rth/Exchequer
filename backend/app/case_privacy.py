"""A case's complaint particulars go only to the browser that traced it.

The case id is the case's reference: it is printed in every letter and
report, and holding it opens the case (ownership.py). That stays true -- an
exchange or Tether that receives a letter must be able to follow its
reference back to the evidence. But a payment-mode trace (R1) also stores the
victim's NCRP acknowledgement number, the wallet each payment came from and,
when the complaint gives it, the victim's own wallet, which the letters
themselves leave as blanks for the officer.

The victim's wallet can also be found without its address: a payment's
transaction hash names its sender on any block explorer, and so does the block
or the second it reached the reported address. So a reader who is not the
owner gets none of these either:

  - each payment's hash, block and time (the amount stays: letters and
    reports state how much was paid);
  - the wallet statement's incoming rows, which list the same transfers with
    their senders, and the time the statement's window opened;
  - the reported wallet's own window start in the graph (the first payment's
    time);
  - the payment hashes and the first payment's date quoted in warnings, and
    the payment's date in a "sent nothing since" message;
  - in the evidence manifest, the block, time and page parameters of every
    provider request (the reported wallet is read from the payment's block or
    time onward, and other reads are windowed around it -- "startblock=" on
    Etherscan, "fromBlock" on NodeReal, "min_timestamp=" on TronGrid), with
    those requests' response hashes and sizes, which could be matched by
    re-issuing candidate requests. The manifest hash is then recomputed over
    the records as this copy prints them, and the copy says how many were
    withheld; the owner's copy keeps the hash over the requests as made.

Every route that serves a case -- GET /trace/{id}, the reports, the graph
exports, the letters, a finished job -- serves the owner the case as stored
and everyone else this redacted copy, with `redacted` naming what was
withheld. Only the response is changed, never the stored case.

The victim flow (victim_flow.py) is built from the graph, the transfers and
the trace's own figures (pro-rata, materiality), none of which this
withholds, and it carries no hash, block or time. A case read without a
current one gets it built from the reader's copy.
"""
from __future__ import annotations

import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any

from .evidence import sha256_hex
from .models import Case

PARTICULARS = ["intake.ncrp_ack", "intake.victim_address", "intake.payments[].from"]
# What else leads back to the victim's wallet on a block explorer.
PAYMENT_LINKS = ["intake.payments[].tx_hash", "intake.payments[].block", "intake.payments[].timestamp",
                 "statement.credits", "statement.window_start", "graph.nodes[].window_start",
                 "warnings (payment hashes and dates)", "message (the payment's date)",
                 "evidence.records[].request (block, time and page parameters) and their response hashes"]

# What renderers print in place of a withheld hash or time.
WITHHELD = "withheld (only the browser that traced the case sees it)"

# payment_intake.review_payments: "The first payment (4 Nov 2023) is ...".
_FIRST_PAYMENT_DATE = re.compile(r"The first payment \(\d{1,2} [A-Z][a-z]{2} \d{4}\)")


# Provider request parameters that bound a read by block, time or position.
# Every one is withheld from a stranger's copy of a payment case, not only
# those equal to the payment's block or time: reads are also windowed
# relative to it (a statement read from two windows before, a pro-rata
# window from it), and a cursor can encode a position in time.
_QUERY_BOUNDS = frozenset({"startblock", "endblock", "min_timestamp", "max_timestamp", "fingerprint",
                           "blockno", "timestamp"})
_JSON_BOUNDS = frozenset({"fromBlock", "toBlock", "pageKey", "blockNumber", "blockHash"})
_OPEN = frozenset({"0", "latest", "earliest", "pending"})  # bounds that name no moment
_QUANTITY = re.compile(r"0x[0-9a-fA-F]{1,16}")  # a JSON-RPC block number, not an address or hash
WITHHELD_PARAM = "withheld"


def _bound_query(query: str) -> str:
    parts = []
    for part in query.split("&"):
        key, eq, value = part.partition("=")
        parts.append(f"{key}={WITHHELD_PARAM}" if eq and key in _QUERY_BOUNDS and value not in _OPEN else part)
    return "&".join(parts)


def _bound_json(value: Any, top: bool = False) -> Any:
    if isinstance(value, dict):
        return {k: (WITHHELD_PARAM if k in _JSON_BOUNDS and str(v) not in _OPEN else _bound_json(v))
                for k, v in value.items()}
    if isinstance(value, list):
        # A positional block number (eth_getBlockByNumber, eth_getTransactionCount).
        return [WITHHELD_PARAM if top and isinstance(v, str) and _QUANTITY.fullmatch(v) else _bound_json(v)
                for v in value]
    return value


def generalised_request(request: str, anchors: set[str]) -> str:
    """`request` with its block, time and page parameters withheld.

    Etherscan and TronGrid: "GET <url>?<query>". NodeReal: "POST <url> <method>
    <JSON params>"; TronGrid: "POST <url> <JSON payload>". If a payment's
    block or time is still in it after that, in whatever form, the whole
    request is withheld."""
    method, _, rest = request.partition(" ")
    if method == "GET" and "?" in rest:
        base, _, query = rest.partition("?")
        out = f"GET {base}?{_bound_query(query)}"
    else:
        cut = [i for i in (rest.find(" ["), rest.find(" {")) if i >= 0]
        out = request
        if method == "POST" and cut:
            head, payload = rest[:min(cut)], rest[min(cut) + 1:]
            try:
                params = json.loads(payload)
            except ValueError:
                params = None
            if params is not None:
                out = f"POST {head} {json.dumps(_bound_json(params, top=True), sort_keys=True)}"
    if any(re.search(rf"(?<![0-9A-Za-z]){re.escape(a)}(?![0-9A-Za-z])", out) for a in anchors):
        return f"{method} request withheld (it names the victim's payment)"
    return out


def _anchors(payments: list[dict[str, Any]]) -> set[str]:
    """Every form a payment's block or time takes in a provider request."""
    out: set[str] = set()
    for p in payments:
        block, when = p.get("block"), p.get("timestamp")
        if isinstance(block, int) and block > 0:
            out |= {str(block), hex(block)}
        if isinstance(when, int) and when > 0:
            out |= {str(when), str(when * 1000)}
        if isinstance(p.get("tx_hash"), str) and len(p["tx_hash"]) >= 10:
            out |= {p["tx_hash"], p["tx_hash"].removeprefix("0x")}
    return out


def _evidence_hidden(evidence: dict[str, Any], payments: list[dict[str, Any]]) -> dict[str, Any]:
    anchors = _anchors(payments)
    records, withheld = [], 0
    for rec in evidence.get("records") or []:
        if not isinstance(rec, dict) or not isinstance(rec.get("request"), str):
            records.append(rec)
            continue
        request = generalised_request(rec["request"], anchors)
        if request == rec["request"]:
            records.append(rec)
            continue
        withheld += 1
        records.append({k: v for k, v in rec.items() if k not in ("value_sha256",)}
                       | {"request": request, "sha256": WITHHELD_PARAM, "bytes": None, "withheld": True})
    if not withheld:
        return evidence
    lines = sorted(f"{r.get('sha256')}  {r.get('provider')}  {r.get('request')}" for r in records if isinstance(r, dict))
    return {**evidence, "records": records, "withheld": withheld, "manifest_sha256": sha256_hex("\n".join(lines))}


def _payment_days(payments: list[dict[str, Any]]) -> list[str]:
    days = []
    for p in payments:
        if isinstance(p.get("timestamp"), int) and p["timestamp"] > 0:
            moment = datetime.fromtimestamp(p["timestamp"], tz=timezone.utc)
            days += [f"{moment:%d %b %Y}", f"{moment.day} {moment:%b %Y}"]
    return days


def is_owner(stored: str | None, caller: str | None) -> bool:
    return bool(stored and caller) and hmac.compare_digest(stored, caller)


def _short(tx_hash: str) -> str:
    """As payment_intake quotes a hash in a warning."""
    return f"{tx_hash[:6]}…{tx_hash[-4:]}"


def _scrub_warning(text: str, hashes: list[str]) -> str:
    for tx_hash in hashes:
        text = text.replace(tx_hash, "(hash withheld)").replace(_short(tx_hash), "(hash withheld)")
    return _FIRST_PAYMENT_DATE.sub("The first payment", text)


def _payment_links_hidden(result: dict[str, Any], intake: dict[str, Any]) -> dict[str, Any]:
    payments = [p for p in intake.get("payments") or [] if isinstance(p, dict)]
    hashes = [p["tx_hash"] for p in payments if isinstance(p.get("tx_hash"), str) and len(p["tx_hash"]) >= 10]
    times = {p.get("timestamp") for p in payments if p.get("timestamp")}
    out: dict[str, Any] = {}

    statement = result.get("statement")
    if isinstance(statement, dict):
        debits = [{k: v for k, v in row.items() if k != "before_window"} if isinstance(row, dict) else row
                  for row in statement.get("debits") or []]
        # Every credit, not only the payments: hiding just those rows would
        # point at them, by comparing the rest with an explorer's list.
        out["statement"] = {**statement, "debits": debits, "credits": [],
                            "poisoning": [r for r in statement.get("poisoning") or []
                                          if not (isinstance(r, dict) and r.get("tx") in hashes)],
                            "window_start": None}

    graph = result.get("graph")
    if isinstance(graph, dict) and isinstance(graph.get("nodes"), list):
        nodes = [{**n, "window_start": None} if isinstance(n, dict) and n.get("window_start") in times else n
                 for n in graph["nodes"]]
        out["graph"] = {**graph, "nodes": nodes}

    if isinstance(result.get("warnings"), list):
        out["warnings"] = [_scrub_warning(w, hashes) if isinstance(w, str) else w for w in result["warnings"]]

    if isinstance(result.get("evidence"), dict):
        out["evidence"] = _evidence_hidden(result["evidence"], payments)

    message = result.get("message")
    if isinstance(message, str):
        # "... sent no BNB since 04 Nov 2023": the search floor can be the payment's block.
        for day in _payment_days(payments):
            message = message.replace(f" since {day}", " since the first payment")
        out["message"] = message

    return out


def for_reader(result: dict[str, Any], stored_owner: str | None, caller: str | None) -> dict[str, Any]:
    """The case as `caller` may read it."""
    intake = result.get("intake")
    if not isinstance(intake, dict) or is_owner(stored_owner, caller):
        return result
    payments = [{**p, "from": None, "tx_hash": None, "block": None, "timestamp": None}
                for p in intake.get("payments") or [] if isinstance(p, dict)]
    hidden = {**intake, "ncrp_ack": None, "payments": payments}
    if "victim_address" in intake:
        hidden["victim_address"] = None
    seen = {**result, "intake": hidden, "redacted": PARTICULARS}
    if intake.get("mode") == "payment" and payments:
        seen.update(_payment_links_hidden(result, intake))
        seen["redacted"] = PARTICULARS + PAYMENT_LINKS
    return seen


def case_for_reader(case: Case, caller: str | None) -> Case:
    """The stored case, or a copy (never saved) holding what `caller` may read,
    for the routes that render a case: the report, the graph and the letters.
    The copy's content differs, so report_cache keeps its renders apart."""
    result = case.result
    seen = for_reader(result, case.owner_hash, caller)
    if seen is result:
        return case
    return Case(id=case.id, address=case.address, created_at=case.created_at,
                result_json=json.dumps(seen), owner_hash=case.owner_hash)
