"""Reminders from the MHA SOP for NCRP-CFCFRMS on asset-register rows (feature 8).

Behind config.SOP_DEADLINES. These are reminders of what the SOP says, quoted
word for word, for the officer to weigh. They are not legal deadlines, and
Exchequer enforces none of them: nothing here refuses, blocks or reorders
anything, and the register's own 45-day court deadline (assets.DEADLINE_DAYS)
is untouched.

Source: Ministry of Home Affairs, "Standard Operating Procedure (SOP) for
NCRP-CFCFRMS, Custody, Restoration of money and Grievance Redressal", the copy
a bank publishes at
    https://www.zoroastrianbank.bank.in/download/SOP-NCRP.pdf
(PDF ModDate 11 Feb 2026, 52 pages, 2,587,996 bytes, SHA-256
65400b47a16ae9986e7bb9b339b26db920435a3ce6c128e804492b6e4be3bd42, fetched
15 Nov 2026). Every quote below was checked against that file's text; "…" marks
words left out, and the PDF ligature glyphs (ff, fi, ffi, fl) are written as
plain letters. Page numbers are the PDF pages as rendered: a plain text dump of
this file puts some text a page early, because its layout layers overlap. Other
versions of the SOP exist (courts cite copies dated 02.01.2026 and 10.04.2026);
the officer should check the current one.

Only bank holds get reminders. Annexure I (the hold notice under s.168 read with
s.94 BNSS) is addressed to a bank, and section 10.1 covers grievances about an
amount "put on hold effected by NCRP-CFCFRMS" at a bank or FI. The register does
not record whether a hold went through CFCFRMS, so each reminder says "if".

Left out, because this copy states no clear time limit for them:
  - informing the Magistrate of a hold: the SOP gives no number of hours or days
    (its process steps say "forthwith", for the s.106(3) BNSS report);
  - holds at an exchange or by a token's issuer (section 9.4 sets none).
Time limits that start from an event the register does not record (the
complaint, a grievance) are shown without a date.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

SOP_URL = "https://www.zoroastrianbank.bank.in/download/SOP-NCRP.pdf"
SOP_COPY = "copy dated 11 Feb 2026"
SOP_NAME = "MHA SOP for NCRP-CFCFRMS"
NOT_ENFORCED = ("A reminder of what the SOP says, quoted from one copy. Not a deadline Exchequer enforces; "
                "check the current SOP and the law.")

# section, PDF page of the copy above, the words quoted, and (for the one limit
# the register can date) how many days after `seized_on` it falls.
BANK_HOLD = [
    {
        "id": "annex1-90-days",
        "section": "Annexure I, para 3",
        "page": 34,
        "quote": ("the bank may remove the hold, after completion of 90 calendar days from the date of "
                  "amount put on hold"),
        "context": "if conditions (a) to (d) of that paragraph are met",
        "days_after_hold": 90,
    },
    {
        "id": "s10-1e-15-days",
        "section": "§10.1(e)",
        "page": 24,
        "quote": ("If the IO or Police Officer is not satisfied with the explanation submitted by the aggrieved "
                  "person, she shall submit her remarks on the Grievance Redressal Module within 15 calendar days "
                  "of raising the grievance by the bank"),
        "context": "if the account holder raises a grievance about the hold",
    },
    {
        "id": "s10-1f-2-days",
        "section": "§10.1(f)",
        "page": 24,
        "quote": ("As instructed by the District Grievance Officer, the IO or Police Officer shall take appropriate "
                  "action and update the portal within 2 calendar days. Banks and FIs should furnish the requested "
                  "information at the earliest and not later than 2 calendar days"),
        "context": "once a grievance reaches the District Grievance Officer",
    },
    {
        "id": "s10-1-extension",
        "section": "§10.1, closing paragraph",
        "page": 24,
        "quote": ("Before carrying out the discontinuation of the hold, intimation will be sent to the SHO at least "
                  "15 calendar days before the date of expiry of the 90 calendar days from the date of raising the "
                  "grievance. … they may ask for an extension for continuation for up to 90 additional calendar "
                  "days."),
        "context": "if the hold has been contested through the grievance module",
    },
    {
        "id": "s6-1k-1-week",
        "section": "§6.1(k)",
        "page": 13,
        "quote": ("If the amount is put on hold, the bank or FI will also update the account related KYC details "
                  "… of the beneficiary account holder within 1 week of reporting."),
        "context": "the bank's step, for the officer to check",
    },
]


def hint(r: dict[str, Any]) -> str:
    """The line the screen shows: where it comes from, then the SOP's words."""
    return f"Reminder, per {SOP_NAME} {r['section']} ({SOP_COPY}): “{r['quote']}” ({r['context']})."


def for_asset(holder: str, status: str, seized_on: str) -> list[dict[str, Any]]:
    """The SOP reminders for one register row: bank holds still held, else none."""
    if holder != "bank" or status != "held":
        return []
    held = date.fromisoformat(seized_on)
    out = []
    for r in BANK_HOLD:
        days = r.get("days_after_hold")
        out.append({
            "id": r["id"], "section": r["section"], "page": r["page"], "quote": r["quote"],
            "hint": hint(r), "date": (held + timedelta(days=days)).isoformat() if days else None,
            "date_label": f"Day {days} from the date seized recorded here" if days else None,
            "source_url": SOP_URL, "copy": SOP_COPY, "reminder_only": True, "note": NOT_ENFORCED,
        })
    return out
