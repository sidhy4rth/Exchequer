"""The case bundle: one zip of what a case already holds, for handing over (suite feature 6, #186).

The signed report (text and PDF, the very bytes the report download serves), each
register of the case as CSV with its history, the case's audit trail, and
MANIFEST.txt: every file's name, size and SHA-256, what it is and where it came
from, the case, who downloaded it and when, and how to check the report at /verify.

Nothing is rendered differently and nothing is added that the caller cannot
already read: each register is read with its own list_for() as its own route
reads it for this caller, and the audit trail goes in only for whom /audit shows
it. The s.63(4) certificate drafts stay out: they are drafts the officer fills in.

Each CSV starts with a UTF-8 byte order mark (Excel), and a cell starting like a
formula gets a leading apostrophe (graph_export._cell); MANIFEST.txt says both.
Files go in the order of PARTS, then MANIFEST.txt. The zip is written to a
spooled temporary file (on disk past SPOOL_BYTES), one file in memory at a time,
and refused past MAX_BYTES, so a large case cannot exhaust the server's memory.

A register added later adds itself with one add_register() call at the bottom
of this module; nothing else changes.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import IO, Any, Callable, Iterator

from . import assets, audit, case_privacy, config, exhibits, freeze_requests, identifiers, ownership, report_cache
from .graph_export import _cell
from .models import Case
from .signing import get_signer

MAX_BYTES = 64 * 1024 * 1024  # all files together, before compression
SPOOL_BYTES = 8 * 1024 * 1024
CHUNK = 64 * 1024
# The audit trail in full, not the first 1000 events GET /audit shows; past this many
# (far more than a case gathers) MANIFEST.txt says the file holds only the first ones.
AUDIT_ROWS_MAX = 20_000
IST = timezone(timedelta(hours=5, minutes=30), "IST")
CERTIFICATES_LEFT_OUT = ("s.63(4) certificate drafts", "drafts the officer completes; draft them from the "
                         "Evidence tab")
AUDIT_WITHHELD = "only the browser or unit that traced the case can read its audit log"


class TooLarge(ValueError):
    """The bundle would pass MAX_BYTES."""


@dataclass
class Request:
    """Who asked for which case: `case` is the copy this caller reads (case_privacy), `stored` the case."""

    case: Case
    stored: Case
    user: Any
    viewer: str | None               # the owner key the caller reads the case with (ownership.reader)
    owner: bool                      # the browser or unit that traced it (what /audit asks)
    pdf: Callable[[Case], bytes]     # the report download's own PDF, rate limits and all
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # each register, read once
    notes: list[str] = field(default_factory=list)  # what MANIFEST.txt must say about a file, e.g. cut short


@dataclass(frozen=True)
class Part:
    name: str
    about: str
    source: str
    build: Callable[[Request, int], bytes | None]   # (request, bytes left) -> the file, or None: withheld
    withheld: str = ""                               # why, in MANIFEST.txt, when build gives None


PARTS: list[Part] = []


def allowed(stored: Case, user: Any) -> tuple[bool, str | None]:
    """(may this caller bundle the case, the owner key they read it with): the
    browser or unit that traced it, or anyone for a public demo case, whose
    report anyone may download."""
    viewer = ownership.reader(stored, user)
    if case_privacy.is_owner(stored.owner_hash, viewer):
        return True, viewer
    return ownership.is_public(stored.owner_hash, stored.address), viewer


def _cap(data: bytes, left: int) -> bytes:
    if len(data) > left:
        raise TooLarge(len(data))
    return data


def _csv(header: list[str], rows: Iterator[list[Any]], left: int) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v) for v in row])
        if out.tell() > left:  # characters: never more than bytes, so this stops no later than the cap
            raise TooLarge(out.tell())
    # With a byte order mark, Excel opens the file as UTF-8 (names in Devanagari, the rupee sign), not as
    # the local code page; other spreadsheets and csv readers that decode utf-8-sig skip it.
    return _cap(out.getvalue().encode("utf-8-sig"), left)


def _history(id_key: str, rows: list[dict[str, Any]]) -> Iterator[list[Any]]:
    for row in rows:
        for entry in row.get("history") or []:
            rest = {k: v for k, v in entry.items() if k not in ("at", "by", "action")}
            yield [row[id_key], entry.get("at"), entry.get("by"), entry.get("action"), rest or ""]


def add_register(name: str, about: str, source: str, id_key: str, columns: tuple[str, ...],
                 rows: Callable[[Request], list[dict[str, Any]]], history: str = "history") -> None:
    """A register as two CSV files: `name`.csv, one row per record, and
    `name`-`history`.csv, one row per history entry (who, when, what)."""
    def read(r: Request) -> list[dict[str, Any]]:
        if name not in r.rows:
            r.rows[name] = rows(r)
        return r.rows[name]

    PARTS.append(Part(f"{name}.csv", about, source,
                      lambda r, left: _csv(list(columns), ([row.get(c) for c in columns] for row in read(r)), left)))
    PARTS.append(Part(f"{name}-{history}.csv", f"{about}: every change, with who made it and when", source,
                      lambda r, left: _csv([id_key, "at", "by", "action", "details"], _history(id_key, read(r)), left)))


def _audit(r: Request, left: int) -> bytes | None:
    if not r.owner:
        return None
    user, case = r.user, r.stored  # as GET /audit reads it
    unit = user.unit_id if user.unit_id is not None and case.unit_id == user.unit_id else None
    events = audit.events_for(case.id, r.viewer, limit=AUDIT_ROWS_MAX + 1, officer_id=user.officer_id, unit_id=unit)
    if len(events) > AUDIT_ROWS_MAX:
        events = events[:AUDIT_ROWS_MAX]
        r.notes.append(f"audit-trail.csv holds the first {AUDIT_ROWS_MAX} events of the case's audit log, oldest "
                       "first; the later ones are not in this bundle.")
    cols = ["seq", "at", "actor", "unit_id", "action", "case_id", "detail", "prev_hash", "row_hash"]
    return _csv(cols, ([e.get(c) for c in cols] for e in events), left)


PARTS += [
    Part("report.txt", "Exchequer's report of the case, signed by this server",
         "the report download (GET /trace/{id}/report?format=text)",
         lambda r, left: _cap(report_cache.text(r.case).encode("utf-8"), left)),
    Part("report.pdf", "the same report as a PDF: a summary page, then the signed text, attached",
         "the report download (GET /trace/{id}/report?format=pdf)", lambda r, left: _cap(r.pdf(r.case), left)),
]
add_register("exhibits", "the exhibit register: files outside forensic tools produced for the case",
             "the exhibit register (GET /trace/{id}/exhibits)", "exhibit_id",
             ("exhibit_id", "case_id", "kind", "kind_label", "label", "tool", "file_name", "size_bytes", "sha256",
              "sha1", "md5", "made_by", "made_on", "stored_at", "holder", "status", "notes", "created_at", "updated_at"),
             lambda r: exhibits.list_for(r.user, r.case.id), history="custody")
add_register("assets", "the asset register: what was frozen or seized, and its court deadline",
             "the asset register (GET /trace/{id}/assets)", "asset_id",
             ("asset_id", "case_id", "holder", "holder_label", "asset", "amount", "chain", "held_at", "tx_hash",
              "key_holders", "request_id", "seized_on", "order_ref", "status", "outcome_ref", "outcome_tx", "notes",
              "deadline", "created_at", "updated_at"),
             lambda r: assets.list_for(r.user, r.case.id))
add_register("requests", "the requests log: freeze and information requests sent for the case",
             "the requests log (GET /trace/{id}/requests)", "request_id",
             ("request_id", "case_id", "recipient", "kind", "status", "address", "asset", "reference", "sent_at",
              "amount_frozen", "notes", "signoff", "created_at", "updated_at"),
             lambda r: freeze_requests.list_for(r.user.owner_hash, case_id=r.case.id, viewer=r.user)
             if r.user.owner_hash else [])
add_register("identifiers", "the case identifiers: phone numbers, handles, domains and accounts named in the case",
             "the case identifiers (GET /trace/{id}/identifiers)", "identifier_id",
             ("identifier_id", "case_id", "kind", "kind_label", "value", "entered", "context", "notes", "status",
              "created_at", "updated_at"),
             lambda r: identifiers.list_for(r.user, r.case.id))
PARTS.append(Part("audit-trail.csv", "the case's audit trail: who read, exported or changed it, hash-chained",
                  "the audit log (GET /audit?case_id={id})", _audit, AUDIT_WITHHELD))


def names() -> list[str]:
    return [p.name for p in PARTS] + ["MANIFEST.txt"]


def _manifest(r: Request, made: list[tuple[Part, int, str]], withheld: list[Part], now: datetime) -> bytes:
    site = config.PUBLIC_URL
    signer = get_signer()
    lines = [
        "Exchequer case bundle", "",
        f"Case: {r.case.id}",
        f"Downloaded by: {r.user.id} ({r.user.unit})",
        f"Downloaded at: {now.isoformat(timespec='seconds')} ({now.astimezone(IST).strftime('%d %b %Y %H:%M IST')})",
        f"Issued by: {site or 'this server (its public address is not configured)'}",
        f"Report signing key: Ed25519, SHA-256 fingerprint {signer.fingerprint_sha256}", "",
        "The SHA-256 of each file below was taken as the file was put in this bundle. Anyone can hash a",
        "file again (sha256sum FILE; on Windows, certutil -hashfile FILE SHA256) and compare: the same hash",
        "shows the file is unchanged since download. The hashes say nothing about whether what a file",
        "records is right, and this manifest is not signed. The report is: check report.txt or report.pdf",
        f"at {site or 'this server'}/verify. The registers and the audit trail are the case's records as",
        "this caller could read them on the case page at the time of download.", "",
        "Each CSV file starts with a UTF-8 byte order mark, so Excel reads its characters right. A cell",
        "that starts with =, +, - or @ is written with a leading apostrophe, so a spreadsheet shows it as",
        "text and never runs it as a formula: a +91 phone number reads '+91 in the file.", "",
        "Files, in the order they are in the bundle:", "",
    ]
    for n, (part, size, digest) in enumerate(made, 1):
        lines += [f"{n}. {part.name}", f"   Size: {size} bytes", f"   SHA-256: {digest}",
                  f"   What it is: {part.about}", f"   Where it came from: {part.source}", ""]
    if r.notes:
        lines += ["Notes:"] + [f"- {n}" for n in r.notes] + [""]
    lines += ["Left out:"]
    lines += [f"- {p.name}: {p.withheld}" for p in withheld]
    lines += [f"- {CERTIFICATES_LEFT_OUT[0]}: {CERTIFICATES_LEFT_OUT[1]}", ""]
    return "\n".join(lines).encode("utf-8")


def build(r: Request, now: datetime | None = None) -> tuple[IO[bytes], int]:
    """(the zip, rewound, and how many files it holds). Raises TooLarge."""
    now = now or datetime.now(tz=timezone.utc)
    stamp = now.astimezone(IST).timetuple()[:6]
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)  # noqa: SIM115 -- closed by the route's response
    made: list[tuple[Part, int, str]] = []
    withheld: list[Part] = []
    left = MAX_BYTES
    try:
        with zipfile.ZipFile(spool, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for part in PARTS:
                data = part.build(r, left)
                if data is None:
                    withheld.append(part)
                    continue
                left -= len(data)
                made.append((part, len(data), hashlib.sha256(data).hexdigest()))
                zf.writestr(zipfile.ZipInfo(part.name, stamp), data, compress_type=zipfile.ZIP_DEFLATED)
                del data
            zf.writestr(zipfile.ZipInfo("MANIFEST.txt", stamp), _manifest(r, made, withheld, now),
                        compress_type=zipfile.ZIP_DEFLATED)
    except BaseException:
        spool.close()
        raise
    spool.seek(0)
    return spool, len(made) + 1


def stream(spool: IO[bytes]) -> Iterator[bytes]:
    try:
        while chunk := spool.read(CHUNK):
            yield chunk
    finally:
        spool.close()
