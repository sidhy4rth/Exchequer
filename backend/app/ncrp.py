"""The usual shape of an NCRP acknowledgement number, as a soft note only.

Source: MHA, "SOP for NCRP-CFCFRMS, Custody, Restoration of Money &
Grievance Redressal", paragraphs 6.1(d) and 6.2(c): a complaint made on the
portal (cybercrime.gov.in) gets a 14-digit acknowledgement number starting
with "2"; one made through the 1930 helpline gets a 14-digit number starting
with "3". Read from a copy of the SOP that a bank publishes
(https://www.zoroastrianbank.bank.in/download/SOP-NCRP.pdf), the same SOP
the Meghalaya High Court notified on 28.04.2026
(https://meghalayahighcourt.nic.in/notification-28042026-sop-national-cybercrime-reporting-portal-and-citizen-financial-fraud).

This never refuses a number and never changes one. Older complaints, or
numbers issued another way, may not fit, and nothing published says they
cannot exist; the limits each form already applies (pipeline.py,
citizen/api/_lib/complaint.py) stay as they are. The same rule is in
frontend/src/ncrp.js and citizen/src/api.js (ncrpNote).

The note is a fixed sentence: it never repeats the number, so it can be
shown or returned without the number reaching a log or the audit trail.
"""
from __future__ import annotations

import re

NOTE = "NCRP acknowledgement numbers are usually 14 digits starting with 2 or 3 — check the number."

# 14 digits: "2" for the portal (SOP 6.1(d)), "3" for 1930 (SOP 6.2(c)).
USUAL = re.compile(r"[23][0-9]{13}")


def shape_note(value: str | None) -> str | None:
    """NOTE when `value` is given but is not the SOP's usual shape, else None.

    Spaces and hyphens are ignored, as the citizen site ignores them.
    """
    if not isinstance(value, str):
        return None
    text = re.sub(r"[\s-]", "", value)
    if not text:
        return None
    return None if USUAL.fullmatch(text) else NOTE
