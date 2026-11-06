"""Draft request letters from a stored case.

A trace ends where an investigator's next step begins: a written request to
the exchange that holds the account, and, where USDT is involved, to Tether,
which can say why it froze an address and can freeze another. This module
turns a case into the first draft of those letters, filled with the facts the
case already holds -- the address to ask about, every hop with its amounts,
times and transaction hashes, and the evidence hash that ties the letter to
the sealed report.

It drafts; it does not decide. Everything that is the officer's to supply is
left as a marked blank: who is writing, the case and FIR reference, the victim's
payments, and the legal provision the request is issued under. The tool suggests
a provision in brackets and never asserts one, because which power applies
depends on the case, the authority and the stage of the investigation.

What an exchange letter may ask depends on what the case holds about the address
(report.attribution_kind): about the customer behind a labelled deposit address;
whether an inferred one is theirs, then about the customer; about the accounts
behind the listed transactions for a wallet the exchange runs itself, never KYC
on the wallet; and, for an explorer's tag, only whether the address is theirs.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from typing import Any

from . import config
from .report import (EXCHANGE_WALLET, EXPLORER_TAG, INFERRED_DEPOSIT, IST, LABELLED_DEPOSIT, TAG_WORDING,
                     _when, _when_iso, attribution_kind)
from .risk_matcher import _list_meta

EXCHANGE = "exchange"
TETHER = "tether"
LETTERS = (EXCHANGE, TETHER)

BLANK = "[____________________]"
USDT_CHAINS = {"ethereum", "tron"}  # where USDT is Tether's own contract, with a blacklist

COMPANY_WALLET_KINDS = {EXCHANGE_WALLET, EXPLORER_TAG}  # the transaction list is the question


class LetterNotApplicable(ValueError):
    """The case holds nothing this letter could ask about."""


def _attribution(result: dict[str, Any]) -> dict[str, Any] | None:
    """The trace (original or follow-on) that reached an exchange, if any.

    `route` is a follow-on's path from the reported address to the swapping
    wallet, in the original asset; None for a case stored before it was kept."""
    if result.get("exchange"):
        return {"trace": result, "asset": result.get("asset"), "via_swap": None, "route": None}
    for follow in result.get("follow_ons") or []:
        found = follow.get("result") or {}
        if found.get("exchange"):
            return {"trace": found, "asset": follow.get("asset"), "via_swap": follow.get("swap"),
                    "route": follow.get("route")}
    return None


METHOD_NAME = {"fifo": "FIFO", "libr": "LIBR", "prorata": "pro-rata"}


def _letter_amount(result: dict[str, Any], found: dict[str, Any]) -> dict[str, Any] | None:
    """The one amount a letter states, or None when the case has none.

    The smallest figure the tracing rules gave (estimates.conservative, which
    the case view promises is what a letter states), else the pro-rata
    estimate; never more than the victim reported paying (an intake trace) or
    than the swap returned (a follow-on), whatever an older stored case holds.
    """
    trace = found["trace"]
    prorata = trace.get("prorata") or {}
    methods = trace.get("tracing_methods") or {}
    amount = (trace.get("estimates") or {}).get("conservative")
    method = methods.get("conservative_method") if amount is not None else None
    if amount is None and methods.get("conservative") is not None:
        amount, method = methods["conservative"], methods.get("conservative_method")
    if amount is None and prorata.get("status") == "estimated":
        amount, method = prorata["estimated"], "prorata"
    if amount is None:
        return None
    swap = found["via_swap"]
    cap, basis = None, None
    if swap and swap.get("amount_out") is not None:
        cap, basis = float(swap["amount_out"]), "swap_output"
    elif not swap and result.get("reported_amount"):
        cap, basis = float(result["reported_amount"]), "reported_amount"
    rng = methods.get("range") if methods.get("range") and methods["range"]["low"] != methods["range"]["high"] else None
    return {"amount": min(float(amount), cap) if cap is not None else float(amount),
            "method": method or "prorata", "range": rng, "cap": cap, "basis": basis,
            "arrived": prorata.get("arrived_total") if prorata.get("status") == "estimated" else None}


def _amount_lines(asset: str, stated: dict[str, Any]) -> list[str]:
    """The letter's amount paragraph, worded for what the figure is."""
    x = f"{stated['amount']:,.6f}"
    how = (f" (by {METHOD_NAME.get(stated['method'], stated['method'])}, the smallest of the tracing rules "
           f"applied; they give {stated['range']['low']:,.6f} to {stated['range']['high']:,.6f})"
           if stated["range"] else "")
    lead = "On a pro-rata estimate" if stated["method"] == "prorata" else "On an estimate"
    if stated["basis"] == "swap_output":
        text = (f"{lead} from the public records, of the {stated['cap']:,.6f} {asset} the swap returned, "
                f"about {x} {asset}{how} reached this address")
    elif stated["basis"] == "reported_amount":
        text = (f"{lead} from the public records, about {x} of the {stated['cap']:,.6f} {asset} the victim "
                f"reported paying{how} reached this address")
    else:
        # Address-only: the start is everything the reported wallet sent.
        text = (f"{lead} from the public records, about {x} {asset}{how} of everything the reported address "
                "sent along this route reached this address. That figure can include other people's money, "
                "not only the complainant's")
    arrived = stated["arrived"]
    if arrived is not None and arrived - stated["amount"] > stated["amount"] * 0.05:
        rest = ("came from other sources" if stated["method"] == "prorata" and not stated["cap"]
                else "is not counted in that figure")
        text += (f" ({arrived:,.6f} {asset} arrived along this path in total; about "
                 f"{arrived - stated['amount']:,.6f} {rest})")
    return ["", *textwrap.wrap(text + ".", width=95, initial_indent="   ", subsequent_indent="   ",
                               break_long_words=False, break_on_hyphens=False),
            "   This is an estimate; your own records of the deposits are authoritative."]


