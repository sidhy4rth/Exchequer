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
        },
        "attribution": {
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
        "patterns_detected": findings,
        "graph_summary": {
            "addresses": len(graph.get("nodes", [])),
            "transfers": len(graph.get("edges", [])),
            "max_depth_reached": result.get("depth_reached"),
            "truncated": result.get("truncated", False),
            "truncation_reasons": result.get("truncation_reasons", []),
        },
        "limitations": confidence_detail.get("caveats", []),
        "methodology": _methodology(native_symbol),
    }


def _methodology(native_symbol: str = "ETH") -> list[str]:
    """Plain description of what the tool did, so the result is reproducible."""
    return [
        f"Outgoing {native_symbol} transfers were followed from the reported "
        "address using breadth-first traversal, depth-limited, via a public "
        "blockchain data API.",
        "At each address, transfers were grouped by recipient and the "
        "highest-value destinations followed first; dust transfers below a "
        "minimum threshold were excluded as spam.",
        "Every address in the resulting graph was compared, by exact match, "
        "against a database of publicly labelled exchange wallets.",
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

    rule()
    add(f"{TOOL_NAME.upper()} - CRYPTOCURRENCY TRACE REPORT")
    rule()
    add(f"Case ID          : {case['case_id']}")
    add(f"Reported address : {case['reported_address']}")
    chain_line = case["chain"]
    if case.get("chain_id"):
        chain_line += f" (chainid {case['chain_id']})"
    add(f"Chain            : {chain_line}")
    add(f"Traced at        : {case['traced_at']}")
    add(f"Report generated : {report['generated_at']}")
    add("")

    rule("-")
    add("ATTRIBUTION")
    rule("-")
    if attribution["exchange"]:
        add(f"Exchange         : {attribution['exchange']}")
        add(f"Wallet           : {attribution['exchange_address']}")
        if attribution.get("exchange_wallet_label"):
            add(f"Wallet label     : {attribution['exchange_wallet_label']}")
        add(f"Hops from source : {attribution['hop_count']}")
        if attribution.get("value_received_native") is not None:
            add(f"Value received   : {attribution['value_received_native']} {symbol}")
    else:
        add("No known exchange wallet was reached within the traced depth.")
        add("This does not establish that the funds were not cashed out.")
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
        add("TRACE PATH (reported address -> exchange)")
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
