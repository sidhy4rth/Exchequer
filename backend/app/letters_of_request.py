"""Draft a letter of request to a foreign country from a stored case (suite feature 7).

When the exchange that holds the traced money is abroad and does not answer a
notice, its records have to come through a letter of request: a Criminal Court
issues it, on the investigating officer's application, to the competent
authority of the country where the evidence is (BNSS s.112; CrPC s.166A before
the BNSS, per NCRB's BNSS-CrPC table), and the Central Government transmits it.

This drafts that letter in the format the Ministry of Home Affairs prescribes
(F. No. 25016/52/2019-LC, 4 December 2019, Figure 3.5), section by section:
the request's basis, its nature, the offences, limitation, the statement of
facts, its purpose, the assistance requested, the mandatory assurances,
limitation of use, execution, period, confidentiality and liaison. The MHA's own
fixed wording is read from data/mha_letter_of_request.txt, with its source.

Like request_letters.py, it drafts and does not decide:

* What the case holds fills the facts: the victim's payments, each hop with its
  amounts, times and hashes, the exchange address and what is known about it,
  the amount, and any request already sent to that exchange (the requests log).
* What only the officer or the Court can say (the court, the requested country,
  the treaty or the assurance of reciprocity, the offences and their penalties,
  limitation, the narrative of the fraud) comes from the officer's details or is
  a marked blank. The legal provision is suggested in brackets, never asserted.
* Notes for the officer come first, and are marked to be removed: the route the
  MHA's guidelines set (concurrence of the MHA's IS-II Division first, then the
  Court, then the CBI's IPCC), what goes with the draft, and whether the MHA's
  2019 list of treaty countries (Figure 3.6, data/mha_mlat_countries.txt) names
  the requested country. The basis stays the officer's choice either way.

Every draft says it is not valid until the Court issues it under its seal.
"""
from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path
from typing import Any

from .display_text import one_line
from .report import (EXCHANGE_WALLET, EXPLORER_TAG, INFERRED_DEPOSIT, _amount, _paid_at, _when, _when_iso,
                     attribution_kind)
from .request_letters import (BLANK, COMPANY_WALLET_KINDS, _amount_lines, _attribution, _claim, _cleaned,
                              _company_listed, _left_out, _letter_amount, _path_lines, _today, _transfers_into,
                              _verify_lines)

WORDING_FILE = Path(__file__).resolve().parent.parent / "data" / "mha_letter_of_request.txt"
# Figure 3.6 of the same guidelines: the countries with a treaty or agreement with India, as listed in 2019.
COUNTRIES_FILE = Path(__file__).resolve().parent.parent / "data" / "mha_mlat_countries.txt"
SECTIONS = ("opening", "basis_treaty", "basis_reciprocity", "assurances", "limitation_of_use", "confidentiality",
            "closing")
BASES = ("treaty", "reciprocity")
WIDTH = 95
# What the officer may type, and its limit. All optional: what is missing is a marked blank.
FIELDS = {
    "country": 80, "authority": 200, "court": 200, "presiding": 120, "basis": 16, "treaty": 300,
    "agency": 200, "reference": 120, "proceedings": 300, "offences": 1500, "limitation": 500, "facts": 4000,
    "exchange_office": 300, "period": 300, "liaison": 500,
}
NOT_VALID = "This is a DRAFT. It is not a letter of request until the Court issues it under its seal."
SENT_STATUSES = ("sent", "acknowledged", "frozen", "declined", "closed")


class LetterOfRequestError(ValueError):
    """The case or what the officer typed cannot make this letter; the message says which."""


def _wording() -> dict[str, str]:
    text = WORDING_FILE.read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current and not line.startswith("#"):
            sections[current].append(line)
    out = {k: "\n".join(v).strip() for k, v in sections.items()}
    missing = [s for s in SECTIONS if not out.get(s)]
    if missing:
        raise RuntimeError(f"data/mha_letter_of_request.txt lacks {', '.join(missing)}")
    return out


def wording_sha256() -> str:
    """The wording file's SHA-256: test_letters_of_request.py pins it, so a change to the MHA's
    wording is deliberate and reviewed."""
    return hashlib.sha256(WORDING_FILE.read_bytes()).hexdigest()


