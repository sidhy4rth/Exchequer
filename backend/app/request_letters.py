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

Before either, the urgent freeze letter: "hold these funds now, pending a
formal request", to the exchange and to Tether. It is sent first, so it holds
only what the recipient needs to act -- the wallets, the hashes with their
times, the chain and token, and the one amount the information letter states
-- and no narrative. Every letter says it is not valid until an officer signs
it on official letterhead, so an unsigned draft cannot pass as a police request.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from typing import Any

from . import config, provenance
from .case_privacy import WITHHELD
from .display_text import one_line, short
from .report import (EXCHANGE_WALLET, EXPLORER_TAG, INFERRED_DEPOSIT, IST, LABELLED_DEPOSIT, TAG_WORDING,
                     _amount, _paid_at, _when, _when_iso, also_reached, also_reached_line, attribution_kind)
from .risk_matcher import _list_meta, is_tether_usdt_freeze

EXCHANGE = "exchange"
TETHER = "tether"
EXCHANGE_FREEZE = "exchange-freeze"  # urgent: hold the funds now, pending a formal request
TETHER_FREEZE = "tether-freeze"
LETTERS = (EXCHANGE_FREEZE, TETHER_FREEZE, EXCHANGE, TETHER)  # the freeze letters first: they go first

NOT_VALID = "This is a DRAFT. It is not valid until an officer signs it on official letterhead."

BLANK = "[____________________]"
USDT_CHAINS = {"ethereum", "tron"}  # where USDT is Tether's own contract, with a blacklist

COMPANY_WALLET_KINDS = {EXCHANGE_WALLET, EXPLORER_TAG}  # the transaction list is the question


class LetterNotApplicable(ValueError):
    """The case holds nothing this letter could ask about."""


def _attribution(result: dict[str, Any]) -> dict[str, Any] | None:
    """The trace (original or follow-on) that reached an exchange, if any.

    `route` is a follow-on's path from the reported address to the swapping
    wallet, in the original asset; None for a case stored before it was kept.
    `cap` and `swaps` are what the follow-on may state and every swap it
    covers (pipeline._follow_swaps); None in older cases."""
    if result.get("exchange"):
        return {"trace": result, "asset": result.get("asset"), "via_swap": None, "route": None,
                "cap": None, "swaps": None, "left_out": None}
    for follow in result.get("follow_ons") or []:
        found = follow.get("result") or {}
        if found.get("exchange"):
            return {"trace": found, "asset": follow.get("asset"), "via_swap": follow.get("swap"),
                    "route": follow.get("route"), "cap": follow.get("cap"), "swaps": follow.get("swaps"),
                    "left_out": follow.get("swaps_left_out")}
    return None


METHOD_NAME = {"fifo": "FIFO", "libr": "LIBR", "prorata": "pro-rata"}


def _swap_cap(result: dict[str, Any], found: dict[str, Any]) -> dict[str, Any] | None:
    """The most a follow-on letter may state: the follow-on's own cap, or
    for a case stored before it, the swap's output. On a payment trace never
    more than the victim's reported payments' share of what went into the
    swap, whatever the case holds."""
    swap = found["via_swap"] or {}
    cap = dict(found.get("cap") or {})
    if cap.get("amount") is None:
        if swap.get("amount_out") is None:
            return None
        cap = {"amount": float(swap["amount_out"]), "basis": "swap_output", "swap_output": float(swap["amount_out"]),
               "swap_input": swap.get("amount_in"), "traced_in": None, "share": None, "swaps": 1}
    reported, paid_in = result.get("reported_amount"), cap.get("swap_input")
    if reported and paid_in and reported < paid_in and (cap.get("share") is None or reported / paid_in < cap["share"]):
        share = reported / paid_in
        cap.update(amount=round(cap["swap_output"] * share, 6), basis="swap_share", traced_in=float(reported),
                   share=round(share, 6))
    return cap


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
    cap, basis, swap_cap = None, None, None
    if swap:
        swap_cap = _swap_cap(result, found)
        if swap_cap is not None:
            cap, basis = swap_cap["amount"], swap_cap["basis"]
    elif result.get("reported_amount"):
        cap, basis = float(result["reported_amount"]), "reported_amount"
    rng = methods.get("range") if methods.get("range") and methods["range"]["low"] != methods["range"]["high"] else None
    return {"amount": min(float(amount), cap) if cap is not None else float(amount),
            "method": method or "prorata", "range": rng, "cap": cap, "basis": basis, "swap_cap": swap_cap,
            "asset_in": (swap or {}).get("asset_in"), "intake": bool(result.get("reported_amount")),
            "arrived": prorata.get("arrived_total") if prorata.get("status") == "estimated" else None}


