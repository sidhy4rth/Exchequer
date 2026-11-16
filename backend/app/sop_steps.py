"""The steps the MHA SOP for NCRP-CFCFRMS sets out, beside what a case's own
records show (feature 8, flag EXCHEQUER_SOP_STEPS).

A checklist for the officer, nothing more. Each step quotes the SOP word for
word with its section and PDF page; the SOP is quoted, never applied, and no
notice is drafted here. Next to each step goes what Exchequer's records for
the case show, or that the step happens on the portal, which Exchequer cannot
see: no portal is read from or written to.

Source: the copy of the SOP a bank publishes, the one sop_reminders.py names
(SOP_URL, SHA-256 65400b47a16ae9986e7bb9b339b26db920435a3ce6c128e804492b6e4be3bd42,
fetched again on 16 Nov 2026 with the same hash). The quotes new here (6.1(d),
6.1(f), 6.1(g), 6.1(i), 6.2(c)) were checked against that file's text on
16 Nov 2026; the pages are the PDF pages as rendered in the 15 Nov quote check
(6.1(d) to (i) on page 12, 6.1(k) and 6.2 on page 13), since a plain text dump
of this file repeats some text a page early. "…" marks words left out; the
ligature glyphs are written as plain letters. The 6.1(k), 9.4 and 10.1 quotes
are the reviewed ones in sop_reminders.py and sop_summary.py, reused as they are.

The NCRP number and the case reference are never returned: the first step says
only whether one of the SOP's usual shape (ncrp.py) is recorded.
"""
from __future__ import annotations

from typing import Any

from . import ncrp, sop_reminders, sop_summary
from .display_text import one_line

OFFICER = "A step on the portal or with the bank: Exchequer cannot see the portal, so it shows nothing here."
NOTE = ("The SOP's steps, quoted from one copy, for the officer to check. Not applied to this case and not "
        "legal advice; check the current SOP and the law.")

_REMINDER = {r["id"]: r for r in sop_reminders.BANK_HOLD}


def _cite(section: str, page: int, quote: str) -> dict[str, Any]:
    return {"section": section, "page": page, "quote": quote}


def _reused(rid: str) -> dict[str, Any]:
    r = _REMINDER[rid]
    return _cite(r["section"], r["page"], r["quote"])


STEPS: list[dict[str, Any]] = [
    {"id": "acknowledgement", "title": "The complaint's acknowledgement number", "cites": [
        _cite("§6.1(d)", 12, "The complainant receives a 14-digit acknowledgment number starting with digit ‘2’ "
              "from the SMS header ‘XXNCRP’ (XX indicates State code)."),
        _cite("§6.2(c)", 13, "The complainant will receive a 14-digit acknowledgment from the SMS header ‘XXNCRP’ "
              "number starting from “3”.")]},
    {"id": "submit", "title": "The police officer submits the complaint to CFCFRMS", "cites": [
        _cite("§6.1(f)", 12, "The Police Officer dealing with the complaint will go through the complaint and "
              "satisfy herself that an offence related to cyber-enabled financial crimes is made out and with "
              "immediate effect, she shall submit the complaint to CFCFRMS.")]},
    {"id": "bank-notices", "title": "Notices to the banks to hold the amount", "cites": [
        _cite("§6.1(g)", 12, "Notices under Section 168 BNSS read with Section 94 BNSS will be sent to all the "
              "concerned Banks and FIs for holding the reported amount and updating the details through "
              "CFCFRMS. … The notice format u/s 168 BNSS read with Section 94 BNSS is attached as Annexure – I."),
        _reused("s6-1k-1-week")]},
    {"id": "fir", "title": "An FIR or e-FIR", "cites": [
        _cite("§6.1(i)", 12, "An email and a SMS will be sent through the CFCFRMS portal to the State and District "
              "Nodal Officers and SHO of the Police Station concerned to register an FIR or e-FIR in compliance "
              "with Section 106 BNSS, wherever freezing of accounts or suspension of digital services or interim "
              "custody of the reported amount of the victims is contemplated.")]},
    {"id": "vasp", "title": "Money converted into crypto at an exchange (VASP)", "cites": [
        _cite("§9.4(ii)", 19, sop_summary.ONBOARDED.split(": ", 1)[1].strip('"')),
        _cite("§9.4(iv)", 19, sop_summary.NOT_ONBOARDED.split(": ", 1)[1].strip('"'))]},
    {"id": "grievance", "title": "If the account holder raises a grievance about a hold", "cites": [
        _reused("s10-1e-15-days"), _reused("s10-1f-2-days")]},
]


def _usual(value: Any) -> bool:
    """Whether `value` is an NCRP number of the SOP's usual shape (never says which)."""
    return isinstance(value, str) and bool(value.strip()) and ncrp.shape_note(value) is None


def _acknowledgement(result: dict[str, Any]) -> str:
    intake = result.get("intake") if isinstance(result.get("intake"), dict) else {}
    if any(_usual(intake.get(k)) for k in ("ncrp_ack", "case_ref")):
        return "This case records a number of the usual shape (14 digits starting with 2 or 3)."
    return ("This case records no number of that shape that you may read (an FIR or GD number may be "
            "recorded instead).")


def _bank_holds(rows: list[dict[str, Any]]) -> str:
    held = sum(1 for r in rows if r.get("holder") == "bank" and r.get("status") == "held")
    if not held:
        return "The asset register records no bank hold still held for this case."
    what = "1 bank hold" if held == 1 else f"{held} bank holds"
    return (f"The asset register records {what} still held for this case. It does not record whether a hold "
            "went through CFCFRMS.")


def _vasp(result: dict[str, Any]) -> str:
    if result.get("direction", "outgoing") != "outgoing":
        return "This trace follows where the money came from, not where it went, so it names no exchange reached."
    reached = sop_summary._reached(result)
    if reached is None:
        return "This trace reached no exchange address."
    att = reached[1].attribution
    return (f"This trace reached an address attributed to {one_line(att.exchange)}. Whether that "
            "exchange is on CFCFRMS is the officer's answer: Exchequer holds no list of onboarded exchanges. "
            "An attribution names an exchange address, not a person.")


def steps(result: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    """The checklist for a case (`result` as this reader may read it, and its asset-register rows)."""
    shown = {"acknowledgement": _acknowledgement(result), "bank-notices": _bank_holds(assets),
             "vasp": _vasp(result)}
    return {
        "steps": [{**s, "case": shown.get(s["id"], OFFICER)} for s in STEPS],
        "source": f"{sop_reminders.SOP_NAME}, {sop_reminders.SOP_COPY}: {sop_reminders.SOP_URL}",
        "note": NOTE,
    }
