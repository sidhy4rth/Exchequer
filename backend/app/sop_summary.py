"""A crypto summary of a case in the terms of the CFCFRMS SOP's para 9.4, for
the officer to enter on CFCFRMS or attach (feature 8, flag EXCHEQUER_SOP_SUMMARY).

Source: MHA, "Standard Operating Procedure (SOP) for NCRP-CFCFRMS, Custody,
Restoration of money and Grievance Redressal", para 9.4 "Measures to be taken
by the Virtual Asset Service Providers (VASPs)". Two copies were read, and on
15 Nov 2026 each quote below was checked word for word against both copies'
rendered pages (not their text layers, which can run a page out):
  - the copy a bank publishes,
    https://www.zoroastrianbank.bank.in/download/SOP-NCRP.pdf (52 PDF pages,
    SHA-256 65400b47a16ae9986e7bb9b339b26db920435a3ce6c128e804492b6e4be3bd42):
    para 9.4 is all on PDF page 19 (its pages print no numbers; its contents
    list says 28-30). Its cover carries no date. It is the SOP the Meghalaya
    High Court notified on 28.04.2026
    (https://meghalayahighcourt.nic.in/notification-28042026-sop-national-cybercrime-reporting-portal-and-citizen-financial-fraud);
  - the copy at https://the420.in/wp-content/uploads/2026/01/sop.pdf (99 PDF
    pages, SHA-256 75251166065bfecbdb60ea91013bc98f8c5781c9e51a9824b5693cea7a00a80d),
    whose cover is dated 02.01.2026: para 9.4 runs over printed pages 28 to 30
    of 98 (PDF pages 29 to 31), and both quotes are on printed page 29 (PDF
    page 30). This copy's 9.4 also ends with a list of P2P details the VASP
    updates; the bank's copy does not have that list.

What it holds is only what the case holds: the exchange the trace reached, the
exchange address and how it was attributed, the amounts and transaction
hashes as the trace has them. An attribution names an exchange address; only
the exchange can name its customer. Whether the exchange is on CFCFRMS is the
officer's answer: Exchequer holds no list of onboarded exchanges, and the
answer is not stored. The SOP is quoted for that answer, never applied: the
summary gives no legal advice and never says a provision applies to the case.

The NCRP number is never filled in here. The line is a blank the officer's
browser fills only with a number the officer types (CryptoSummary.jsx), so the
number never reaches this server, a log or the audit trail.
"""
from __future__ import annotations

from typing import Any, Literal

from .case_privacy import WITHHELD
from .contracts import read_case
from .display_text import one_line, short
from .report import IST, _amount, _when
from .request_letters import _utc_now

Answer = Literal["yes", "no", "unknown"]
ANSWERS: dict[str, str] = {"yes": "Yes", "no": "No", "unknown": "Not known"}

NCRP_BLANK = "NCRP acknowledgement no.: [officer to enter]"
LISTED = 20  # transfers into the exchange address listed here; the report lists every one

SOURCE = ('MHA, "Standard Operating Procedure (SOP) for NCRP-CFCFRMS, Custody, Restoration of money and '
          'Grievance Redressal", para 9.4, quoted from the copy at '
          "https://www.zoroastrianbank.bank.in/download/SOP-NCRP.pdf (PDF page 19; that copy's cover carries no "
          "date), the SOP the Meghalaya High Court notified on 28.04.2026. The same words are on page 29 of the "
          "copy at https://the420.in/wp-content/uploads/2026/01/sop.pdf, whose cover is dated 02.01.2026.")

# SOP 9.4(ii), last sentence: what an onboarded VASP updates on CFCFRMS.
ONBOARDED = ('SOP 9.4(ii): "Additionally, the VASP shall update CFCFRMS with the relevant details, including the '
             "KYC information of the account holder, associated bank account details, transaction ID or Hash, "
             'wallet ID, and liquidation details."')
# SOP 9.4(iv), in full: an exchange not onboarded on CFCFRMS.
NOT_ONBOARDED = ('SOP 9.4(iv): "If the reported amount has been converted into a Virtual Digital Asset (VDA) at an '
                 "exchange that is not onboarded on CFCFRMS, the Law Enforcement Agency (LEA) may issue a notice "
                 "under Section 106(1) of BNSS to seize the assets through available law enforcement channels or "
                 "the Sahyog Portal of I4C - MHA. To trace the movement of these assets, the LEA may conduct a VDA "
                 "forensic analysis to identify further transaction trails and ascertain that which VASP or VDA "
                 'Exchange has control of the wallet."')
QUOTES: dict[str, list[str]] = {"yes": [ONBOARDED], "no": [NOT_ONBOARDED], "unknown": [ONBOARDED, NOT_ONBOARDED]}


def _reached(result: dict[str, Any]) -> tuple[dict[str, Any], Any, str | None] | None:
    """(the trace, its attribution, the swap that led to it) for the first trace that reached an exchange."""
    case = read_case(result)
    if case.attribution is not None:
        return result, case, None
    for follow in result.get("follow_ons") or []:
        found = follow.get("result")
        if found and (sub := read_case(found)).attribution is not None:
            return found, sub, one_line(follow.get("asset") or "")
    return None