def countries_sha256() -> str:
    """The country list's SHA-256, pinned in test_mlat_countries.py like the wording."""
    return hashlib.sha256(COUNTRIES_FILE.read_bytes()).hexdigest()


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


def treaty_countries() -> list[dict[str, str]]:
    """Figure 3.6's rows: name, formal name (may be empty), instrument and year, status."""
    rows = []
    for line in COUNTRIES_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, formal, instrument, status = (part.strip() for part in line.split("|"))
            rows.append({"name": name, "formal": formal, "instrument": instrument, "status": status})
    return rows


def listed_country(country: str) -> dict[str, str] | None:
    """The row whose name or formal name is exactly the officer's country (ignoring case and spacing);
    no fuzzy match, so a spelling the MHA did not print is not guessed at."""
    key = _key(country)
    return next((r for r in treaty_countries() if key and key in (_key(r["name"]), _key(r["formal"]))), None)


def _country_note(country: str) -> list[str]:
    """Whether the MHA's 2019 list names the requested country: a note for the officer, never the letter,
    and never a choice of basis."""
    if not country:
        return []
    row = listed_country(country)
    if row is None:
        return _para(f"Treaty: {country} is not on the MHA's 2019 list (Figure 3.6) under that name; check the "
                     "list for another spelling. If it is not there, reciprocity may be the route; confirm with "
                     "the MHA (IS-II Division).", "  ")
    status = ("; the list marks it signed but not yet in force, so confirm whether it is now in force and, if "
              "it is, name it" if row["status"] != "listed" else "; confirm it is still in force and name it")
    return _para(f"Treaty: the MHA's 2019 list (Figure 3.6) names {row['name']} among countries with a "
                 f"treaty/agreement ({row['instrument']}){status}. The list may have changed since; the MHA's "
                 "IS-II Division confirms.", "  ")


def _details(raw: dict[str, Any]) -> dict[str, str]:
    """The officer's details, each on one line (so none can add a line, a forged heading, to the
    letter) and within its limit."""
    out = {}
    for key, limit in FIELDS.items():
        value = one_line(str(raw.get(key) or "")).strip()
        if len(value) > limit:
            raise LetterOfRequestError(f"'{key}' is longer than {limit} characters.")
        out[key] = value
    if out["basis"] and out["basis"] not in BASES:
        raise LetterOfRequestError(f"basis must be one of {', '.join(BASES)}, or left empty.")
    if out["basis"] == "treaty" and not out["treaty"]:
        raise LetterOfRequestError("Name the treaty or convention the request is made under.")
    return out


def _or_blank(value: str, hint: str) -> str:
    return value or f"{BLANK} ({hint})"


def _para(text: str, indent: str = "   ") -> list[str]:
    return textwrap.wrap(text, width=WIDTH, initial_indent=indent, subsequent_indent=indent,
                         break_long_words=False, break_on_hyphens=False) or [indent.rstrip()]


def _heading(title: str) -> list[str]:
    return ["", title, "-" * len(title)]


def _notes(exchange: str, country: str = "") -> list[str]:
    """For the officer, before the letter: the MHA's route and what goes with the draft."""
    src = "MHA guidelines of 4 December 2019 (F. No. 25016/52/2019-LC)"
    return [
        "NOTES FOR THE OFFICER — remove this part before the draft goes to the Court.",
        *_para(f"Route ({src}, Figure 2.2): (1) the draft request, with the documents below, goes to the "
               "Under Secretary (Legal Cell), IS-II Division, Ministry of Home Affairs (the Central Authority of "
               "India) for concurrence, routed through the State's Home Department for State Police; "
               "(2) once concurred, the officer applies to the Court of competent jurisdiction, which may issue "
               "the letter under its seal; (3) once issued, three copies go to the Assistant Director (IPCC), "
               "CBI, and one copy to the IS-II Division, MHA, for transmission.", "  "),
        *_para("With the draft for concurrence (Figure 3.2): the legal opinion of the Director of Prosecution "
               "or a senior law officer; a copy of the application to the Court; the FIR, with an English "
               "translation if it is in another language; extracts of the sections of Indian law relied on, "
               "including the law on limitation; the applicable laws of the requested country; the contact "
               "details of the officer; any other document related to the evidence sought.", "  "),
        *_para("Language (para 3.4): in English, with a translation certified by the translator into the "
               "language the requested country requires, where it requires one. Figure 3.6 of the guidelines "
               "lists the countries with a treaty with India, their Central Authorities and their language "
               "requirements: check it, and the MHA's current list, for this country.", "  "),
        *_country_note(country),
        *_para("The guidelines name CrPC s.166A as the power to issue the letter; its successor is BNSS s.112 "
               "(NCRB's BNSS-CrPC table). Confirm the provision with the Director of Prosecution.", "  "),
        *_para(f"Before this letter: a direct request to {exchange} is quicker where it answers one. Exchequer's "
               "other letters draft it.", "  "),
        "",
        "=" * WIDTH,
    ]


