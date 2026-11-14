"""A draft of the s.63(4) certificate for a case's exhibits (suite feature 6, issue #112).

An electronic record goes to court with the certificate in THE SCHEDULE of the
Bharatiya Sakshya Adhiniyam, 2023 [See section 63(4)(c)]: Part A filled by the
party producing it, Part B by an expert, each giving the source device and the
record's hash values, with a hash report enclosed.

This module drafts it and decides nothing:

* The wording is the Act's, read from data/bsa_schedule_certificate.txt, which
  scripts/fetch_bsa_schedule.py copies from India Code's PDF. Nothing here
  retypes it; a line this module fills is matched to the Schedule's own line,
  and a Schedule that changed stops the draft rather than misfill it.
* Part A gets the device particulars the officer typed (kept nowhere: they go
  into the draft and nowhere else) and the hashes the exhibit register holds,
  with a box ticked only for an algorithm on record. Every blank nobody filled,
  the person's name above all, stays a line of underscores for a pen.
* Part B is the expert's own statement and is left exactly as the Schedule
  prints it.
* The hash report the Schedule asks for is enclosed: each record's file, size,
  hashes, tool, maker, and chain of custody from the register.
* It is a draft for signature. It never calls itself certified or admissible,
  and values Exchequer filled in are set apart in bold type so they are checked.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from . import config, exhibits
from .assets import NOT_A_KEY, looks_like_secret
from .display_text import one_line
from .report_pdf import INK, MUTED, PANEL, RULE, _register_fonts, _styles

SCHEDULE_FILE = Path(__file__).resolve().parent.parent / "data" / "bsa_schedule_certificate.txt"
BOX = "□"
DEVICES = ("Computer / Storage Media", "DVR", "Mobile", "Flash Drive", "CD/DVD", "Server", "Cloud", "Other")
CONTROL = ("Owned", "Maintained", "Managed", "Operated")
ALGORITHMS = (("SHA1", "sha1"), ("SHA256", "sha256"), ("MD5", "md5"))
TEXT = {"device_other": (120, "the other kind of device"), "make_model": (120, "the make and model"),
        "color": (40, "the colour"), "serial": (80, "the serial number"),
        "device_id": (120, "the IMEI, UIN, UID, MAC or cloud ID"), "other_info": (300, "the other information")}
EXHIBITS_MAX = 20
REPORT_MAX = 2_000_000  # as /verify: the largest real reports are ~200 KB
GENUINE = ("genuine", "genuine_earlier_key")
BLANK = re.compile(r"_{3,}")
TITLES = ("THE SCHEDULE", "[See section 63(4)(c)]", "CERTIFICATE", "PART A", "(To be filled by the Party)",
          "PART B", "(To be filled by the Expert)")


class CertificateError(ValueError):
    """What was asked for is missing, malformed or not the viewer's; the message says which."""


@lru_cache(maxsize=1)
def schedule() -> tuple[dict[str, str], list[str]]:
    """The Schedule's lines and where they came from (source, text_as_on, source_pdf_sha-256)."""
    meta: dict[str, str] = {}
    lines: list[str] = []
    for line in SCHEDULE_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") and ": " in line:
            key, value = line[2:].split(": ", 1)
            meta[key.strip().lower().replace(" ", "_")] = value.strip()
        elif line and not line.startswith("#"):
            lines.append(line)
    return meta, lines


# -- what the officer typed -------------------------------------------------------------------------------
def _details(raw: dict[str, Any]) -> dict[str, Any]:
    unknown = set(raw) - set(TEXT) - {"device", "control"}
    if unknown:
        raise CertificateError(f"Not part of the certificate: {', '.join(sorted(unknown))}.")
    out: dict[str, Any] = {}
    for key, (limit, what) in TEXT.items():
        value = one_line(raw.get(key) or "").strip()
        if len(value) > limit:
            raise CertificateError(f"{what[0].upper()}{what[1:]} is longer than {limit} characters.")
        if looks_like_secret(value):
            raise CertificateError(NOT_A_KEY)
        out[key] = value
    device = one_line(raw.get("device") or "").strip()
    if device and device not in DEVICES:
        raise CertificateError(f"Pick the kind of device from the Schedule's list: {', '.join(DEVICES)}.")
    control = raw.get("control") or []
    if not isinstance(control, list) or not all(c in CONTROL for c in control):
        raise CertificateError(f"Who controls the device is one or more of {', '.join(CONTROL)}.")
    return {**out, "device": device, "control": sorted(set(control), key=CONTROL.index)}