def _all_traces(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [result] + [f["result"] for f in result.get("follow_ons") or [] if f.get("result")]


def _frozen(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for t in _all_traces(result) for m in t.get("risk_matches") or [] if m.get("category") == "frozen"]


def _usdt_traces(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in _all_traces(result) if t.get("asset") == "USDT" and t.get("chain") in USDT_CHAINS]


def available(result: dict[str, Any]) -> list[dict[str, str]]:
    """Which letters this case can support, for the interface to offer."""
    out = []
    found = _attribution(result)
    if found and result.get("direction", "outgoing") == "outgoing":
        out.append({"to": EXCHANGE, "title": f"Request to {found['trace']['exchange']}"})
    if _frozen(result) or _usdt_traces(result):
        out.append({"to": TETHER, "title": "Request to Tether"})
    return out


def _opening(result: dict[str, Any]) -> list[str]:
    """Only what the case holds: an address. Who reported it, and what they paid, the officer states."""
    return [
        "1. This office is investigating a complaint of cyber-enabled financial fraud. The wallet",
        f"   address {result.get('address')} was reported in connection with it.",
        f"   The victim's payments: {BLANK} (officer to state amounts, dates and references",
        "   from the complaint).",
    ]


def _label_source(trace: dict[str, Any]) -> str:
    """Where a label came from and when, so a reader can weigh it."""
    meta = None
    if trace.get("chain"):
        try:
            meta = _list_meta(config.get_chain(trace["chain"]).labels_path)
        except config.UnknownChainError:
            pass
    checked = (meta or {}).get("last_reviewed")
    return f"Exchequer's exchange label list{f', last checked {checked}' if checked else ''}"


def _plain_label(label: str | None) -> str:
    return (label or "").removesuffix(TAG_WORDING)


def _claim(kind: str, trace: dict[str, Any], exchange: str) -> str:
    """Paragraph 2's statement about the address: what is known, and how."""
    label = _plain_label(trace.get("exchange_label"))
    if kind == INFERRED_DEPOSIT:
        return f"which we have reason to believe is a deposit address issued by {exchange}."
    if kind == EXPLORER_TAG:
        return (f"which TronScan, the Tron block explorer, tags as “{label}”.\n"
                "   That tag is the explorer's: this office has not confirmed it. When it was read is\n"
                "   recorded in the attached report's evidence manifest.")
    source = f"(label: {label}; {_label_source(trace)})."
    if kind == LABELLED_DEPOSIT:
        return f"which is publicly labelled as a deposit address of {exchange}\n   {source}"
    return (f"which is publicly labelled as a wallet {exchange} operates itself\n   {source} "
            "We understand it does not belong to any one customer.")


def _requests(kind: str, exchange: str, address: str) -> list[str]:
    """What this letter may ask, given what the case holds about the address."""
    if kind == EXPLORER_TAG:
        return [
            f"   you are requested to confirm whether {address} is controlled by {exchange}.",
            "   If it is, please say so in writing, name the channel for a further request about the",
            "   transactions in paragraph 3, and preserve the records of any accounts connected with",
            "   them. If it is not, please say so, so that this office can correct its records.",
        ]
    if kind == EXCHANGE_WALLET:
        return [
            "   you are requested to identify the customer account or accounts behind each transaction",
            "   listed in paragraph 3, and their holders, and to furnish for each such account:",
            "   (a) the account statement and all deposits and withdrawals, with transaction hashes,",
            "       from the date of the first transfer above to date;",
            "   (b) linked bank accounts, UPI identifiers and cards used for fiat deposits or withdrawals;",
            "   (c) login records with IP addresses and device identifiers.",
            f"   This request is not about the wallet {address} itself.",
            "",
            "5. You are further requested to preserve all records relating to those accounts and to",
            f"   consider restricting withdrawals from them pending this investigation {BLANK}.",
        ]
    ask = (f"   you are requested to confirm whether {address} is a deposit address you issued and,\n"
           f"   if it is, to furnish in respect of the account(s) associated with it:"
           if kind == INFERRED_DEPOSIT else
           f"   you are requested to furnish, in respect of the account(s) associated with {address}:")
    return [
        ask,
        "   (a) the account holder's identity and KYC documents;",
        "   (b) the account statement and all deposits and withdrawals, with transaction hashes,",
        "       from the date of the first transfer above to date;",
        "   (c) linked bank accounts, UPI identifiers and cards used for fiat deposits or withdrawals;",
        "   (d) login records with IP addresses and device identifiers;",
        "   (e) any other deposit addresses issued to the same account.",
        "",
        "5. You are further requested to preserve all records relating to this account and to",
        f"   consider restricting withdrawals from it pending this investigation {BLANK}.",
    ]


def _transfers_into(trace: dict[str, Any], address: str) -> list[dict[str, Any]]:
    into = [t for t in trace.get("transfers") or [] if t.get("to") == address]
    return sorted(into, key=lambda t: t.get("timestamp") or 0)


def _path_lines(trace: dict[str, Any], asset: str, *, list_all: bool = False, leave_out: str | None = None) -> list[str]:
    """Each hop. `leave_out` drops hashes listed separately; `list_all` lifts the limit of ten."""
    lines = []
    for step in (trace.get("trace_path") or [])[1:]:
        label = _plain_label(step.get("label"))
        named = f" ({label})" if label else ""
        lines.append(
            f"  Hop {step.get('depth')}: {step.get('address')}{named}\n"
            f"         received {step.get('value_native', 0):,.6f} {asset} in "
            f"{step.get('tx_count', 0)} transfer(s), {_when(step.get('first_seen'))}"
            + (f"\n         to {_when(step.get('last_seen'))}" if step.get("last_seen") != step.get("first_seen") else "")
        )
        if step.get("address") == leave_out:
            continue
        hashes = step.get("tx_hashes") or []
        shown = hashes if list_all else hashes[:10]
        for tx in shown:
            lines.append(f"         tx {tx}")
        if (step.get("tx_count") or 0) > len(shown):
            lines.append(f"         (first {len(shown)} of {step.get('tx_count')} transfers shown; "
                         "all are listed in the attached report)")
    return lines


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _header(case_id: str, result: dict[str, Any], to_line: str, subject: str) -> list[str]:
    today = _utc_now().astimezone(IST).strftime("%d %B %Y")  # the officer's date, whatever the server's clock says
    manifest = (result.get("evidence") or {}).get("manifest_sha256")
    return [
        "DRAFT — for the investigating officer to review, complete and sign.",
        "Generated by Exchequer from a stored case. Nothing below has been sent.",
        "",
        f"From      : {BLANK} (name, rank, unit, official e-mail and phone)",
        f"Reference : {BLANK} (FIR / complaint / NCRP acknowledgement number)",
        f"Date      : {today}",
        f"To        : {to_line}",
        "",
        f"Subject   : {subject}",
        "",
        f"Exchequer case {case_id}, traced {_when_iso(result.get('created_at'))},",
        f"{result.get('chain_name')} · asset {result.get('asset')} · reported address {result.get('address')}.",
        (f"Evidence manifest SHA-256: {manifest}" if manifest else
         "This case was stored before evidence hashing; the report says so."),
        "",
    ]


def _exchange_letter(case_id: str, result: dict[str, Any]) -> str:
    found = _attribution(result)
    if not found or result.get("direction", "outgoing") != "outgoing":
        raise LetterNotApplicable("This case reached no exchange, so there is no exchange to write to.")
    trace, asset = found["trace"], found["asset"]
    exchange, address = trace["exchange"], trace["exchange_address"]
    kind = attribution_kind(trace)
    swap = found["via_swap"]
    chain_name = result.get("chain_name")
    subjects = {
        LABELLED_DEPOSIT: f"Request for account information relating to deposit address {address} ({chain_name})",
        INFERRED_DEPOSIT: f"Request to confirm, and for account information on, suspected deposit address {address} ({chain_name})",
        EXCHANGE_WALLET: f"Request to identify the accounts behind transactions into wallet {address} ({chain_name})",
        EXPLORER_TAG: f"Request to confirm whether address {address} is controlled by {exchange} ({chain_name})",
    }

    lines = _header(
        case_id, result,
        f"{exchange} — Law Enforcement / Compliance team {BLANK} (officer to find and confirm the right channel)",
        subjects[kind],
    )
    sender = (swap or {}).get("sender")
    moved = (f"{swap.get('asset_in')} moving from that address and, after a swap at\n"
             f"   {swap.get('router_label')} (tx {swap.get('tx')}),\n"
             f"   {asset} moving from {'it' if sender == result.get('address') else sender} to the address"
             if swap else f"{asset} moving from that address to the address")
    lines += [
        *_opening(result),
        "",
        f"2. Public blockchain records show {moved}",
        f"   {address}, {_claim(kind, trace, exchange)}",
    ]
    if kind == INFERRED_DEPOSIT:
        dep = next((m for m in trace.get("inferred_deposits") or [] if m.get("address") == address), {})
        ev = dep.get("evidence") or {}
        lines += [
            f"   Every outgoing transfer from it ({ev.get('sweep_count', '?')} in all) went to {exchange}'s",
            f"   labelled wallet {ev.get('sweep_destination_label', '')} {ev.get('sweep_destination', '')},",
            "   the pattern of an exchange sweeping a customer deposit address. This is an inference",
            f"   from public records, which only {exchange} can confirm.",
        ]
    if swap:
        returned = (f"{swap['amount_out']:,.6f} {asset}" if swap.get("amount_out") is not None else asset)
        lines += [
            "",
            f"   On the way, {sender} exchanged {swap.get('amount_in', 0):,.6f} {swap.get('asset_in')}",
            f"   for {returned} at {swap.get('router_label')} (tx {swap.get('tx')}); the {asset} was followed",
            "   from that swap.",
        ]
    stated = _letter_amount(result, found)
    if stated is not None:
        lines += _amount_lines(asset, stated)
    listed = _transfers_into(trace, address) if kind in COMPANY_WALLET_KINDS else []
    path = _path_lines(trace, asset, list_all=kind in COMPANY_WALLET_KINDS, leave_out=address if listed else None)
    lines += ["", "3. The transfers, hop by hop:", f"  Reported address: {result.get('address')}"]
    if swap:
        # The reported address's own route to the swap, in the asset it sent;
        # then the follow-on from the swapping wallet, in the asset it became.
        if sender != result.get("address"):
            lines += (_path_lines({"trace_path": found["route"]}, swap.get("asset_in") or "") if found["route"]
                      else ["  Route to the swapping wallet: see the attached report"])
        lines.append(f"  Swapping wallet (follow-on start): {sender}"
                     + (" (the reported address itself)" if sender == result.get("address") else ""))
    lines += path
    if listed:
        lines += ["", f"   Every transfer into {address} in this trace:"]
        for transfer in listed:
            lines += [f"     {transfer.get('value_native', 0):,.6f} {asset}, {_when(transfer.get('timestamp'))}",
                      f"       tx {transfer.get('hash')}"]
    lines += ["", f"4. In exercise of the powers under {BLANK}",
              "   [e.g. Section 94 of the Bharatiya Nagarik Suraksha Sanhita, 2023, and/or the",
              "   provisions of the PMLA, 2002 applicable to this investigation — officer to confirm],",
              *_requests(kind, exchange, address), ""]
    lines += [
        f"{6 if kind != EXPLORER_TAG else 5}. This request identifies an address, not a person. The attached Exchequer report sets",
        "   out every address and transaction relied on, so each can be verified independently on",
        "   a public block explorer.",
        "",
        "Attachment: Exchequer report for case " + case_id + " (text), with evidence manifest.",
        "",
        f"{BLANK}",
        "(signature, name, designation, seal)",
    ]
    return "\n".join(lines) + "\n"


def _tether_letter(case_id: str, result: dict[str, Any]) -> str:
    frozen = _frozen(result)
    usdt = _usdt_traces(result)
    if not frozen and not usdt:
        raise LetterNotApplicable("This case involves no USDT on Ethereum or Tron and no Tether-frozen address.")

    lines = _header(
        case_id, result,
        f"Tether Operations Limited — law-enforcement requests team {BLANK} (officer to find and confirm the right channel)",
        "Request for information and preservation relating to USDT addresses in a fraud investigation",
    )
    lines += [*_opening(result), ""]
    n = 2
    if frozen:
        lines += [f"{n}. The following addresses in the traced funds are recorded on the USDT contract as",
                  "   frozen by Tether (AddedBlackList events):"]
        for m in frozen:
            lines += [f"   - {m.get('address')} — {m.get('label')}", f"     {m.get('source')}"]
        lines += ["", "   You are requested to state, to the extent you are able, the basis of each freeze and",
                  "   any information held on the parties associated with these addresses.", ""]
        n += 1
    for trace in usdt:
        found = trace.get("exchange")
        lines += [f"{n}. USDT on {trace.get('chain_name')} moved from {trace.get('address')} as follows:",
                  *_path_lines(trace, "USDT")]
        if found:
            lines.append(f"   It reached {found} at {trace.get('exchange_address')}.")
        lines.append("")
        n += 1
    lines += [
        f"{n}. In exercise of the powers under {BLANK}",
        "   [officer to state the provision and, if applicable, the mutual legal assistance route],",
        "   you are requested to preserve all records relating to the addresses above and to",
        f"   consider freezing USDT held at {BLANK} (addresses the officer confirms) pending this",
        "   investigation.",
        "",
        "Attachment: Exchequer report for case " + case_id + " (text), with evidence manifest.",
        "",
        f"{BLANK}",
        "(signature, name, designation, seal)",
    ]
    return "\n".join(lines) + "\n"


def draft(case_id: str, result: dict[str, Any], to: str) -> str:
    if to == EXCHANGE:
        return _exchange_letter(case_id, result)
    if to == TETHER:
        return _tether_letter(case_id, result)
    raise ValueError(f"Unknown letter '{to}'. Expected one of: {', '.join(LETTERS)}.")
