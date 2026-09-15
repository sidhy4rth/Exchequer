"""Exportable case report for law-enforcement handoff.

The report is written for a reader who was not present when the trace ran and
who may not be technical. It therefore states, in order: what was reported,
what was found, how confident the tool is and exactly why, what the evidence
was, and -- importantly -- what the tool cannot tell you.

That last section is not boilerplate. A trace names an exchange, not a person;
saying so plainly in the artefact itself is what keeps the output honest when
it is read out of context.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import Case

REPORT_VERSION = "1.0"
TOOL_NAME = "TraceChain"


def build_report(case: Case) -> dict[str, Any]:
    """Structured report for one case. Safe to serve as JSON."""
    result = case.result
    confidence_detail = result.get("confidence_detail", {})
    native_symbol = result.get("native_symbol", "ETH")
    matches = result.get("matches", [])
    findings = result.get("findings", [])
    graph = result.get("graph", {})
    direction = result.get("direction", "outgoing")

    return {
        "report_version": REPORT_VERSION,
        "generated_by": TOOL_NAME,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "case": {
            "case_id": case.id,
            "reported_address": case.address,
            "traced_at": case.created_at,
            "chain": result.get("chain_name") or result.get("chain", "Ethereum Mainnet"),
            "chain_id": result.get("chain_id"),
            "native_currency": native_symbol,
            "block_explorer": result.get("explorer_url"),
            "direction": direction,
        },
        # Only meaningful on a reverse trace. Named for what the transactions
        # show -- these addresses funded the reported one -- because calling
        # them victims would be an inference the data does not support.
        "funding_sources": result.get("direct_senders", []),
        "attribution": {
            "claim": (
                "Exchange at which the traced funds arrived"
                if direction == "outgoing"
                else "Exchange from which the traced funds originated"
            ),
            "exchange": result.get("exchange"),
            "exchange_address": result.get("exchange_address"),
            "exchange_wallet_label": result.get("exchange_label"),
            "hop_count": result.get("hop_count"),
            "value_received_native": result.get("value_received_native"),
            "value_currency": native_symbol,
            "all_matches": matches,
        },
        "confidence": {
            "score": result.get("confidence"),
            "band": confidence_detail.get("band"),
            "summary": confidence_detail.get("summary"),
            "components": confidence_detail.get("components", []),
        },
        "trace_path": result.get("trace_path", []),
        # Sanctions / mixer screening sits above the patterns because it is a
        # finding of a different order: a pattern is this tool's inference from
        # arithmetic, while a sanctions hit is a published government
        # designation that an investigator must act on regardless of what the
        # rest of the trace concluded.
        "risk_screening": {
            "screened": True,
            "categories": result.get("risk_flags", []),
            "matches": result.get("risk_matches", []),
            "notes": result.get("risk_notes", []),
        },
        "patterns_detected": findings,
        "graph_summary": {
            "addresses": len(graph.get("nodes", [])),
            "transfers": len(graph.get("edges", [])),
            "max_depth_reached": result.get("depth_reached"),
            "truncated": result.get("truncated", False),
            "truncation_reasons": result.get("truncation_reasons", []),
        },
        "limitations": confidence_detail.get("caveats", []),
        "methodology": _methodology(native_symbol, direction),
    }


def _methodology(native_symbol: str = "ETH", direction: str = "outgoing") -> list[str]:
    """Plain description of what the tool did, so the result is reproducible."""
    if direction == "outgoing":
        walk = (
            f"Outgoing {native_symbol} transfers were followed from the reported "
            "address using breadth-first traversal, depth-limited, via a public "
            "blockchain data API."
        )
        grouping = (
            "At each address, transfers were grouped by recipient and the "
            "highest-value destinations followed first; dust transfers below a "
            "minimum threshold were excluded as spam."
        )
    else:
        walk = (
            f"Incoming {native_symbol} transfers were followed backwards from "
            "the reported address using breadth-first traversal, depth-limited, "
            "via a public blockchain data API. The graph therefore shows which "
            "addresses funded the reported one, not where its funds went."
        )
        grouping = (
            "At each address, transfers were grouped by sender and the "
            "highest-value sources followed first; dust transfers below a "
            "minimum threshold were excluded as spam."
        )
    if direction == "outgoing":
        timing = (
            "At every address after the reported one, only transfers made at "
            "or after the moment the traced funds arrived there were followed. "
            "Money cannot be forwarded before it is received, so anything the "
            "address sent earlier was left out of the graph."
        )
    else:
        timing = (
            "At every address before the reported one, only transfers received "
            "at or before the moment it paid the next address were followed, "
            "since only money already held could have funded that payment."
        )
    return [
        walk,
        grouping,
        timing,
        "Every address in the resulting graph was compared, by exact match, "
        "against a database of publicly labelled exchange wallets.",
        "Every address was also screened, by exact match, against digital "
        "currency addresses published on the U.S. Treasury's Specially "
        "Designated Nationals list. A trace is stopped at any address "
        "identified as a mixer: its payouts come from a commingled pool, so "
        "transfers leaving it have no established link to the deposit traced.",
        "Laundering patterns were identified using fixed arithmetic rules "
        "(peel chain, amount split). Each finding records the thresholds it "
        "applied so it can be re-checked by hand.",
        "Confidence combines three weighted factors: proximity to the reported "
        "address (40%), how much of the value survived the route (35%), and "
        "how direct the exchange match was (25%).",
        "No machine learning or proprietary scoring is used. Every conclusion "
        "in this report can be reproduced from the transaction data.",
    ]


def render_text_report(report: dict[str, Any]) -> str:
    """Human-readable plain-text version, suitable for printing or attaching."""
    out: list[str] = []
    add = out.append

    def rule(char: str = "=") -> None:
        add(char * 78)

    case = report["case"]
    attribution = report["attribution"]
    confidence = report["confidence"]
    symbol = case.get("native_currency", "ETH")
    direction = case.get("direction", "outgoing")

    rule()
    add(f"{TOOL_NAME.upper()} - CRYPTOCURRENCY TRACE REPORT")
    rule()
    add(f"Case ID          : {case['case_id']}")
    add(f"Reported address : {case['reported_address']}")
    chain_line = case["chain"]
    if case.get("chain_id"):
        chain_line += f" (chainid {case['chain_id']})"
    add(f"Chain            : {chain_line}")
    add(f"Direction        : "
        + ("outgoing (where the funds went)" if direction == "outgoing"
           else "incoming (who funded this address)"))
    add(f"Traced at        : {case['traced_at']}")
    add(f"Report generated : {report['generated_at']}")
    add("")

    rule("-")
    add("ATTRIBUTION")
    rule("-")
    if attribution.get("claim"):
        add(f"Claim            : {attribution['claim']}")
    if attribution["exchange"]:
        add(f"Exchange         : {attribution['exchange']}")
        add(f"Wallet           : {attribution['exchange_address']}")
        if attribution.get("exchange_wallet_label"):
            add(f"Wallet label     : {attribution['exchange_wallet_label']}")
        add(f"Hops from source : {attribution['hop_count']}")
        if attribution.get("value_received_native") is not None:
            label = "Value received  " if direction == "outgoing" else "Value sent      "
            add(f"{label} : {attribution['value_received_native']} {symbol}")
    elif direction == "outgoing":
        add("No known exchange wallet was reached within the traced depth.")
        add("This does not establish that the funds were not cashed out.")
    else:
        add("No known exchange wallet was found upstream within the traced depth.")
        add("This does not establish that the funds did not originate at one.")
    add("")

    # A reverse trace's substantive output. Printed before confidence because
    # on this kind of trace it, not the attribution, is the finding.
    funders = report.get("funding_sources") or []
    if direction == "incoming" and funders:
        rule("-")
        add("ADDRESSES THAT FUNDED THE REPORTED ADDRESS")
        rule("-")
        for line in _wrap(
            "Each address below sent funds directly to the reported address. "
            "Where the reported address belongs to an offender, these senders "
            "are candidate victims of the same operation and may each hold a "
            "separate complaint. This list states only what the transactions "
            "show: a sender may equally be the offender's own wallet, an "
            "exchange withdrawal, or an unrelated payment."
        ):
            add(line)
        add("")
        add(f"{'address':<44} {'value ' + symbol:>16} {'tx':>4}  note")
        add("-" * 78)
        for sender in funders:
            note = ""
            if sender.get("exchange"):
                note = f"{sender['exchange']} (withdrawal, not a victim)"
            elif sender.get("risk_category"):
                note = sender["risk_category"]
            add(f"{sender['address']:<44} {sender['value_native']:>16,.2f} "
                f"{sender.get('tx_count', 0):>4}  {note}")
        add("")

    rule("-")
    add("CONFIDENCE")
    rule("-")
    score = confidence.get("score")
    add(f"Score            : {score if score is not None else 'n/a'}"
        f"  ({confidence.get('band', 'n/a')})")
    if confidence.get("summary"):
        add("")
        for line in _wrap(confidence["summary"]):
            add(line)
    if confidence.get("components"):
        add("")
        add("How this score was reached:")
        for component in confidence["components"]:
            add(f"  - {component['name']} "
                f"(raw {component['raw_value']} x weight {component['weight']} "
                f"= {component['contribution']})")
            for line in _wrap(component["explanation"], indent="      "):
                add(line)
    add("")

    if report.get("trace_path"):
        rule("-")
        add("TRACE PATH (reported address -> exchange)" if direction == "outgoing"
            else "TRACE PATH (exchange -> reported address)")
        rule("-")
        for i, step in enumerate(report["trace_path"]):
            arrow = "    |" if i else ""
            if arrow:
                add(arrow)
                amount = step.get("value_native")
                if amount is not None:
                    add(f"    | {amount} {symbol}"
                        + (f"  ({step['tx_count']} tx)" if step.get("tx_count") else ""))
                add("    v")
            label = f"  [{step['label']}]" if step.get("label") else ""
            add(f"[{i}] {step['address']}{label}")
        add("")

    # Screening comes before the heuristics: a published designation outranks
    # this tool's own arithmetic, and an investigator reading top-down should
    # meet it first.
    screening = report.get("risk_screening") or {}
    rule("-")
    add("SANCTIONS AND MIXER SCREENING")
    rule("-")
    if screening.get("matches"):
        for note in screening.get("notes", []):
            for line in _wrap(note, bullet="* "):
                add(line)
            add("")
    else:
        add("No address in this trace appeared on the screened lists.")
        add("Screening is an exact match against digital currency addresses")
        add("published on the U.S. Treasury SDN list; an address absent from")
        add("that list is not thereby established as legitimate.")
        add("")

    if report.get("patterns_detected"):
        rule("-")
        add("LAUNDERING PATTERNS DETECTED")
        rule("-")
        for finding in report["patterns_detected"]:
            add(f"* {finding['pattern'].replace('_', ' ').upper()} "
                f"(strength {finding.get('strength')})")
            for line in _wrap(finding["description"], indent="  "):
                add(line)
            add("")
    else:
        rule("-")
        add("LAUNDERING PATTERNS DETECTED")
        rule("-")
        add("None. The traced transfers did not match the peel-chain or")
        add("amount-split heuristics.")
        add("")

    summary = report["graph_summary"]
    rule("-")
    add("TRACE SCOPE")
    rule("-")
    add(f"Addresses examined : {summary['addresses']}")
    add(f"Transfers examined : {summary['transfers']}")
    add(f"Depth reached      : {summary['max_depth_reached']}")
    add(f"Truncated          : {'yes' if summary['truncated'] else 'no'}")
    for reason in summary.get("truncation_reasons", []):
        add(f"  - {reason}")
    add("")

    rule("-")
    add("LIMITATIONS")
    rule("-")
    for item in report.get("limitations", []):
        for line in _wrap(item, bullet="- "):
            add(line)
    add("")

    rule("-")
    add("METHODOLOGY")
    rule("-")
    for item in report["methodology"]:
        for line in _wrap(item, bullet="- "):
            add(line)
    add("")

    rule()
    add(f"Generated by {TOOL_NAME} (report format v{report['report_version']}).")
    add("Automated analysis of public blockchain data. Findings should be")
    add("independently verified before use in legal proceedings.")
    rule()

    return "\n".join(out)


def _wrap(text: str, width: int = 78, indent: str = "", bullet: str = "") -> list[str]:
    """Wrap `text` to `width`, honouring an optional bullet and indent."""
    import textwrap

    prefix = indent + bullet
    subsequent = indent + (" " * len(bullet))
    return textwrap.wrap(text, width=width, initial_indent=prefix,
                         subsequent_indent=subsequent) or [prefix.rstrip()]