def _records(case_id: str, exhibit_ids: list[str], viewer: Any) -> list[dict[str, Any]]:
    if not exhibit_ids:
        raise CertificateError("Pick at least one exhibit for the certificate.")
    if len(exhibit_ids) > EXHIBITS_MAX or len(set(exhibit_ids)) != len(exhibit_ids):
        raise CertificateError(f"Pick up to {EXHIBITS_MAX} different exhibits.")
    readable = {r["exhibit_id"]: r for r in exhibits.list_for(viewer, case_id)}
    for eid in exhibit_ids:
        if eid not in readable:
            raise CertificateError(f"No exhibit {str(eid)[:8]} in this case that you can read.")
    return [readable[eid] for eid in exhibit_ids]


# -- filling the Schedule ----------------------------------------------------------------------------------
# A line is (alignment, segments); a segment is ("t", Schedule text), ("f", a value filled in) or ("b", ticked).
def _with_blanks(text: str, values: list[str]) -> list[tuple[str, Any]]:
    """The line with its runs of underscores, in order, replaced by `values`; an empty value keeps the blank."""
    out: list[tuple[str, Any]] = []
    at = 0
    for i, run in enumerate(BLANK.finditer(text)):
        before, after = text[at:run.start()], text[run.end():run.end() + 1]
        out.append(("t", before))
        value = values[i] if i < len(values) else ""
        if value:  # a blank glued to its label ("Cloud ID____") gets a space, so the value reads apart
            value = ("" if not before or before.endswith(" ") else " ") + value + (" " if after.isalnum() or after == "(" else "")
        out.append(("f", value) if value else ("t", run.group()))
        at = run.end()
    out.append(("t", text[at:]))
    return [s for s in out if s[1] != ""]


def _boxes(text: str, ticked: set[str], spaced: bool = False) -> list[tuple[str, Any]]:
    """The line with each □ a box, ticked when the label before it is in `ticked`."""
    parts = text.split(BOX)
    out: list[tuple[str, Any]] = []
    for i, part in enumerate(parts):
        if part:
            out.append(("t", part.strip() + " " if spaced else part))
        if i < len(parts) - 1:
            out.append(("b", part.strip() in ticked))
            if spaced and i < len(parts) - 2:
                out.append(("t", " "))
    return out


def _hash_line(records: list[dict[str, Any]]) -> str:
    if len(records) > 1:
        return f"listed in the enclosed hash report ({len(records)} records)"
    r = records[0]
    return r["sha256"] or r["sha1"] or r["md5"]


def _algorithm(text: str, records: list[dict[str, Any]]) -> list[tuple[str, Any]] | None:
    for label, key in ALGORITHMS:
        if text == f"{BOX} {label}:":
            have = [r[key] for r in records if r[key]]
            if not have:
                return [("b", False), ("t", f" {label}:")]
            value = have[0] if len(records) == 1 else "see the enclosed hash report"
            return [("b", True), ("t", f" {label}: "), ("f", value)]
    return None


def _part_a(lines: list[str], d: dict[str, Any], records: list[dict[str, Any]]) -> list[tuple[str, list]]:
    filled = {
        "Other:": [d["device_other"] if d["device"] == "Other" else ""],
        "Make & Model:": [d["make_model"], d["color"]],
        "Serial Number:": [d["serial"]],
        "IMEI/UIN/UID/MAC/Cloud ID": [d["device_id"]],
        "and any other relevant information": [d["other_info"]],
        "I state that the HASH value/s": [_hash_line(records)],
    }
    seen: set[str] = set()
    out = []
    for text in lines:
        if text in TITLES:
            out.append(("title", [("t", text)]))
            continue
        segments = _algorithm(text, records)
        start = next((k for k in filled if text.startswith(k)), None)
        if segments is not None:
            seen.add(text)
        elif start:
            segments = _with_blanks(text, filled[start])
            seen.add(start)
        elif text.startswith("Owned " + BOX):
            segments = _boxes(text, set(d["control"]), spaced=True)
            seen.add("Owned")
        elif BOX in text and not text.startswith(BOX):
            segments = _boxes(text, {d["device"]})
            seen.add("device")
        else:
            segments = _boxes(text, set())
        out.append(("sig" if text.startswith("(Name") else "left", segments))
    expected = set(filled) | {"Owned", "device"} | {f"{BOX} {label}:" for label, _ in ALGORITHMS}
    if seen != expected:
        raise RuntimeError(f"The Schedule's wording has changed ({sorted(expected - seen)} not found); "
                           "check app/certificates.py against data/bsa_schedule_certificate.txt.")
    return out


