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
  - the payment hashes and the first payment's date quoted in warnings.

Every route that serves a case -- GET /trace/{id}, the reports, the graph
exports, the letters, a finished job -- serves the owner the case as stored
and everyone else this redacted copy, with `redacted` naming what was
withheld. Only the response is changed, never the stored case.
"""
from __future__ import annotations

import hmac
import json
import re
from typing import Any

from .models import Case

PARTICULARS = ["intake.ncrp_ack", "intake.victim_address", "intake.payments[].from"]
# What else leads back to the victim's wallet on a block explorer.
PAYMENT_LINKS = ["intake.payments[].tx_hash", "intake.payments[].block", "intake.payments[].timestamp",
                 "statement.credits", "statement.window_start", "graph.nodes[].window_start",
                 "warnings (payment hashes and dates)"]

# What renderers print in place of a withheld hash or time.
WITHHELD = "withheld (only the browser that traced the case sees it)"

# payment_intake.review_payments: "The first payment (4 Nov 2023) is ...".
_FIRST_PAYMENT_DATE = re.compile(r"The first payment \(\d{1,2} [A-Z][a-z]{2} \d{4}\)")


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