def _payments(result: dict[str, Any]) -> list[str]:
    intake = result.get("intake") or {}
    payments = (intake.get("payments") or []) if intake.get("mode") == "payment" else []
    asset = result.get("asset")
    if not payments:
        return _para(f"The victim's payments: {BLANK} (officer to state amounts, dates and references from the "
                     "complaint). The trace followed the reported address's history, not specific payments.")
    lines = [*_para(f"The victim's payments, as verified on the public blockchain ({len(payments)}):")]
    for p in payments:
        lines += [f"     {_amount(p.get('amount'))} {asset}, {_paid_at(p)}", f"       tx {p.get('tx_hash')}"]
    return lines


def _earlier(requests: list[dict[str, Any]], exchange: str) -> list[str]:
    """Requests already sent to the exchange, from the requests log: the guidelines ask whether a
    preservation request was made, and a refusal is why this letter is needed."""
    mine = [q for q in requests if (q.get("recipient") or "").strip().casefold() == exchange.casefold()
            and q.get("status") in SENT_STATUSES and q.get("sent_at")]
    if not mine:
        return [*_para(f"Records preserved: {BLANK} (officer to state whether {exchange} was asked to preserve "
                       "these records, when, and what it replied).")]
    lines = [f"   Requests already sent to {exchange} (from this case's requests log):"]
    for q in sorted(mine, key=lambda q: q["sent_at"]):
        ref = f", reference {one_line(q['reference'])}" if q.get("reference") else ""
        lines.append(f"     {str(q['sent_at'])[:10]}: {q.get('kind')} request{ref}; "
                     f"status {q['status'].replace('_', ' ')}")
    return lines


def _records(kind: str, exchange: str, address: str, office: str, since: str) -> list[str]:
    """Assistance (a): the records to be produced, worded for what the case holds about the address."""
    by = f"{exchange}{f' ({office})' if office else ''}"
    if kind == EXPLORER_TAG:
        return _para(f"(a) a statement from {by} confirming whether it controls the address {address} and, if it "
                     "does, production of certified copies of the records in (b) for the account or accounts "
                     "connected with the transfers in the Statement of Facts;")
    subject = (f"the customer account or accounts behind the transfers into {address} listed in the Statement "
               "of Facts, and no other (the address is a wallet the exchange operates itself)"
               if kind == EXCHANGE_WALLET else
               f"the account or accounts associated with the address {address}"
               + (f", if that address was issued by {exchange}" if kind == INFERRED_DEPOSIT else ""))
    return [
        *_para(f"(a) production by {by} of certified copies of the following records relating to {subject}, "
               f"for the period from {since} to the date of production:"),
        "       (i)   the account holder's identity and KYC documents;",
        "       (ii)  the account statement, and every deposit and withdrawal with its transaction hash;",
        "       (iii) linked bank accounts, cards and payment identifiers used for deposits or withdrawals;",
        "       (iv)  login records, with IP addresses and device identifiers;",
        "       (v)   any other deposit addresses issued to the same account;",
        *_para("together with the oral or written evidence of the person who keeps those records, confirming "
               "their position, that the records were made in the ordinary course of business, and that the "
               "copies are authentic, so that they can be proved in the proceedings in India;", "       "),
    ]