def _part_b(lines: list[str]) -> list[tuple[str, list]]:
    """Exactly as the Schedule prints it: the expert's statement is theirs to make."""
    return [("title" if t in TITLES else "sig" if t.startswith("(Name") else "left", _boxes(t, set())) for t in lines]


def _assemble(case_id: str, d: dict[str, Any], records: list[dict[str, Any]], rows: list[list[tuple[str, str]]],
              source: str, note: str) -> dict[str, Any]:
    meta, lines = schedule()
    split = lines.index("PART B")
    return {
        "case_id": case_id, "made_at": datetime.now(tz=exhibits.IST).strftime("%d/%m/%Y %H:%M"), "meta": meta,
        "lines": _part_a(lines[:split], d, records) + _part_b(lines[split:]), "records": records, "rows": rows,
        "source": source, "note": note,
    }


def draft(case_id: str, exhibit_ids: list[str], details: dict[str, Any], viewer: Any) -> dict[str, Any]:
    """The certificate for `exhibit_ids` of `case_id`, ready to print as text or PDF."""
    d = _details(details)
    records = _records(case_id, list(exhibit_ids), viewer)
    return _assemble(case_id, d, records, [_report_rows(r) for r in records], "from its exhibit register",
                     "From the case's exhibit register; each file was hashed where it is kept and never uploaded.")


# -- Exchequer's own report as the record -----------------------------------------------------------------
def _checked(body: bytes) -> dict[str, Any]:
    """What /verify says of `body`: a PDF by its attached report and its pages, else the text report."""
    from .pdf_verify import is_pdf, verify_pdf  # PdfBusy, when every reader is busy, reaches the route
    from .signing import verify_report

    if is_pdf(body):
        return verify_pdf(body)
    try:
        return verify_report(body.decode("utf-8"))
    except UnicodeDecodeError:
        return {"status": "not_a_report", "detail": "It is not a text report or an Exchequer PDF."}