def _how(att: Any) -> str:
    """How the exchange address was attributed, in the case's own terms."""
    label = short(one_line(att.label or ""), 200)
    named = f' (label: "{label}")' if label else ""
    if att.source == "live_tag":
        return (f"the block explorer's tag read at trace time{named}; Exchequer has not confirmed it, "
                "so ask the exchange to confirm the address is theirs first")
    if att.kind == "deposit_inferred":
        return ("inferred, not confirmed: every outflow of this unlabelled address swept to one "
                f"{one_line(att.exchange)} wallet, the pattern of a customer deposit address")
    if att.kind == "deposit_label":
        return f"Exchequer's exchange label list names it a deposit address of {one_line(att.exchange)}{named}"
    return (f"Exchequer's exchange label list names it a wallet {one_line(att.exchange)} operates itself{named}; "
            "it belongs to no one customer")


def summary(case_id: str, result: dict[str, Any], answer: Answer) -> str:
    """The plain-text summary of `result` (the case as this reader may read it)."""
    lines = ["CRYPTO SUMMARY FOR CFCFRMS: SOP 9.4 (VASPs)",
             f"Exchequer case {case_id}, prepared {_utc_now().astimezone(IST).strftime('%d %B %Y')} (IST).",
             "",
             "Exchequer's tracing analysis in the words of SOP 9.4, for the officer to enter on CFCFRMS or attach.",
             "It is not a CFCFRMS export and does not follow the portal's own form, which is not public.",
             "It gives no legal advice: the officer decides what applies.",
             "",
             NCRP_BLANK,
             ""]
    # An incoming trace's exchange is where money came from, not where it went (report.py).
    incoming = result.get("direction", "outgoing") != "outgoing"
    reached = None if incoming else _reached(result)
    if incoming:
        lines += ["1. Exchange (VASP) reached: none. This trace follows where the reported address's money came from,",
                  "   not where it went, so it names no exchange the money reached. See the case report.", ""]
    elif reached is None:
        lines += ["1. Exchange (VASP) reached: none. This trace reached no exchange address, so there is",
                  "   nothing here for SOP 9.4. See the case report for where the money went.", ""]
    else:
        trace, case, via = reached
        att = case.attribution
        asset = one_line(trace.get("asset") or "")
        lines += ["1. Exchange (VASP) reached",
                  f"   Exchange: {one_line(att.exchange)}",
                  f"   Exchange address (wallet ID): {att.address}",
                  f"   Network and asset: {one_line(trace.get('chain_name') or trace.get('chain') or '?')}, {asset}",
                  f"   How attributed: {_how(att)}.",
                  *([f"   Hops from the reported address: {att.depth}."] if att.depth is not None else []),
                  *([f"   Reached after a swap into {via} (a follow-on trace)."] if via else []),
                  "   An attribution names an exchange address, not a person: only the exchange can say",
                  "   which customer account it serves.",
                  "",
                  "2. Amounts and transactions, as the trace has them"]
        main = read_case(result)
        paid = main.reported_amount
        lines.append(f"   Reported paid by the victim: {_amount(paid)} {one_line(result.get('asset') or '')}"
                     if paid is not None else
                     "   Reported paid by the victim: not given (an address-only trace, not a reported payment).")
        conservative = case.estimates.conservative
        if conservative is not None:
            lines.append(f"   Estimated to have reached the exchange (the smallest of the methods run): "
                         f"{_amount(conservative)} {asset}"
                         + ("" if paid is not None else ", of the reported address's history"))
        if main.intake.payments:
            lines.append("   Victim's payments (transaction ID or hash, amount, time):")
            lines += [f"   - {p.tx_hash or WITHHELD}  {_amount(p.amount)} {one_line(p.asset)}  "
                      f"{_when(p.timestamp) if p.tx_hash else WITHHELD}" for p in main.intake.payments]
        into = sorted((t for t in case.transfers if t.to == att.address), key=lambda t: t.timestamp or 0)
        lines.append("   Transfers into the exchange address (transaction ID or hash, amount, time):")
        lines += [f"   - {t.hash or '?'}  {_amount(t.value_native)} {asset}  {_when(t.timestamp)}"
                  for t in into[:LISTED]] or ["   - none listed in the case"]
        if len(into) > LISTED:
            lines.append(f"   ({len(into) - LISTED} more in the case report.)")
        lines.append("")
    lines += [f"3. Is this exchange on CFCFRMS? {ANSWERS[answer]} (the officer's answer; Exchequer holds no",
              "   list of the exchanges onboarded on CFCFRMS).",
              "   What SOP 9.4 says for this answer, quoted, not applied:",
              *(f"   {q}" for q in QUOTES[answer]),
              "",
              f"Source: {SOURCE}"]
    return "\n".join(lines) + "\n"
