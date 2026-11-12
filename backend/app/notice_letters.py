"""Draft notices to a bank and to a telecom operator (suite feature 7).

An exchange's reply is where the money trail leaves the chain: the account the
exchange paid out to, the phone number on the customer's account. The officer's
next letters go there. Like request_letters.py, this module drafts and does not
decide: it fills in only what the case holds and what the officer typed, leaves
the legal provision as a marked blank with a bracketed suggestion, and says on
every draft that it is not valid until an officer signs it.

Three notices:

  bank-info    to a bank: who holds the account, its statement for a period,
               what is linked to it, and its login records
  bank-freeze  to a bank, urgent: a debit freeze on the account. Freezing a
               bank account is an attachment of money, which courts have held
               the police cannot order on their own (BNSS s.106 seizes evidence;
               s.107 attaches proceeds of crime on a Magistrate's order). So the
               draft is refused without the order it rests on, and, like every
               "-freeze" letter, waits for a second officer's sign-off
               (freeze_requests.py).
  telecom      to a telecom operator: the subscriber behind a number, and its
               call and IP records for a period

The account number, IFSC and phone number are personal data. They are checked,
written into the letter, and kept nowhere else: the route takes them in the
request body (never the URL), names the file by case and notice, and records
only which notice was drafted.
"""
from __future__ import annotations

import re
import textwrap
from datetime import date
from typing import Any

from .display_text import one_line, short
from .request_letters import BLANK, SIGN_OFF, _attribution, _cleaned, _freeze_header, _header

BANK_INFO = "bank-info"
BANK_FREEZE = "bank-freeze"  # urgent: "-freeze", so freeze_requests asks a second officer to sign it off
TELECOM = "telecom"
NOTICES = (BANK_FREEZE, BANK_INFO, TELECOM)  # the urgent one first, as with the exchange letters

IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")  # RBI: four letters, a zero, six letters or digits
ACCOUNT_RE = re.compile(r"^[0-9]{6,20}$")
PHONE_RE = re.compile(r"^(?:\+?91|0)?([6-9][0-9]{9})$")  # an Indian mobile number, with or without +91 / 0
NAME_MAX, TEXT_MAX = 100, 200
AMOUNT_MAX = 1e12


class NoticeError(ValueError):
    """What the officer typed is missing or malformed; the message says which."""


def _text(details: dict[str, Any], key: str, what: str, limit: int, required: bool = True) -> str:
    """Typed text on one line, so it cannot add lines (a forged "To:") to the letter."""
    value = one_line(details.get(key) or "").strip()
    if required and not value:
        raise NoticeError(f"Enter {what}.")
    if len(value) > limit:
        raise NoticeError(f"{what[0].upper()}{what[1:]} is longer than {limit} characters.")
    return value


def _period(details: dict[str, Any]) -> tuple[date, date]:
    try:
        start = date.fromisoformat(str(details.get("period_from") or ""))
        end = date.fromisoformat(str(details.get("period_to") or ""))
    except ValueError as exc:
        raise NoticeError("Enter the period as two dates, YYYY-MM-DD.") from exc
    if start > end:
        raise NoticeError("The period starts after it ends.")
    return start, end


def _day(d: date) -> str:
    return d.strftime("%d %b %Y")


def _bank(details: dict[str, Any]) -> dict[str, Any]:
    account = re.sub(r"\s+", "", str(details.get("account") or ""))
    if not ACCOUNT_RE.match(account):
        raise NoticeError("Enter the account number as 6 to 20 digits.")
    ifsc = str(details.get("ifsc") or "").strip().upper()
    if not IFSC_RE.match(ifsc):
        raise NoticeError("Enter the IFSC: four letters, a zero, then six letters or digits.")
    return {"bank": _text(details, "bank", "the bank's name", NAME_MAX), "account": account, "ifsc": ifsc,
            "source": _text(details, "source", "where the account came from (for example the exchange's reply)",
                            TEXT_MAX)}


def _phone(details: dict[str, Any]) -> str:
    m = PHONE_RE.match(re.sub(r"[\s-]+", "", str(details.get("phone") or "")))
    if not m:
        raise NoticeError("Enter a 10-digit Indian mobile number.")
    return m.group(1)


def _wrap(text: str, indent: str = "   ") -> list[str]:
    return textwrap.wrap(text, width=95, initial_indent=indent, subsequent_indent=indent,
                         break_long_words=False, break_on_hyphens=False)


def _with_gap(lines: list[str]) -> list[str]:
    return [*lines, ""] if lines else []


def _case_line(result: dict[str, Any]) -> list[str]:
    """What the case says about where the money went, when it reached an exchange."""
    found = _attribution(result)
    if not found:
        return []
    return _wrap(f"The case traces the complainant's funds on chain to {short(found['trace']['exchange'], 60)}, "
                 "whose records led this office to the details below.")