def draft(case_id: str, result: dict[str, Any], raw: dict[str, Any],
          requests: list[dict[str, Any]] | None = None) -> str:
    """The draft letter of request for the case, from its result, the officer's details and the
    case's requests log."""
    d = _details(raw)
    result = _cleaned(result)
    found = _attribution(result)
    if not found or result.get("direction", "outgoing") != "outgoing":
        raise LetterOfRequestError("This case reached no exchange, so there is no one abroad to ask for records.")
    w = _wording()
    trace, asset = found["trace"], found["asset"]
    exchange, address = trace["exchange"], trace["exchange_address"]
    kind = attribution_kind(trace)
    country = _or_blank(d["country"], "the requested country")
    into = _transfers_into(trace, address)
    manifest = (result.get("evidence") or {}).get("manifest_sha256")

    def fill(text: str, treaty: str = d["treaty"]) -> str:
        return (text.replace("{country}", country)
                .replace("{court}", _or_blank(d["court"], "the Court and its place"))
                .replace("{presiding}", _or_blank(d["presiding"], "name of the presiding officer of the Court"))
                .replace("{treaty}", treaty))

    lines = [
        "DRAFT — for the investigating officer and the Court to review, complete and issue.",
        NOT_VALID,
        "Generated by Exchequer from a stored case. Nothing below has been sent.",
        "",
        *_notes(exchange, d["country"]),
        "",
        "LETTER OF REQUEST (LETTER ROGATORY)",
        f"In the matter of {_or_blank(d['reference'], 'FIR / case number and police station')}",
        f"Date: {_today()}",
        "",
        *[ln for part in fill(w["opening"]).split("\n") for ln in _para(part, "")],
        *_para(f"Competent authority: {_or_blank(d['authority'], 'the authority in that country, if known')}", ""),
    ]

    lines += _heading("Request")
    if d["basis"] == "treaty":
        lines += _para(fill(w["basis_treaty"]))
    elif d["basis"] == "reciprocity":
        lines += _para(fill(w["basis_reciprocity"]))
    else:
        treaty = (f"{BLANK} [the relevant provisions of the Treaty between the Republic of India and {country}, or of "
                  "a convention or other agreement that applies]")
        lines += [*_para(f"{BLANK} (officer to keep one of the two, as the MHA's format offers):"),
                  *_para(fill(w["basis_treaty"], treaty) + " Or", "     "),
                  *_para(fill(w["basis_reciprocity"]), "     ")]

    lines += _heading("Nature of Request")
    lines += _para(f"This request relates to an investigation into cyber-enabled financial fraud, in which the "
                   f"proceeds were moved as cryptocurrency ({asset} on {result.get('chain_name')}) to an account "
                   f"at {exchange}. The authority conducting the investigation is "
                   f"{_or_blank(d['agency'], 'the police station or agency, and its address')}.")
    lines += _para(f"Judicial proceedings: {_or_blank(d['proceedings'], 'whether proceedings have been or are to be instituted, and before which Court')}.")

    lines += _heading("Criminal Offences / Applicable Legislation / Penalties")
    lines += _para(d["offences"] or f"{BLANK} (officer to set out the offences in the FIR, the maximum penalty for "
                   "each, and the identity of the suspect if known; attach the text of each provision).")

    lines += _heading("Period of Limitations")
    lines += _para(d["limitation"] or f"{BLANK} (officer to state that the offence is not time-barred, citing "
                   "the provision on limitation of Indian law).")

    lines += _heading("Statement of Facts")
    lines += _para(f"(a) {d['facts'] or BLANK + ' (officer to describe the fraud: how the victim was approached, what was promised, and when and how they paid)'}")
    lines += ["", *_para("(b) The movement of the money, from the public blockchain records:")]
    lines += _payments(result)
    stated = _letter_amount(result, found)
    # A wallet the exchange runs credits many customers: name only the transfers into it that can carry the
    # traced funds, as the exchange letter does, so no one else's account is asked about.
    listed, others, every = (_company_listed(trace, address, stated) if kind in COMPANY_WALLET_KINDS
                             else ([], 0, []))
    lines += ["", f"   Reported address: {result.get('address')}",
              *_path_lines(trace, asset, leave_out=address if every else None)]
    claim = " ".join(_claim(kind, trace, exchange).split())  # one paragraph: the claim is worded for a letter's lines
    lines += ["", *_para(f"The money reached the address {address}, {claim}")]
    if stated is not None:
        # Worded for a letter to the exchange; this one goes to the country's authority.
        lines += [f"   This is an estimate; {exchange}'s own records of the deposits are authoritative."
                  if ln.startswith("   This is an estimate;") else ln for ln in _amount_lines(asset, stated)]
    if every:
        lines += ["", *_para(f"The transfers into {address} that can carry the traced funds:" if others
                             else f"Every transfer into {address} in this trace:")]
        for t in listed:
            lines += [f"     {t.get('value_native', 0):,.6f} {asset}, {_when(t.get('timestamp'))}", f"       tx {t.get('hash')}"]
        lines += _left_out(others) if listed else [f"     {BLANK} (officer to add)"]
    lines += ["", *_para(f"(c) How the account was used in the offence: the traced funds were deposited to the "
                         f"account at {exchange} that this request concerns, which is why its records are "
                         f"expected to identify who received the proceeds and where they went next.")]
    lines += _earlier(requests or [], exchange)
    lines += _para(f"Every address and transaction above is listed in the attached Exchequer report for case "
                   f"{case_id}, traced {_when_iso(result.get('created_at'))}"
                   + (f", evidence manifest SHA-256 {manifest}" if manifest else "")
                   + ", and can be checked on a public block explorer.")
    lines += [f"   {x}" for x in _verify_lines()]

    lines += _heading("Purpose of the Request")
    lines += _para("To secure admissible evidence of the identity of the holder of the account to which the "
                   "proceeds of the offence were transferred, and of the onward movement of those proceeds, for "
                   "use in the investigation and prosecution in India; and to trace the proceeds of crime.")

    first = (listed or into)[:1]
    since = _when(first[0].get("timestamp")) if first else f"{BLANK} (the date of the first transfer)"
    lines += _heading("Assistance Requested")
    lines += _para(f"The Competent Authority of the Government of {country} is requested to take such steps as "
                   "are necessary for:")
    lines += _records(kind, exchange, address, d["exchange_office"], since)
    lines += _para(f"(b) assistance in tracing property suspected to be connected to the offence: the {asset} "
                   f"deposited to that account and its onward movement;")
    lines += _para("(c) the preservation of those records pending the execution of this request.")

    lines += _heading("Mandatory Assurance And Undertakings")
    lines += [ln for part in w["assurances"].split("\n") for ln in _para(part)]
    lines += _para("[The MHA's format adds (f), for a person whose attendance is requested, and (g), for an "
                   "offence punishable with death; add them only if they apply.]")

    lines += _heading("Limitation of Use")
    lines += _para(w["limitation_of_use"])

    lines += _heading("Execution of Request")
    lines += _para(f"{BLANK} (officer to state the manner and form in which the evidence is to be taken and sent, "
                   "any special requirement for certifying the documents, and whether an officer from India asks "
                   "to be present.) [e.g. the records as certified copies, electronic records with their hash "
                   "values, sent through the Central Authority]")

    lines += _heading("Period of Execution")
    lines += _para(d["period"] or f"{BLANK} (if urgent, the period within which execution is requested, and why: "
                   "for example, a hearing date).")

    lines += _heading("Confidentiality")
    lines += _para(w["confidentiality"])

    lines += _heading("Liaison")
    lines += _para(d["liaison"] or f"{BLANK} (name of the officer handling this request, address, telephone "
                   "number, e-mail address).")

    lines += ["", *_para(w["closing"], ""), "", BLANK, "(Signature along with seal)",
              f"Name of the Presiding Officer of the case: {_or_blank(d['presiding'], 'name')}",
              f"Office: {_or_blank(d['court'], 'the Court')}", "Date:", "",
              f"Attachment: Exchequer report for case {case_id} (text), with evidence manifest."]
    return "\n".join(lines) + "\n"
