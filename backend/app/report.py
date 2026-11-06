"""Exportable case report for law-enforcement handoff.

The report is written for a reader who was not present when the trace ran and
who may not be technical. It therefore states, in order: what was reported,
what was found in one plain paragraph, exactly how confident the tool is and
why, the path the money took hop by hop with amounts and times, every pattern
with the thresholds it applied, every inferred attribution with its evidence
and the sentence that would confirm it, what the tool cannot tell you, and an
appendix of every address and transaction hash so that anything in the report
can be re-checked on a public explorer.

That last section is the point of the whole document. A trace names an
address, not a person; the record that links the two exists only at the
exchange, and the request that obtains it has to quote the exact address,
hashes, amounts and times. This report is the input to that request.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import config
from .evidence import seal_text
from .exchange_matcher import DEPOSIT_WALLET, is_deposit_label
from .models import Case
from .risk_matcher import freeze_parts, is_tether_usdt_freeze, list_freshness
from .scoring import BAND_THRESHOLDS, CAP_WORDING

REPORT_VERSION = "2.1"
TOOL_NAME = "Exchequer"


def _read_tool_version() -> str:
    """The code that produced the report, so a reader can check out exactly
    what ran. `git describe` where there is a checkout; in the Docker image
    there is no git, so the commit comes from the environment instead --
    EXCHEQUER_VERSION from the build, or the one Railway or Render sets. Falls back cleanly, because a report must never fail over its own
    footer."""
    baked = (
        os.getenv("EXCHEQUER_VERSION", "").strip()
        # Railway and Render inject the deployed commit; the short form is what a
        # reader would type into `git checkout`.
        or os.getenv("RAILWAY_GIT_COMMIT_SHA", "").strip()[:12]
        or os.getenv("RENDER_GIT_COMMIT", "").strip()[:12]
    )
    if baked:
        return baked
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=Path(__file__).resolve().parent, capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown (not a git checkout)"


# Read once. The code does not change while the process runs, and shelling out
# to git on every report is a subprocess in the request path for nothing.
_TOOL_VERSION = _read_tool_version()


def tool_version() -> str:
    return _TOOL_VERSION


# What a case holds about the address it reached decides what may be claimed about it.
LABELLED_DEPOSIT = "labelled_deposit"  # one customer: ask about that customer
INFERRED_DEPOSIT = "inferred_deposit"  # probably one customer: ask to confirm, then about them
EXCHANGE_WALLET = "exchange_wallet"    # the company's own: ask about the transactions, never KYC on it
EXPLORER_TAG = "explorer_tag"          # a third party's word: ask whether it is theirs first
TAG_WORDING = " (TronScan tag, read live)"  # tron_tags.py's label suffix


def attribution_kind(trace: dict[str, Any]) -> str:
    """What the case actually holds about the address it reached.

    The one place that reads this from a trace: when case contract v2 lands, this
    becomes a lookup of its attribution.kind and nothing else changes. A case that
    does not say gets the kind that assumes least: no single customer.
    """
    address = trace.get("exchange_address")
    if trace.get("attribution_inferred"):
        return INFERRED_DEPOSIT
    if any(found.get("address") == address for found in (trace.get("live_tags") or {}).get("found") or []):
        return EXPLORER_TAG
    match = next((m for m in trace.get("matches") or [] if m.get("address") == address), {})
    # Typed a deposit by an importer, and the label says so: older files typed
    # any label with "deposit" in it (an exchange's Deposit Funder) as one.
    deposit = match.get("wallet_type") == DEPOSIT_WALLET and is_deposit_label(match.get("label"))
    return LABELLED_DEPOSIT if deposit else EXCHANGE_WALLET


def _band_word(score: float | None) -> str:
    """'High', 'Moderate', 'Low' or 'Very low' for a score (R10): scoring.py's thresholds."""
    if score is None:
        return "n/a"
    return next((name for threshold, name in BAND_THRESHOLDS if score >= threshold), "very low").capitalize()


def _shown_label(label: str | None) -> str:
    """A label for a reader. "Read live" can be untrue: the tag may have come from cache."""
    return (label or "").replace(TAG_WORDING, " (TronScan tag)")