PROVISION = [f"2. In exercise of the powers under {BLANK}",
             "   [e.g. Section 94 of the Bharatiya Nagarik Suraksha Sanhita, 2023 — officer to confirm],"]


def _bank_info(case_id: str, result: dict[str, Any], details: dict[str, Any]) -> str:
    b, (start, end) = _bank(details), _period(details)
    lines = _header(case_id, result, f"The Nodal Officer, {b['bank']}",
                    f"Request for information about account {b['account']}")
    lines += [*_with_gap(_case_line(result)),
              f"1. Account   : {b['account']}", f"   IFSC      : {b['ifsc']}", f"   Bank      : {b['bank']}",
              *_wrap(f"Source    : {b['source']}"), "",
              *PROVISION,
              "   you are requested to provide, for the account above:",
              "   (a) the account opening form and KYC documents of every holder and nominee;",
              f"   (b) the statement of account from {_day(start)} to {_day(end)};",
              "   (c) linked accounts, UPI IDs, cards, and the registered mobile number and e-mail;",
              f"   (d) internet and mobile banking login records (IP address, device, time) from {_day(start)}",
              f"       to {_day(end)}.", "",
              "3. Please treat this request as confidential and do not inform the account holder.", "",
              *SIGN_OFF]
    return "\n".join(lines) + "\n"


def _bank_freeze(details: dict[str, Any], approval: dict[str, Any] | None) -> str:
    order = _text(details, "order", "the Magistrate's order this hold rests on (number, date and court)",
                  TEXT_MAX, required=False)
    if not order:
        raise NoticeError("A bank hold attaches money, which needs a Magistrate's order: enter its number, "
                          "date and court.")
    b = _bank(details)
    amount = details.get("amount")
    if amount in (None, ""):
        stated = [f"Amount    : {BLANK} (officer to state)"]
    else:
        if isinstance(amount, bool):
            raise NoticeError("Enter the amount as a number of rupees.")
        try:  # "2,50,000" and "250 000" are how officers write it
            value = float(re.sub(r"[,\s]", "", str(amount)))
        except ValueError as exc:
            raise NoticeError("Enter the amount as a number of rupees.") from exc
        if not 0 < value < AMOUNT_MAX:  # also refuses nan and inf
            raise NoticeError("Enter an amount of rupees above zero and below one lakh crore.")
        stated = [f"Amount    : up to INR {value:,.2f}"]
    ask = f"Please place a debit freeze, now, on account {b['account']} (IFSC {b['ifsc']}) up to the amount below"
    lines = _freeze_header(f"The Nodal Officer, {b['bank']}", f"debit freeze on account {b['account']}", ask, approval)
    lines += [f"Account   : {b['account']}", f"IFSC      : {b['ifsc']}", *stated,
              *_wrap(f"Order     : {order} (copy attached)", indent=""),
              *_wrap(f"Source    : {b['source']}", indent=""), "",
              "Please confirm the hold and the balance held to the contact above.",
              *SIGN_OFF]
    return "\n".join(lines) + "\n"


def _telecom(case_id: str, result: dict[str, Any], details: dict[str, Any]) -> str:
    operator = _text(details, "operator", "the operator's name", NAME_MAX)
    phone, (start, end) = _phone(details), _period(details)
    source = _text(details, "source", "where the number came from (for example the exchange's reply)", TEXT_MAX)
    lines = _header(case_id, result, f"The Nodal Officer, {operator}",
                    f"Request for subscriber details and records of mobile number {phone}")
    lines += [*_with_gap(_case_line(result)),
              f"1. Number    : {phone}", f"   Operator  : {operator}", *_wrap(f"Source    : {source}"), "",
              *PROVISION,
              "   you are requested to provide, for the number above:",
              "   (a) subscriber details and the customer application form (CAF) with its KYC documents;",
              f"   (b) call detail records (CDR) from {_day(start)} to {_day(end)};",
              f"   (c) IP detail records (IPDR) from {_day(start)} to {_day(end)}.", "",
              "3. Please treat this request as confidential and do not inform the subscriber.", "",
              *SIGN_OFF]
    return "\n".join(lines) + "\n"


def draft(case_id: str, result: dict[str, Any], to: str, details: dict[str, Any],
          approval: dict[str, Any] | None = None) -> str:
    """The notice `to` for the case, from the officer's `details`. A bank hold
    says whether a second officer approved it (`approval`: {"by", "at"})."""
    if to not in NOTICES:
        raise NoticeError(f"Unknown notice '{to}'. Expected one of: {', '.join(NOTICES)}.")
    result = _cleaned(result)
    if to == BANK_FREEZE:
        return _bank_freeze(details, approval)
    if to == BANK_INFO:
        return _bank_info(case_id, result, details)
    return _telecom(case_id, result, details)