def _amount_lines(asset: str, stated: dict[str, Any]) -> list[str]:
    """The letter's amount paragraph, worded for what the figure is."""
    x = f"{stated['amount']:,.6f}"
    how = (f" (by {METHOD_NAME.get(stated['method'], stated['method'])}, the smallest of the tracing rules "
           f"applied; they give {stated['range']['low']:,.6f} to {stated['range']['high']:,.6f})"
           if stated["range"] else "")
    lead = "On a pro-rata estimate" if stated["method"] == "prorata" else "On an estimate"
    # Only an intake trace starts from the victim's own payments; anything
    # else starts from what the reported wallet sent.
    caveat = ("" if stated["intake"] else
              ". This trace is exploratory, so that figure is an upper bound: it can include other people's "
              "money, not only the complainant's")
    if stated["basis"] in ("swap_output", "swap_share"):
        swap = stated["swap_cap"]
        count = swap.get("swaps") or 1
        text = (f"{lead} from the public records, of the {swap['swap_output']:,.6f} {asset} "
                + ("the swap returned, " if count == 1 else f"the {count} swaps returned, "))
        if stated["basis"] == "swap_share":
            # The swapping wallet added money of its own.
            whose, source = (("the victim's", "the victim's reported payments") if stated["intake"]
                             else ("the traced funds", "the reported address"))
            text += (f"at most {swap['amount']:,.6f} {asset} can be {whose} (at most {swap['traced_in']:,.6f} of "
                     f"the {swap['swap_input']:,.6f} {stated['asset_in']} that went in can have come from {source}); "
                     f"about {x} {asset}{how} of it reached this address")
        else:
            text += f"about {x} {asset}{how} reached this address"
    elif stated["basis"] == "reported_amount":
        text = (f"{lead} from the public records, about {x} of the {stated['cap']:,.6f} {asset} the victim "
                f"reported paying{how} reached this address")
    else:
        # Address-only: the start is everything the reported wallet sent.
        text = (f"{lead} from the public records, about {x} {asset}{how} of everything the reported address "
                "sent along this route reached this address")
    arrived = stated["arrived"]
    if arrived is not None and arrived - stated["amount"] > stated["amount"] * 0.05:
        rest = ("came from other sources" if stated["method"] == "prorata" and not stated["cap"]
                else "is not counted in that figure")
        text += (f" ({arrived:,.6f} {asset} arrived along this path in total; about "
                 f"{arrived - stated['amount']:,.6f} {rest})")
    return ["", *textwrap.wrap(text + caveat + ".", width=95, initial_indent="   ", subsequent_indent="   ",
                               break_long_words=False, break_on_hyphens=False),
            "   This is an estimate; your own records of the deposits are authoritative."]