# India has one offset and no daylight saving, so this needs no time-zone
# database, and a report cannot fail for want of one.
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def _both_zones(moment: datetime) -> str:
    """'21:40 IST (16:10 UTC)' with its date; the UTC date only when it differs from India's."""
    ist, utc = moment.astimezone(IST), moment.astimezone(timezone.utc)
    utc_part = utc.strftime("%H:%M UTC") if utc.date() == ist.date() else utc.strftime("%Y-%m-%d %H:%M UTC")
    return f"{ist.strftime('%Y-%m-%d %H:%M')} IST ({utc_part})"


def _when(ts: int | None) -> str:
    if not ts:
        return "time unknown"
    return _both_zones(datetime.fromtimestamp(int(ts), tz=timezone.utc))


def _when_iso(value: str | None) -> str:
    """A stored ISO timestamp for a reader. One that cannot be read prints as it is, never guessed at."""
    if not value:
        return "time unknown"
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return _both_zones(moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc))


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
        "tool_version": tool_version(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "case": {
            "case_id": case.id,
            "reported_address": case.address,
            "traced_at": case.created_at,
            "chain": result.get("chain_name") or result.get("chain", "Ethereum Mainnet"),
            "chain_id": result.get("chain_id"),
            "asset": result.get("asset") or native_symbol,
            "native_currency": native_symbol,
            # The chain's own coin (ETH on a USDT trace), for balances and gas.
            "chain_currency": result.get("chain_native_symbol"),
            "block_explorer": result.get("explorer_url"),
            "direction": direction,
            "max_depth": result.get("max_depth"),
        },
        "summary": _summary(case, result),
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
            "kind": attribution_kind(result) if result.get("exchange") else None,
            "inferred": result.get("attribution_inferred", False),
            "inferred_deposit_addresses": result.get("inferred_deposits", []),
            "inference_notes": result.get("inference_notes", []),
            "hop_count": result.get("hop_count"),
            "value_received_native": result.get("value_received_native"),
            "prorata": result.get("prorata"),
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
        "risk_screening": {
            "screened": True,
            "categories": result.get("risk_flags", []),
            "matches": result.get("risk_matches", []),
            "notes": result.get("risk_notes", []),
        },
        "screening_lists": _screening_lists(case, result),
        "patterns_detected": findings,
        "swaps": result.get("swaps", []),
        "swap_notes": result.get("swap_notes", []),
        "follow_ons": [
            {
                "asset": f.get("asset"),
                "address": f.get("address"),
                "swap_tx": (f.get("swap") or {}).get("tx"),
                "amount_out": (f.get("swap") or {}).get("amount_out"),
                "max_depth": f.get("max_depth"),
                "error": f.get("error"),
                "exchange": (f.get("result") or {}).get("exchange"),
                "exchange_label": (f.get("result") or {}).get("exchange_label"),
                "exchange_address": (f.get("result") or {}).get("exchange_address"),
                "confidence": (f.get("result") or {}).get("confidence"),
                "hop_count": (f.get("result") or {}).get("hop_count"),
                "message": (f.get("result") or {}).get("message"),
                "trace_path": (f.get("result") or {}).get("trace_path", []),
                "risk_notes": (f.get("result") or {}).get("risk_notes", []),
                "manifest_hash": ((f.get("result") or {}).get("evidence") or {}).get("manifest_sha256"),
            }
            for f in result.get("follow_ons", [])
        ],
        "graph_summary": {
            "addresses": len(graph.get("nodes", [])),
            "transfers": len(graph.get("edges", [])),
            "individual_transactions": len(result.get("transfers", [])),
            "max_depth_reached": result.get("depth_reached"),
            "transfers_excluded_by_time": result.get("transfers_excluded_by_time"),
            "truncated": result.get("truncated", False),
            "truncation_reasons": result.get("truncation_reasons", []),
            "warnings": result.get("warnings", []),
        },
        "limitations": confidence_detail.get("caveats", []),
        "methodology": _methodology(native_symbol, direction)
        + ([
            f"{len(result['read_from_arrival'])} busy address(es) had more transfers since the "
            "traced funds arrived than one page of the data provider returns, so each was "
            "also read from the block of that arrival forward: "
            + ", ".join(result["read_from_arrival"][:10])
            + (" and others." if len(result["read_from_arrival"]) > 10 else ".")
        ] if result.get("read_from_arrival") else []),
        "appendix": {
            "addresses": [n.get("id") for n in graph.get("nodes", [])],
            "transactions": result.get("transfers", []),
        },
        # Every provider response the trace was computed from, hashed when it
        # arrived, and one hash over all of them. Absent on cases stored by an
        # earlier version.
        "evidence": result.get("evidence"),
        "live_tags": result.get("live_tags"),
    }