def decode_report(report_b64: str) -> bytes:
    try:
        return base64.b64decode(report_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CertificateError("The report file did not arrive as base64; choose the file again.") from exc


def draft_report(case_id: str, body: bytes, file_name: str, details: dict[str, Any], viewer: Any) -> dict[str, Any]:
    """The certificate for Exchequer's own report of `case_id`: the file the officer will produce.

    The server cannot rebuild a downloaded report's exact bytes later (rendered
    reports are kept in memory only), so the file itself is checked, as /verify
    checks it, and its SHA-256 is the one the certificate states."""
    d = _details(details)
    if len(body) > REPORT_MAX:
        raise CertificateError("That file is larger than any Exchequer report.")
    name = one_line(file_name or "").strip()[:200] or "not given"
    result = _checked(body)
    if result.get("status") not in GENUINE:
        raise CertificateError("This file is not a genuine, unchanged Exchequer report: "
                               f"{result.get('detail') or result.get('status')} Choose the file exactly as it was downloaded.")
    reported = (result.get("finding") or {}).get("case_id")
    if reported != case_id:
        raise CertificateError(f"This is the report of case {reported}, not of this case; open that case to draft its certificate.")
    sha = hashlib.sha256(body).hexdigest()
    pdf = result.get("pdf")
    key = result.get("key_fingerprint_sha256") or "not given"
    checked = ("Genuine: its signature verifies and its content hash matches"
               + ("; its pages match the signed report" if pdf else "")
               + (", signed with an earlier Exchequer key" if result["status"] == "genuine_earlier_key" else "") + ".")
    rows = [("File", f"{name} · {len(body):,} bytes"),
            ("What it is", f"Exchequer's report of case {case_id} ({'PDF with its signed text report attached' if pdf else 'signed text report'})"),
            ("SHA-256", sha), ("SHA-1", "not stated"), ("MD5", "not stated"),
            ("Checked", f"{checked} Checked by Exchequer on drafting this certificate."),
            ("Signing key", f"Ed25519, SHA-256 fingerprint {key} ({'in' if result.get('official') else 'not in'} the list of official Exchequer keys)"),
            ("Content hash", result.get("content_sha256") or "not given"),
            ("Issued by", result.get("issued_by") or "not stated in the report"),
            ("Check again", f"Upload the same file at {(config.PUBLIC_URL or 'the issuing server').rstrip('/')}/verify, "
                            "which recomputes the hash and the signature and keeps nothing.")]
    record = {"sha256": sha, "sha1": "", "md5": ""}
    return _assemble(case_id, d, [record], [rows], "from the report file the officer will produce",
                     "The report file itself was checked: a genuine, unchanged Exchequer report of this case. "
                     "The SHA-256 is of exactly that file; produce that file with this certificate.")


# -- the hash report ---------------------------------------------------------------------------------------
def _history(h: dict[str, Any]) -> str:
    note = f" ({h['note']})" if h.get("note") else ""
    if h.get("action") == "checked":
        return f"file checked: {h.get('result')}"
    if h.get("action") == "changed":
        return ", ".join(h.get("changed") or []).replace("_", " ") + " changed" + note
    if h.get("action") == "noted":
        return f"note: {h.get('note', '')}"
    return str(h.get("action", ""))


def _report_rows(r: dict[str, Any]) -> list[tuple[str, str]]:
    size = f"{r['size_bytes']:,} bytes" if r.get("size_bytes") is not None else "not recorded"
    rows = [("Exhibit", r["exhibit_id"]), ("What it is", f"{r['label']} ({r['kind_label']})"),
            ("File", f"{r['file_name'] or 'not recorded'} · {size}"), ("Tool", r["tool"]),
            ("Made", f"{r['made_on']} by {r['made_by'] or 'not recorded'}"),
            ("Kept", f"{r['stored_at'] or 'not recorded'} · held by {r['holder'] or 'not recorded'} · {r['status']}")]
    rows += [(label, r[key] or "not recorded") for label, key in (("SHA-256", "sha256"), ("SHA-1", "sha1"), ("MD5", "md5"))]
    rows += [("Custody" if i == 0 else "", f"{str(h.get('at', ''))[:10]} {_history(h)}") for i, h in enumerate(r["history"])]
    return rows


# -- as text (for tests and the screen's preview) --------------------------------------------------------
def _intro(dr: dict[str, Any]) -> list[str]:
    return [
        "DRAFT FOR SIGNATURE: not valid until the person producing the record signs Part A and the expert signs Part B.",
        f"Prepared by Exchequer on {dr['made_at']} (IST) for case {dr['case_id']}, {dr['source']}. "
        "Values in bold were filled in by Exchequer or typed by the officer: check each one before signing.",
        f"Wording: THE SCHEDULE of the Bharatiya Sakshya Adhiniyam, 2023, from India Code, text as on {dr['meta'].get('text_as_on', '?')}.",
    ]


def as_text(dr: dict[str, Any]) -> str:
    def seg(s: tuple[str, Any]) -> str:
        return ("[x]" if s[1] else "[ ]") if s[0] == "b" else s[1]

    body = ["".join(seg(s) for s in segments) for _, segments in dr["lines"]]
    report = ["HASH REPORT (enclosed with the certificate)"]
    for n, rows in enumerate(dr["rows"], 1):
        report.append(f"Record {n}")
        report += [f"  {k}: {v}" if k else f"    {v}" for k, v in rows]
    return "\n".join(_intro(dr) + [""] + body + [""] + report)


# -- as PDF -----------------------------------------------------------------------------------------------
class _FormLine(Flowable):
    """One line of the Schedule: its words in Plex, filled values in bold mono, boxes drawn (Plex has no □)."""

    FONTS = {"t": ("Plex", 9.2), "f": ("PlexMono-Bold", 8.4)}
    LEADING, BOXSIZE = 13.2, 7.4

    def __init__(self, align: str, segments: list[tuple[str, Any]]) -> None:
        super().__init__()
        self.align, self.segments, self.rows = align, segments, []
        if align == "title":
            bold = segments[0][1] in ("THE SCHEDULE", "CERTIFICATE", "PART A", "PART B")
            self.FONTS = {"t": ("PlexSerif" if bold else "Plex", 11 if bold else 9.2)}

    def _tokens(self) -> list[tuple[str, Any, float]]:
        out = []
        for kind, value in self.segments:
            if kind == "b":
                out.append(("b", value, self.BOXSIZE + 2))
                continue
            font, size = self.FONTS.get(kind, self.FONTS["t"])
            for word in re.findall(r"\S+|\s+", value):
                out.append((kind, word, stringWidth(word, font, size)))
        return out

    def wrap(self, available_width: float, _height: float) -> tuple[float, float]:
        self.width, self.rows, row, used = available_width, [], [], 0.0
        for token in self._tokens():
            if row and used + token[2] > available_width and not token[1] == " ":
                self.rows.append(row)
                row, used = [], 0.0
            if not row and isinstance(token[1], str) and token[1].isspace():
                continue
            row.append(token)
            used += token[2]
        self.rows.append(row)
        self.height = len(self.rows) * self.LEADING + (4 if self.align == "title" else 0)
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        y = self.height - self.LEADING + 3.5
        for row in self.rows:
            total = sum(t[2] for t in row)
            x = {"title": (self.width - total) / 2, "sig": self.width - total}.get(self.align, 0.0)
            for kind, value, width in row:
                if kind == "b":
                    c.setStrokeColor(INK)
                    c.setLineWidth(0.7)
                    c.rect(x + 1, y - 0.5, self.BOXSIZE, self.BOXSIZE)
                    if value:
                        c.setFont("Plex-Bold", 8.5)
                        c.drawString(x + 1.6, y + 0.4, "✓")
                else:
                    font, size = self.FONTS.get(kind, self.FONTS["t"])
                    c.setFont(font, size)
                    c.setFillColor(INK)
                    c.drawString(x, y, value)
                x += width
            y -= self.LEADING


def render_pdf(dr: dict[str, Any]) -> bytes:
    _register_fonts()
    st = _styles()
    story: list[Any] = []
    intro = Table([[Paragraph(escape(line), st["small" if i else "base"])] for i, line in enumerate(_intro(dr))],
                  colWidths=[174 * mm])
    intro.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.6, RULE),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (0, 0), 7),
                               ("BOTTOMPADDING", (0, -1), (-1, -1), 7)]))
    story += [intro, Spacer(1, 8 * mm)]
    for align, segments in dr["lines"]:
        if align == "title" and segments[0][1] == "PART B":
            story.append(PageBreak())
        story.append(_FormLine(align, segments))
    story += [PageBreak(), Paragraph("HASH REPORT", st["h2"]),
              Paragraph(escape("Enclosed with the certificate, as Part A and Part B ask. " + dr["note"]), st["small"]),
              Spacer(1, 4 * mm)]
    mono = ("Exhibit", "SHA-256", "SHA-1", "MD5", "Content hash")
    for n, report_rows in enumerate(dr["rows"], 1):
        rows = [[Paragraph(f"<b>Record {n}</b>", st["base"]), ""]]
        rows += [[Paragraph(escape(k), st["small"]),
                  Paragraph(escape(v), st["cellmono" if k in mono else "cell"])]
                 for k, v in report_rows]
        table = Table(rows, colWidths=[26 * mm, 148 * mm])
        table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        story += [table, Spacer(1, 6 * mm)]

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("PlexMono", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"DRAFT for signature · s.63(4) certificate · case {dr['case_id'][:12]} "
                                            f"· prepared {dr['made_at']} IST")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"page {doc.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=18 * mm, title=f"Draft certificate under s.63(4), case {dr['case_id']}",
                            author="Exchequer", subject="Draft for signature", creator="Exchequer")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