def _all_traces(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [result] + [f["result"] for f in result.get("follow_ons") or [] if f.get("result")]


def _frozen(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Tether's own USDT freezes, on the chains where USDT is Tether's
    blacklisting contract. Other issuers' freezes (Circle's USDC, ...) stay
    in the report's screening notes: the Tether letter says each listed
    address is on the USDT contract's blacklist."""
    return [m for t in _all_traces(result) if t.get("chain") in USDT_CHAINS
            for m in t.get("risk_matches") or [] if is_tether_usdt_freeze(m)]


def _usdt_traces(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in _all_traces(result) if t.get("asset") == "USDT" and t.get("chain") in USDT_CHAINS]


def _route_into(trace: dict[str, Any], i: int) -> tuple[list[tuple[str, int | None]], int]:
    """The transfers along the route into its i-th wallet, with their times,
    and how many there were: the case's own list of them, which holds every
    one on the route, else the step's, which keeps twenty."""
    route = trace.get("trace_path") or []
    if i <= 0:
        return [], 0  # what reached the start is the complaint's, never this letter's
    step, before = route[i], route[i - 1].get("address")
    rows = [t for t in trace.get("transfers") or [] if t.get("from") == before and t.get("to") == step.get("address")]
    hashes = step.get("tx_hashes") or []
    pairs = ([(t.get("hash"), t.get("timestamp")) for t in rows] if rows else
             [(h, step.get("first_seen") if len(hashes) == 1 else None) for h in hashes])
    return pairs, max(len(pairs), step.get("tx_count") or 0)


NOT_A_HOLDER = ("label", "exchange", "inferred_exchange", "risk_category", "is_router", "is_service_contract",
                "is_terminal")
STOPS_MAX = 5  # a freeze request names a few wallets, never every end of a wide trace


def _stops(trace: dict[str, Any], frozen: set[str]) -> tuple[list[dict[str, Any]], int]:
    """Where a trace that reached no exchange left the USDT: the unlabelled
    wallets that received it and sent none on (the start, if it sent
    nothing), the largest first, and how many more there were."""
    graph = trace.get("graph") or {}
    ends = sorted((n for n in graph.get("nodes") or [] if n.get("address") and not n.get("total_out_native")
                   and n["address"] not in frozen and not any(n.get(k) for k in NOT_A_HOLDER)),
                  key=lambda n: -(n.get("total_in_native") or 0))
    wallets = []
    for n in ends[:STOPS_MAX]:
        address = n["address"]
        if address == trace.get("address"):
            wallets.append({"address": address, "pairs": [], "count": 0})
            continue
        rows = [(t.get("hash"), t.get("timestamp")) for t in _transfers_into(trace, address)]
        count = sum(e.get("tx_count") or 0 for e in graph.get("edges") or [] if e.get("target") == address)
        wallets.append({"address": address, "pairs": rows, "count": max(len(rows), count)})
    return wallets, len(ends) - len(wallets)


def _tether_holds(result: dict[str, Any]) -> list[tuple[dict[str, Any], list[dict[str, Any]], int]]:
    """Each USDT trace's wallets that Tether could be asked to freeze: along
    the route to the exchange, or where a trace that reached none stopped;
    never an exchange's or another labelled wallet, nor one Tether has
    already frozen. A reverse trace runs back to where the money came from: none."""
    if result.get("direction", "outgoing") != "outgoing":
        return []
    frozen = {m.get("address") for m in _frozen(result)}
    out = []
    for trace in _usdt_traces(result):
        route, wallets, left = trace.get("trace_path") or [], [], 0
        for i, s in enumerate(route):
            if (s.get("address") and s["address"] not in frozen and s["address"] != trace.get("exchange_address")
                    and not s.get("label") and not s.get("exchange")):
                pairs, count = _route_into(trace, i)
                wallets.append({"address": s["address"], "pairs": pairs, "count": count})
        if not route:
            wallets, left = _stops(trace, frozen)
        if wallets:
            out.append((trace, wallets, left))
    return out


def available(result: dict[str, Any]) -> list[dict[str, str]]:
    """Which letters this case can support, for the interface to offer: the
    urgent freeze letters first, since they are sent first."""
    urgent, info = [], []
    found = _attribution(result)
    if found and result.get("direction", "outgoing") == "outgoing":
        urgent.append({"to": EXCHANGE_FREEZE, "title": f"Urgent freeze request to {found['trace']['exchange']}"})
        info.append({"to": EXCHANGE, "title": f"Request to {found['trace']['exchange']}"})
    if _tether_holds(result):
        urgent.append({"to": TETHER_FREEZE, "title": "Urgent freeze request to Tether"})
    if _frozen(result) or _usdt_traces(result):
        info.append({"to": TETHER, "title": "Request to Tether"})
    return urgent + info


# An exploratory trace starts from everything the reported address sent, so
# every amount it reaches can hold third parties' funds as well as the victim's.
EXPLORATORY_LINES = [
    "   This trace is EXPLORATORY: it started from the reported address, not from the victim's",
    "   payments, so every amount in this letter can include other people's money. Each amount is",
    "   an upper bound on what can be the victim's, not a finding that it is.",
]


def _opening(result: dict[str, Any]) -> list[str]:
    """Only what the case holds. A trace from the victim's payments states them as
    verified on chain; one from the address alone says so and leaves them to the
    officer. The complaint's references are always the officer's."""
    lines = [
        "1. This office is investigating a complaint of cyber-enabled financial fraud. The wallet",
        f"   address {result.get('address')} was reported in connection with it.",
    ]
    intake = result.get("intake") or {}
    payments = intake.get("payments") or [] if intake.get("mode") == "payment" else []
    if not payments:
        return lines + [
            f"   The victim's payments: {BLANK} (officer to state amounts, dates and references",
            "   from the complaint). This trace followed the reported address's history, not specific payments.",
            # An older intake case may hold the reported amount without its
            # payments: it started from them, so it is not exploratory.
            *(EXPLORATORY_LINES if not result.get("reported_amount") else []),
        ]
    asset = result.get("asset")
    total = result.get("reported_amount")
    if total is None:
        total = sum(float(p.get("amount") or 0) for p in payments)
    lines.append(f"   The victim's payments, as verified on chain: {len(payments)} transfer"
                 f"{'s' if len(payments) != 1 else ''}, {_amount(total)} {asset} in all:")
    for payment in payments:
        lines += [f"     {_amount(payment.get('amount'))} {asset}, {_paid_at(payment)}",
                  f"       tx {payment.get('tx_hash') or WITHHELD}"]
    return lines + [f"   {BLANK} (officer to add the complaint's references)."]


def _label_source(trace: dict[str, Any]) -> str:
    """Where a label came from and when, so a reader can weigh it: the list as
    the trace recorded it, or, for a case stored before that, as held today."""
    recorded = provenance.list_metas(trace)
    if recorded is not None:
        checked = (recorded.get("labels_path") or {}).get("last_reviewed")
        return f"Exchequer's exchange label list{f', last checked {checked}' if checked else ''}"
    meta = None
    if trace.get("chain"):
        try:
            meta = _list_meta(config.get_chain(trace["chain"]).labels_path)
        except config.UnknownChainError:
            pass
    checked = (meta or {}).get("last_reviewed")
    return ("Exchequer's exchange label list as held when this letter was drafted"
            f"{f', last checked {checked}' if checked else ''}")


def _plain_label(label: str | None) -> str:
    return short((label or "").removesuffix(TAG_WORDING), LABEL_MAX)


LABEL_MAX = 200  # a label is a name; anything longer is not one a letter should quote


def _cleaned(value: Any) -> Any:
    """`value` with every string on one line (display_text.one_line). Labels,
    tags and names in a case come from third parties, and a newline in one
    would print as a paragraph of the letter. The graph is never quoted, so
    it is kept as it is rather than walked: only its addresses, which are
    printed through one_line, and its numbers and flags are read."""
    if isinstance(value, str):
        return one_line(value)
    if isinstance(value, list):
        return [_cleaned(v) for v in value]
    if isinstance(value, dict):
        return {k: v if k == "graph" else _cleaned(v) for k, v in value.items()}
    return value


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


def _today() -> str:
    return _utc_now().astimezone(IST).strftime("%d %B %Y")  # the officer's date, whatever the server's clock says


def _header(case_id: str, result: dict[str, Any], to_line: str, subject: str) -> list[str]:
    manifest = (result.get("evidence") or {}).get("manifest_sha256")
    return [
        "DRAFT — for the investigating officer to review, complete and sign.",
        NOT_VALID,
        "Generated by Exchequer from a stored case. Nothing below has been sent.",
        "",
        f"From      : {BLANK} (name, rank, unit, official e-mail and phone)",
        f"Reference : {BLANK} (FIR / complaint / NCRP acknowledgement number)",
        f"Date      : {_today()}",
        f"To        : {to_line}",
        "",
        f"Subject   : {subject}",
        "",
        f"Exchequer case {case_id}, traced {_when_iso(result.get('created_at'))},",
        f"{result.get('chain_name')} · asset {result.get('asset')} · reported address {result.get('address')}.",
        (f"Evidence manifest SHA-256: {manifest}" if manifest else
         "This case was stored before evidence hashing; the report says so."),
        *_verify_lines(),
        "",
    ]


def _verify_lines() -> list[str]:
    """Where the attached report can be checked, and the key it must carry."""
    from .signing import get_signer

    where = f"{config.PUBLIC_URL}/verify" if config.PUBLIC_URL else "/verify on the server that issued it"
    return [f"Check the attached report only at {where}; it must be signed with the",
            f"Ed25519 key whose SHA-256 fingerprint is {get_signer().fingerprint_sha256}."]


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
    if swap and len(found["swaps"] or []) > 1:
        # Every swap by that wallet into the asset: the follow-on covers them all.
        each = found["swaps"]
        lines += [
            "",
            f"   On the way, {sender} exchanged {sum(s.get('amount_in') or 0 for s in each):,.6f} "
            f"{swap.get('asset_in')}",
            f"   for {sum(s.get('amount_out') or 0 for s in each):,.6f} {asset} in {len(each)} swaps (the largest at "
            f"{swap.get('router_label')}); the {asset} was followed",
            "   from the first of them:",
            *(f"     {s.get('amount_in') or 0:,.6f} {swap.get('asset_in')} for {s.get('amount_out') or 0:,.6f} "
              f"{asset}, tx {s.get('tx')}" for s in each),
        ]
    elif swap:
        returned = (f"{swap['amount_out']:,.6f} {asset}" if swap.get("amount_out") is not None else asset)
        lines += [
            "",
            f"   On the way, {sender} exchanged {swap.get('amount_in', 0):,.6f} {swap.get('asset_in')}",
            f"   for {returned} at {swap.get('router_label')} (tx {swap.get('tx')}); the {asset} was followed",
            "   from that swap.",
        ]
    if swap and found.get("left_out"):
        # Swaps that cannot have carried the traced funds -- made before they
        # reached the wallet, or too small: the follow-on starts after them, so
        # what the wallet sent before is not counted.
        lines += ["", f"   Earlier swaps by {sender} cannot have carried the traced funds and were left out;",
                  f"   the {asset} was followed from the first swap that could:",
                  *(f"     {s.get('amount_in') or 0:,.6f} {swap.get('asset_in')} for {s.get('amount_out') or 0:,.6f} "
                    f"{asset}, tx {s.get('tx')} (left out: "
                    + ("made before the traced funds reached it)" if s.get("why") == "before_arrival"
                       else "too small to be the traced funds)")
                    for s in found["left_out"])]
    stated = _letter_amount(result, found)
    if stated is not None:
        lines += _amount_lines(asset, stated)
    others = also_reached(trace)
    if others:
        # The trace names one exchange, but material funds also went elsewhere
        # (8 Nov check): the addressee must know, and the officer must confirm.
        lines += ["", "   Material funds in this trace also reached another exchange, which this request does",
                  "   not cover:",
                  *(f"     {also_reached_line(o)}" for o in others),
                  "   [Officer to confirm that this exchange is the right addressee; a separate request",
                  "   may be needed to each.]"]
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


# -- the urgent freeze letters -------------------------------------------------------
FREEZE_ASK = {  # what the case holds about the address decides what may be held
    LABELLED_DEPOSIT: "Please hold, now, funds up to the amount below in the account(s) that deposit address {a} "
                      "belongs to",
    INFERRED_DEPOSIT: "If {a} is a deposit address you issued, please hold, now, funds up to the amount below in "
                      "the account(s) it belongs to",
    EXCHANGE_WALLET: "Please hold, now, funds up to the amount below in the customer account(s) credited by the "
                     "transactions below into your wallet {a} (this request is not about the wallet itself)",
    EXPLORER_TAG: "If {a} is controlled by you, please hold, now, funds up to the amount below in the account(s) "
                  "credited by the transactions below",
}


def _freeze_header(to_line: str, subject: str, ask: str) -> list[str]:
    return [
        "DRAFT — URGENT freeze request, for the investigating officer to complete and sign.",
        NOT_VALID,
        "Generated by Exchequer from a stored case. Nothing below has been sent.",
        "",
        f"From      : {BLANK} (officer's name and rank)",
        f"Station   : {BLANK} (police station / cyber cell)",
        f"Reference : {BLANK} (FIR / NCRP acknowledgement number)",
        f"Contact   : {BLANK} (official e-mail and phone)",
        f"Date      : {_today()}",
        f"To        : {to_line}",
        "",
        f"Subject   : URGENT — {subject}, pending a formal request",
        "",
        f"Under {BLANK} (the legal provision this request is made under, officer to state):",
        *textwrap.wrap(ask + ", pending a formal request from this office.", width=95, initial_indent="   ",
                       subsequent_indent="   ", break_long_words=False, break_on_hyphens=False),
        "",
    ]


def _freeze_amount(stated: dict[str, Any] | None, asset: str, reached: str | None = None) -> list[str]:
    """The information letter's figure, never a gross one; the officer's when
    there is none. To Tether it is what went on to the exchange (`reached`),
    not what the listed wallets hold."""
    if stated is None:
        return [f"Amount    : {BLANK} (officer to state)"]
    hedge = "" if stated["intake"] else "; it can include other people's money"
    went = f" passed through these wallets and reached {reached}" if reached else ""
    return [f"Amount    : about {stated['amount']:,.6f} {asset}{went}",
            f"            (the smallest estimate the case holds, from the public records{hedge})"]


def _hash_lines(pairs: list[tuple[str, int | None]], into: str, count: int = 0) -> list[str]:
    if not pairs:
        return [f"Transactions into {into}: {BLANK} (officer to add)"]
    cut = [f"     ({len(pairs)} of {count} transfers listed; officer to add the rest)"] if count > len(pairs) else []
    return [f"Transactions into {into} (times in IST, with UTC):",
            *(f"     tx {h}" + (f", {_when(ts)}" if ts else "")
              for h, ts in sorted(pairs, key=lambda p: (p[1] is None, p[1] or 0))), *cut]


def _carrying(trace: dict[str, Any], i: int, amount: float | None) -> list[dict[str, Any]]:
    """The transfers into the route's i-th wallet that can carry the traced
    funds: from the wallet before it, in time order, each carrying no more
    than had reached that wallet by then, until `amount` is covered. A wallet
    the exchange runs credits many customers: the rest are not this case's."""
    route, rows = trace["trace_path"], trace.get("transfers") or []
    via, start = route[i - 1].get("address"), route[i - 2].get("address") if i >= 2 else None
    arrived = ([(a.get("timestamp") or 0, a.get("value_native") or 0.0) for a in rows
                if start and a.get("from") == start and a.get("to") == via]
               or [(route[i - 1].get("first_seen") or 0, float("inf"))])  # the start's money is all traced
    listed, carried = [], 0.0
    for t in (t for t in _transfers_into(trace, route[i].get("address")) if t.get("from") == via):
        if amount is not None and carried >= amount - 1e-6:
            break
        reached = sum(v for ts, v in arrived if ts <= (t.get("timestamp") or 0))
        part = min(t.get("value_native") or 0.0, reached - carried)
        if part > 1e-9:
            listed.append(t)
            carried += part
    return listed


SIGN_OFF = ["", BLANK, "(signature, name, rank, seal)"]


def _exchange_freeze(result: dict[str, Any]) -> str:
    found = _attribution(result)
    if not found or result.get("direction", "outgoing") != "outgoing":
        raise LetterNotApplicable("This case reached no exchange, so there is no exchange to write to.")
    trace, asset = found["trace"], found["asset"]
    exchange, address, kind = trace["exchange"], trace["exchange_address"], attribution_kind(trace)
    stated = _letter_amount(result, found)
    i = next((n for n, s in enumerate(trace.get("trace_path") or []) if s.get("address") == address), 0)
    every, note = _transfers_into(trace, address), []
    if kind in COMPANY_WALLET_KINDS:
        # Every transfer into a wallet the exchange runs credits some customer:
        # only those that can carry the traced funds, so no one else's is held.
        listed = _carrying(trace, i, stated["amount"] if stated else None) if i else []
        pairs, count = [(t.get("hash"), t.get("timestamp")) for t in listed], len(listed)
        others = len(every) - len(listed) if listed else 0
        if others:
            note = textwrap.wrap(f"(the earliest that can carry the traced funds; {others} other transfer"
                                 f"{'s' if others != 1 else ''} into it in this trace "
                                 f"{'are' if others != 1 else 'is'} not part of this request)",
                                 width=95, initial_indent="     ", subsequent_indent="      ")
    elif every:
        pairs, count = [(t.get("hash"), t.get("timestamp")) for t in every], len(every)
    else:
        pairs, count = _route_into(trace, i)
    lines = _freeze_header(
        f"{exchange} — Law Enforcement / Compliance team {BLANK} (officer to find and confirm the right channel)",
        f"hold funds credited through {address}", FREEZE_ASK[kind].format(a=address))
    lines += [f"Chain     : {trace.get('chain_name') or result.get('chain_name')}", f"Token     : {asset}",
              f"Wallet    : {address}", *_freeze_amount(stated, asset), *_hash_lines(pairs, "it", count), *note,
              *SIGN_OFF]
    return "\n".join(lines) + "\n"


def _tether_freeze(result: dict[str, Any]) -> str:
    holds = _tether_holds(result)
    if not holds:
        raise LetterNotApplicable("This case has no USDT wallet on Ethereum or Tron for Tether to freeze.")
    lines = _freeze_header(
        f"Tether Operations Limited — law-enforcement requests team {BLANK} (officer to find and confirm the right channel)",
        "freeze USDT at the wallets below", "Please freeze, now, the USDT held at the wallets below")
    found = _attribution(result)
    for trace, wallets, left in holds:
        # The figure the exchange letter states, when this trace reached that exchange: it went on past these wallets.
        own = found if found and found["trace"] is trace else None
        lines += [f"Chain     : {trace.get('chain_name')}", "Token     : USDT", "Wallets   : (officer to confirm each)",
                  *(f"     {one_line(w['address'])}" for w in wallets),
                  *([f"     ({left} more wallet{'s' if left != 1 else ''} where the traced USDT stopped "
                     f"{'are' if left != 1 else 'is'} not listed)"] if left else []),
                  *_freeze_amount(_letter_amount(result, own) if own else None, "USDT", trace.get("exchange")),
                  *_hash_lines([p for w in wallets for p in w["pairs"]], "them", sum(w["count"] for w in wallets)),
                  ""]
    return "\n".join(lines[:-1] + SIGN_OFF) + "\n"


def draft(case_id: str, result: dict[str, Any], to: str) -> str:
    result = _cleaned(result)
    if to == EXCHANGE_FREEZE:
        return _exchange_freeze(result)
    if to == TETHER_FREEZE:
        return _tether_freeze(result)
    if to == EXCHANGE:
        return _exchange_letter(case_id, result)
    if to == TETHER:
        return _tether_letter(case_id, result)
    raise ValueError(f"Unknown letter '{to}'. Expected one of: {', '.join(LETTERS)}.")