def _screening_lists(case: Case, result: dict[str, Any]) -> dict[str, Any] | None:
    """How old each list was when this case was traced; None if the chain is unknown here."""
    try:
        traced = datetime.fromisoformat(str(case.created_at).replace("Z", "+00:00")).date()
    except ValueError:
        traced = datetime.now(tz=timezone.utc).date()
    try:
        if "label_store" in result:  # recorded by the trace; an older case can only name today's
            return list_freshness(result.get("chain"), traced, store=result["label_store"])
        return list_freshness(result.get("chain"), traced)
    except config.UnknownChainError:
        return None


def _summary(case: Case, result: dict[str, Any]) -> str:
    """One paragraph in plain English: what was asked, what was found."""
    asset = result.get("asset") or result.get("native_symbol", "ETH")
    chain = result.get("chain_name") or result.get("chain", "Ethereum")
    direction = result.get("direction", "outgoing")
    nodes = len(result.get("graph", {}).get("nodes", []))
    hops = result.get("hop_count")
    exchange = result.get("exchange")
    flags = [f.replace("_", " ") for f in result.get("flags", [])]
    risk = result.get("risk_flags", [])
    swaps = [s for s in result.get("swaps", []) if s.get("output_read")]

    if direction == "outgoing":
        opening = (
            f"The {asset} sent out of the reported address {case.address} on {chain} was "
            f"followed across {nodes} addresses."
        )
    else:
        senders = len(result.get("direct_senders", []))
        opening = (
            f"The {asset} received by the reported address {case.address} on {chain} was "
            f"followed back to {senders} addresses that paid it directly, and {nodes} "
            f"addresses in all."
        )

    if exchange and result.get("attribution_inferred"):
        found = (
            f" The funds reached {result.get('exchange_address')}, which this tool infers "
            f"to be a {exchange} deposit address, {hops} hop{'s' if hops != 1 else ''} away; "
            f"that inference is explained below and only {exchange} can confirm it."
        )
    elif exchange and attribution_kind(result) == EXPLORER_TAG:
        plain = (result.get("exchange_label") or "").removesuffix(TAG_WORDING)
        distance = f"{hops} hop{'s' if hops != 1 else ''} {'away' if direction == 'outgoing' else 'upstream'}"
        found = (
            f" {'The funds reached' if direction == 'outgoing' else 'Part of the money came from'} "
            f"{result.get('exchange_address')}, which TronScan, the Tron block explorer, tags as "
            f"{plain}, {distance}; the tag is the explorer's and only {exchange} can confirm it."
        )
    elif exchange and attribution_kind(result) == LABELLED_DEPOSIT:
        distance = f"{hops} hop{'s' if hops != 1 else ''} {'away' if direction == 'outgoing' else 'upstream'}"
        found = (
            f" {'The funds reached' if direction == 'outgoing' else 'Part of the money came from'} "
            f"a deposit address publicly labelled as {exchange}'s ({result.get('exchange_label')}), {distance}."
        )
    elif exchange:
        found = (
            f" The funds reached a wallet that {exchange} publicly operates "
            f"({result.get('exchange_label')}), {hops} hop{'s' if hops != 1 else ''} away."
            if direction == "outgoing" else
            f" Part of the money came from a wallet that {exchange} publicly operates "
            f"({result.get('exchange_label')}), {hops} hop{'s' if hops != 1 else ''} upstream."
        )
    elif swaps:
        first = swaps[0]
        found = (
            f" No exchange was reached in {asset}: the funds were exchanged for "
            f"{first.get('asset_out')} at {first.get('router_label')}, and the trail in "
            f"{asset} ends there."
        )
    else:
        found = " No wallet in the trace matched a publicly known exchange."

    extra = ""
    if flags:
        extra += (
            f" The transfers matched the shape of {' and '.join(flags)}, which is a reason "
            f"to look closer and is not by itself evidence of an offence."
        )
    if "sanctioned" in risk:
        extra += " At least one address in the trace is on a published sanctions list."
    if "seized" in risk:
        extra += (
            " At least one address in the trace is named in a government seizure or "
            "forfeiture order, which is not a sanctions designation."
        )
    if "mixer" in risk:
        extra += " The trace stopped at a mixer, whose payouts cannot be linked to its deposits."
    frozen = [m for m in result.get("risk_matches") or [] if m.get("category") == "frozen"]
    if "frozen" in risk and frozen and all(is_tether_usdt_freeze(m) for m in frozen):
        extra += " At least one address in the trace has had its USDT frozen by Tether."
    elif "frozen" in risk:
        # Not every freeze is Tether's: the label store holds other issuers'.
        named = sorted({f"{token} by {issuer or 'its issuer'}"
                        for token, issuer in (freeze_parts(m) for m in frozen) if token})
        extra += (" At least one address in the trace has been frozen by its token's issuer"
                  + (f" ({'; '.join(named)})." if named else "."))
    if "reported" in risk:
        extra += (
            " TronScan, the Tron block explorer, carries a warning tag on at least one "
            "address in the trace."
        )
    if "stolen" in risk:
        extra += (
            " At least one address in the trace is tied by a published source to a known "
            "hack or exploit."
        )
    if "scam" in risk:
        extra += (
            " At least one address in the trace is named by a published scam or phishing "
            "list; a list's report is an accusation, not a finding."
        )
    if "poisoning" in risk:
        extra += (
            " At least one address in the trace is an address-poisoning lookalike found by "
            "on-chain detection."
        )
    if "laundering" in risk:
        extra += (
            " At least one address in the trace is named by a published source as moving "
            "illicit proceeds."
        )
    closing = (
        " An exchange wallet identifies where the money went, not who received it; "
        "only the exchange can link an address to a customer, on a lawful request."
        if exchange else ""
    )
    return opening + found + extra + closing


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
        timing = (
            "At every address after the reported one, only transfers made at "
            "or after the moment the traced funds arrived there were followed. "
            "Money cannot be forwarded before it is received, so anything the "
            "address sent earlier was left out of the graph."
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
        "against a database of publicly labelled exchange wallets. An unlabelled "
        "address whose every outgoing transfer went to one labelled exchange "
        "wallet was reported as a probable deposit address of that exchange, "
        "marked as an inference and scored lower than an exact match.",
        "Every address was also screened, by exact match, against the lists "
        "named under LISTS SCREENED AGAINST. A trace is stopped at any address "
        "identified as a mixer: its payouts come from a commingled pool, so "
        "transfers leaving it have no established link to the deposit traced.",
        "A transfer into a publicly labelled DEX router was recorded as a swap, "
        "with the asset returned to the sender read from the transaction "
        "receipt; the trace ends there and is not continued on the other asset.",
        "Laundering patterns were identified using fixed arithmetic rules "
        "(peel chain, amount split). Each finding records the thresholds it "
        "applied so it can be re-checked by hand.",
        "Confidence combines three weighted factors: proximity to the reported "
        "address (40%), how much of the value survived the route (35%), and "
        "how direct the exchange match was (25%).",
        "No machine learning or proprietary scoring is used. Every conclusion "
        "in this report can be reproduced from the transaction data listed in "
        "the appendix.",
    ]


def render_text_report(report: dict[str, Any]) -> str:
    """Human-readable plain-text version, suitable for printing or attaching."""
    out: list[str] = []
    add = out.append

    def rule(char: str = "=") -> None:
        add(char * 78)

    def section(title: str) -> None:
        rule("-")
        add(title)
        rule("-")

    def para(text: str, indent: str = "", bullet: str = "") -> None:
        for line in _wrap(_shown_label(text), indent=indent, bullet=bullet):
            add(line)

    case = report["case"]
    attribution = report["attribution"]
    confidence = report["confidence"]
    symbol = case.get("asset") or case.get("native_currency", "ETH")
    direction = case.get("direction", "outgoing")

    # -- header ----------------------------------------------------------------
    rule()
    add(f"{TOOL_NAME.upper()} - CRYPTOCURRENCY TRACE REPORT")
    rule()
    add(f"Case ID          : {case['case_id']}")
    add(f"Reported address : {case['reported_address']}")
    chain_line = case["chain"]
    if case.get("chain_id"):
        chain_line += f" (chainid {case['chain_id']})"
    add(f"Chain            : {chain_line}")
    add(f"Asset followed   : {symbol}")
    add("Direction        : "
        + ("outgoing (where the funds went)" if direction == "outgoing"
           else "incoming (who funded this address)"))
    add(f"Traced at        : {_when_iso(case['traced_at'])}")
    add(f"Report generated : {_when_iso(report['generated_at'])}")
    add(f"Tool version     : {TOOL_NAME} {report.get('tool_version', 'unknown')} "
        f"(report format v{report['report_version']})")
    if case.get("block_explorer"):
        add(f"Verify at        : {case['block_explorer']}")
    add("")
    screening_lists = report.get("screening_lists")
    if screening_lists and screening_lists.get("warning"):
        para(f"WARNING: {screening_lists['warning']}")
        add("")

    # -- summary ---------------------------------------------------------------
    section("SUMMARY")
    para(report.get("summary", ""))
    add("")

    # -- finding ---------------------------------------------------------------
    section("FINDING")
    if attribution.get("claim"):
        add(f"Claim            : {attribution['claim']}")
    if attribution["exchange"]:
        add(f"Exchange         : {attribution['exchange']}")
        add(f"Address          : {attribution['exchange_address']}")
        if attribution.get("exchange_wallet_label"):
            add(f"Address label    : {_shown_label(attribution['exchange_wallet_label'])}")
        basis = ("a TronScan tag, not confirmed by the exchange" if attribution.get("kind") == EXPLORER_TAG
                 else "exact match against a published exchange label")
        add("Basis            : "
            + ("INFERRED from the wallet's behaviour, not a label-file match"
               if attribution.get("inferred") else basis))
        add(f"Hops from source : {attribution['hop_count']}")
        prorata = attribution.get("prorata") or {}
        cap = prorata.get("seed_cap") or {}
        if direction == "outgoing" and prorata.get("status") == "estimated":
            if cap.get("applied"):
                # Never more than the victim paid, or than the swap returned.
                add(f"Likely arrived   : about {prorata['estimated']} of the {cap['amount']} {symbol} "
                    f"{CAP_WORDING.get(cap.get('basis'), 'the trace started from')} (pro-rata; the "
                    f"reported address sent {prorata['sent']} along this path)")
            else:
                add(f"Likely arrived   : about {prorata['estimated']} of {prorata['sent']} {symbol} "
                    "sent from the reported address (pro-rata)")
            add(f"Arrived in total : {prorata['arrived_total']} {symbol} along this path, "
                "including funds from other sources")
            for h in prorata.get("hops") or []:
                add(f"  via {h['address']}: traced funds {round(h['victim_share'] * 100, 1)}% "
                    f"of {h['received_in_window']} {symbol} received before it sent on")
        elif attribution.get("value_received_native") is not None:
            label = ("Arrived on path " if direction == "outgoing" else "Value sent      ")
            add(f"{label} : {attribution['value_received_native']} {symbol}"
                + (" (including any funds from other sources)" if direction == "outgoing" else ""))
            if prorata.get("status") == "unknown":
                add(f"Pro-rata         : not estimated -- {prorata.get('reason')}")
    elif direction == "outgoing":
        add("No known exchange wallet was reached within the traced depth.")
        add("This does not establish that the funds were not cashed out.")
    else:
        add("No known exchange wallet was found upstream within the traced depth.")
        add("This does not establish that the funds did not originate at one.")
    add("")

    # -- reverse trace: who funded it -------------------------------------------
    funders = report.get("funding_sources") or []
    if direction == "incoming" and funders:
        section("ADDRESSES THAT FUNDED THE REPORTED ADDRESS")
        para(
            "Each address below sent funds directly to the reported address. "
            "Where the reported address belongs to an offender, these senders "
            "are candidate victims of the same operation and may each hold a "
            "separate complaint. This list states only what the transactions "
            "show: a sender may equally be the offender's own wallet, an "
            "exchange withdrawal, or an unrelated payment."
        )
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

    # -- confidence ------------------------------------------------------------
    section("CONFIDENCE")
    score = confidence.get("score")
    # R10: lead with the band. The score stays here, beside how it was reached,
    # and nowhere else: it is a rule of three inputs, not a probability.
    add(f"Band             : {(confidence.get('band') or 'n/a').capitalize()}")
    add(f"Score            : {score if score is not None else 'n/a'}"
        "  (a rule of three inputs, not a probability; read the band)")
    if confidence.get("summary"):
        add("")
        para(confidence["summary"])
    if confidence.get("components"):
        add("")
        add("How this score was reached:")
        for component in confidence["components"]:
            add(f"  - {component['name']} "
                f"(raw {component['raw_value']} x weight {component['weight']} "
                f"= {component['contribution']})")
            para(component["explanation"], indent="      ")
    add("")

    # -- path ------------------------------------------------------------------
    if report.get("trace_path"):
        section("PATH THE MONEY TOOK" + (" (reported address -> exchange)" if direction == "outgoing"
                                          else " (exchange -> reported address)"))
        for i, step in enumerate(report["trace_path"]):
            label = f"  [{_shown_label(step['label'])}]" if step.get("label") else ""
            if i == 0:
                add(f"  1. {step['address']}{label}")
                continue
            amount = step.get("value_native")
            add(f"     sent {amount} {symbol}"
                + (f" in {step['tx_count']} transfers" if step.get("tx_count", 0) > 1 else ""))
            if step.get("first_seen"):
                if step.get("last_seen") and step["last_seen"] != step["first_seen"]:
                    add(f"       between {_when(step['first_seen'])}")
                    add(f"       and {_when(step['last_seen'])}")
                else:
                    add(f"       on {_when(step['first_seen'])}")
            add("     to")
            add(f"  {i + 1}. {step['address']}{label}")
            for h in (step.get("tx_hashes") or [])[:5]:
                add(f"        tx {h}")
        add("")

    # -- inferred attributions --------------------------------------------------
    inferred = attribution.get("inferred_deposit_addresses") or []
    if inferred:
        section("INFERRED DEPOSIT ADDRESSES")
        para(
            "The addresses below are not in any label file. Each is called a "
            "probable exchange deposit address because of what it did with "
            "money, and the evidence is listed so it can be checked on a "
            "public explorer. An inference scores lower than a label match."
        )
        add("")
        for note in attribution.get("inference_notes") or []:
            para(note, bullet="* ")
            add("")
        for m in inferred:
            e = m.get("evidence") or {}
            add(f"  {m['address']}")
            add(f"    exchange            : {m['exchange']}")
            add(f"    outgoing transfers  : {e.get('sweep_count')}, all to {e.get('sweep_destination')}")
            add(f"    destination label   : {e.get('sweep_destination_label')}")
            add(f"    total swept         : {e.get('total_swept_native')} {symbol}")
            if e.get("first_sweep"):
                add(f"    sweeps between      : {_when(e.get('first_sweep'))}")
                add(f"                      and {_when(e.get('last_sweep'))}")
            if e.get("current_balance_native") is not None:
                # The chain's coin, not the traced asset (older cases did not say which).
                balance_unit = e.get("current_balance_symbol") or case.get("chain_currency") or symbol
                add(f"    current balance     : {e.get('current_balance_native')} {balance_unit}")
            add(f"    thresholds applied  : {e.get('thresholds_applied')}")
            add("")

    # -- screening -------------------------------------------------------------
    screening = report.get("risk_screening") or {}
    section("SANCTIONS, MIXER, FREEZE AND STOLEN-FUNDS SCREENING")
    if screening.get("matches"):
        for note in screening.get("notes", []):
            para(note, bullet="* ")
            add("")
    else:
        add("No address in this trace appeared on the screened lists.")
        add("Screening is an exact match against the lists named in the next")
        add("section; an address absent from them is not thereby established")
        add("as legitimate.")
        add("")

    # -- lists -----------------------------------------------------------------
    section("LISTS SCREENED AGAINST")
    if screening_lists:
        para("The lists this server held when this report was generated, compared "
             f"with {screening_lists['as_of']} (UTC), the day this case was traced. A date "
             "is when the list was last checked against its source.")
        add("")
        for entry in screening_lists.get("lists") or []:
            para(entry["name"], indent="  ")
            add(f"    {entry['file']}: checked {entry['checked'] or 'no date recorded'}"
                + (f", published {entry['published']}" if entry.get("published") else ""))
            if entry.get("note"):
                para(entry["note"], indent="    ")
        if screening_lists.get("not_held"):
            add("")
            para(f"Not loaded for this chain, so not screened: {', '.join(screening_lists['not_held'])}.")
    else:
        add("The lists for this chain could not be determined.")
    add("")

    # -- patterns --------------------------------------------------------------
    section("LAUNDERING PATTERNS DETECTED")
    if report.get("patterns_detected"):
        para(
            "A pattern is a fixed arithmetic shape, and the same shapes occur in "
            "ordinary activity: measured on real wallets, the amount-split rule "
            "fires within three hops of about one in nine ordinary high-volume "
            "wallets. Read each as a reason to look closer, not as a verdict."
        )
        add("")
        for finding in report["patterns_detected"]:
            add(f"* {finding['pattern'].replace('_', ' ').upper()} "
                f"(strength {finding.get('strength')})")
            para(finding["description"], indent="  ")
            thresholds = (finding.get("evidence") or {}).get("thresholds_applied") or {}
            if thresholds:
                add("  Thresholds applied:")
                for name, value in thresholds.items():
                    add(f"    {name:<26} {value}")
            add("")
    else:
        add("None. The traced transfers did not match the peel-chain or")
        add("amount-split rules.")
        add("")

    # -- swaps -----------------------------------------------------------------
    if report.get("swap_notes"):
        section("SWAPS (THE TRACE CHANGES ASSET HERE)")
        for note in report["swap_notes"]:
            para(note, bullet="* ")
            add("")

    # -- follow-on traces ----------------------------------------------------------
    if report.get("follow_ons"):
        section("FOLLOW-ON TRACES (THE MONEY AFTER A SWAP)")
        para(
            "Each trace below starts at a swap found above, in the asset the swap "
            "returned, from the wallet that swapped, and follows only what that "
            "wallet sent at or after the swap. It is scored within its own asset; "
            "its amounts are never added to the trace above."
        )
        add("")
        for f in report["follow_ons"]:
            add(f"* {f['asset']} from {f['address']} (swap tx {f.get('swap_tx')}, "
                f"up to {f.get('max_depth')} hops)")
            if f.get("amount_out") is not None:
                add(f"    swap returned       : {f['amount_out']:,.4f} {f['asset']}")
            if f.get("error"):
                add(f"    not traced          : {f['error']}")
            elif f.get("exchange"):
                add(f"    reached             : {f['exchange']} ({f['exchange_label']}) "
                    f"{f['exchange_address']}")
                add(f"    hops / confidence   : {f['hop_count']} / {_band_word(f['confidence'])}")
            else:
                para(f.get("message") or "No exchange was reached.", indent="    ")
            for step in (f.get("trace_path") or [])[1:]:
                named = f" ({_shown_label(step['label'])})" if step.get("label") else ""
                add(f"    hop {step.get('depth')}               : {step.get('address')}{named} "
                    f"received {step.get('value_native', 0):,.4f} {f['asset']}")
            for note in f.get("risk_notes") or []:
                para(note, indent="    ", bullet="! ")
            if f.get("manifest_hash"):
                add(f"    evidence manifest   : {f['manifest_hash']}")
            add("")

    # -- scope -----------------------------------------------------------------
    summary = report["graph_summary"]
    section("TRACE SCOPE")
    live = report.get("live_tags")
    if live is not None:
        if live.get("enabled"):
            add(f"TronScan tags read live    : {live.get('asked', 0)} unlabelled wallets asked, "
                f"{len(live.get('found') or [])} tagged as an exchange, "
                f"{len(live.get('warnings') or [])} carrying a TronScan warning")
            if live.get("asked") and live.get("requests") == 0:
                para("All were answered from this server's cache, not a fresh request. "
                     "When each was first read is in Appendix C.", indent="  ")
            for f in live.get("found") or []:
                add(f"  - {f['address']} {_shown_label(f['label'])}")
            for w in live.get("warnings") or []:
                add(f"  ! {w['address']} warning tag \u201c{w['warning']}\u201d")
        else:
            add("TronScan tags read live    : off (no TRONSCAN_API_KEY configured)")
    add(f"Addresses examined         : {summary['addresses']}")
    add(f"Transfers (aggregated)     : {summary['transfers']}")
    if summary.get("individual_transactions"):
        add(f"Individual transactions    : {summary['individual_transactions']}")
    add(f"Depth reached              : {summary['max_depth_reached']}")
    if summary.get("transfers_excluded_by_time") is not None:
        add(f"Excluded by the time rule  : {summary['transfers_excluded_by_time']}")
    add(f"Truncated                  : {'yes' if summary['truncated'] else 'no'}")
    for reason in summary.get("truncation_reasons", []):
        add(f"  - {reason}")
    for warning in summary.get("warnings", []):
        para(warning, indent="  ", bullet="! ")
    add("")

    # -- limitations and method ---------------------------------------------------
    section("LIMITATIONS")
    for item in report.get("limitations", []):
        para(item, bullet="- ")
    add("")

    section("METHODOLOGY")
    for item in report["methodology"]:
        para(item, bullet="- ")
    add("")

    # -- appendix --------------------------------------------------------------
    appendix = report.get("appendix") or {}
    section("APPENDIX A - EVERY ADDRESS IN THE TRACE")
    for address in appendix.get("addresses", []):
        add(f"  {address}")
    add("")
    section("APPENDIX B - EVERY TRANSACTION IN THE TRACE")
    transactions = appendix.get("transactions") or []
    if transactions:
        add("Each hash can be opened on the block explorer named in the header.")
        add("")
        para(f"Each gives its time, then its value in {symbol} and from -> to "
             "(i = moved by a contract call), then its hash.")
        add("-" * 78)
        for tx in transactions:
            flag = "i" if tx.get("internal") else " "
            add(_when(tx.get("timestamp")))
            add(f"{tx.get('value_native', 0):>16,.4f} {flag} "
                f"{(tx.get('from') or '')[:10]}.. -> {(tx.get('to') or '')[:10]}..")
            add(f"    {tx.get('hash')}")
    else:
        add("Individual transaction hashes were not stored with this case (it was")
        add("traced by an earlier version). Re-run the trace to obtain them.")
    add("")

    # -- evidence manifest -----------------------------------------------------
    evidence = report.get("evidence")
    section("APPENDIX C - EVIDENCE MANIFEST")
    if evidence and evidence.get("records"):
        para("Every provider response this trace was computed from was hashed "
             "(SHA-256) at the moment it arrived, with the request that produced "
             "it and the UTC time. A reviewer who re-issues a request and obtains "
             "the same hash has confirmed the input was unchanged; a different "
             "hash means the chain, or the provider, has moved on since. "
             "Responses marked 'cached' re-used bytes retrieved earlier in the "
             "same process and carry that earlier time.")
        add("")
        add(f"Responses       : {evidence['count']} "
            f"({evidence['retrieved']} retrieved, {evidence['from_cache']} cached)")
        add(f"Providers       : {', '.join(evidence.get('providers') or [])}")
        add(f"Retrieved       : {evidence.get('first_retrieved_at')} to "
            f"{evidence.get('last_retrieved_at')}")
        add(f"Manifest SHA-256: {evidence['manifest_sha256']}")
        add("  (SHA-256 over the sorted lines '<sha256>  <provider>  <request>')")
        add("")
        for i, rec in enumerate(evidence["records"], 1):
            cached = "  cached" if rec.get("from_cache") else ""
            add(f"[{i:>3}] {rec['retrieved_at']}  {rec['provider']}  {rec['bytes']} bytes{cached}")
            add(f"      {rec['request']}")
            add(f"      sha256 {rec['sha256']}")
    else:
        add("No evidence manifest was stored with this case (it was traced by an")
        add("earlier version). Re-run the trace to obtain one.")
    add("")

    rule()
    add(f"Generated by {TOOL_NAME} {report.get('tool_version', '')} "
        f"(report format v{report['report_version']}).")
    add("Automated analysis of public blockchain data. Findings should be")
    add("independently verified before use in legal proceedings.")
    rule()

    # The report's own hash goes last, over every byte above it, so the
    # document that leaves this tool can be checked against the document that
    # reaches a court.
    return seal_text("\n".join(out))


def _wrap(text: str, width: int = 78, indent: str = "", bullet: str = "") -> list[str]:
    """Wrap `text` to `width`, honouring an optional bullet and indent."""
    import textwrap

    prefix = indent + bullet
    subsequent = indent + (" " * len(bullet))
    return textwrap.wrap(text, width=width, initial_indent=prefix,
                         subsequent_indent=subsequent) or [prefix.rstrip()]
