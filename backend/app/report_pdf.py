"""The case report as a PDF, for a case file.

Part 1 is a summary an officer can read in a minute: the finding, the
address to ask the exchange about, how sure, what the screening found, the
route. Part 2 is the signed text report, reproduced exactly -- the PDF is a
way to file and print it, and the text is what the content hash and the
signature cover. Every page's footer carries the case id, the content hash
and the signing key, so a single printed page can be matched to its report.

Only the attached text is signed: anyone can edit a PDF's pages without
touching it. Part 1 says so at the top, and is drawn from the signed text
alone (summary_facts reads it back; nothing else reaches the page), so
/verify can draw it again from the attached file and require the uploaded
page 1 to hold exactly that text (pdf_verify).

Typeset in IBM Plex (app/fonts, SIL Open Font Licence), the app's own family.
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak, KeepTogether, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.platypus.doctemplate import LayoutError
from xml.sax.saxutils import escape

from .display_text import one_line, short
from .evidence import CONTENT_HASH_MARK, read_issuer
from .report import (EXCHANGE_WALLET, EXPLORER_TAG, KIND_LINE, KIND_WORDING, _shown_label, signed_finding)
from .scoring import CAP_WORDING
from .signing import SIGNATURE_MARK

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).resolve().parent / "fonts"
# A label in a narrow table cell: a row taller than the page cannot be laid
# out at all. The full text is in Part 2 and the attached file.
CELL_LABEL_MAX = 120
_FONTS = {
    "Plex": "IBMPlexSans-Regular.ttf",
    "Plex-Bold": "IBMPlexSans-SemiBold.ttf",
    "PlexMono": "IBMPlexMono-Regular.ttf",
    "PlexMono-Bold": "IBMPlexMono-SemiBold.ttf",
    "PlexSerif": "IBMPlexSerif-SemiBold.ttf",
}
_registered = False

INK = colors.HexColor("#16181c")
MUTED = colors.HexColor("#5d636b")
RULE = colors.HexColor("#d9d6cf")
PANEL = colors.HexColor("#f5f3ee")
GREEN = colors.HexColor("#1d7a4c")
RED = colors.HexColor("#b3261e")
AMBER = colors.HexColor("#9a5b00")


def _register_fonts() -> None:
    global _registered
    if _registered:
        return
    for name, file in _FONTS.items():
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
    _registered = True


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Plex", fontSize=9.5, leading=13.5, textColor=INK, alignment=TA_LEFT)
    return {
        "base": base,
        "micro": ParagraphStyle("micro", parent=base, fontName="Plex-Bold", fontSize=7, leading=9,
                                textColor=MUTED, spaceBefore=10, spaceAfter=4),
        "finding": ParagraphStyle("finding", parent=base, fontName="PlexSerif", fontSize=26, leading=30,
                                  spaceAfter=4),
        "lede": ParagraphStyle("lede", parent=base, fontSize=9.5, leading=13.5, textColor=INK),
        "small": ParagraphStyle("small", parent=base, fontSize=8, leading=11, textColor=MUTED),
        "mono": ParagraphStyle("mono", parent=base, fontName="PlexMono", fontSize=8.5, leading=11.5),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.5, leading=11.5),
        "cellmono": ParagraphStyle("cellmono", parent=base, fontName="PlexMono", fontSize=7.8, leading=10.5),
        "h2": ParagraphStyle("h2", parent=base, fontName="PlexSerif", fontSize=15, leading=19, spaceAfter=6),
        "pre": ParagraphStyle("pre", parent=base, fontName="PlexMono", fontSize=6.9, leading=8.6),
    }


def _seal_facts(sealed_text: str) -> tuple[str, str | None]:
    """(content hash, signing key fingerprint) read back from the sealed text."""
    digest, key = "", None
    for line in sealed_text.splitlines():
        if line.startswith(CONTENT_HASH_MARK + " ("):
            digest = line.rsplit(": ", 1)[-1].strip()
        elif line.startswith(SIGNATURE_MARK + " ("):
            key = line.split("key ", 1)[-1].split(")", 1)[0].strip()
    return digest, key


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(one_line(text)), style)


def _label(text: Any) -> str:
    return short(_shown_label(one_line(text) if text else ""), CELL_LABEL_MAX)


def _num(value: Any) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{v:,.6f}".rstrip("0").rstrip(".") if v else "0"


def render_pdf(report: dict[str, Any], sealed_text: str) -> bytes:
    """The PDF for `sealed_text`. `report` is the same report; only its case id
    is read here: page 1 is drawn from the signed text alone."""
    _register_fonts()
    st = _styles()
    digest, key = _seal_facts(sealed_text)
    case_id = report["case"]["case_id"]
    try:
        pdf = _build(summary_story(sealed_text, st, case_id) + _part_two(sealed_text, st), case_id, digest, key)
    except LayoutError:
        # Part 1 is a reading aid; the signed report must still be issued.
        logger.warning("Case %s: the PDF summary page could not be laid out; issuing Part 2 only", case_id)
        pdf = _build(unplaced_story(case_id, st) + _part_two(sealed_text, st), case_id, digest, key)
    return _attach(pdf, _attachment_name(case_id), sealed_text.encode("utf-8"))


NOT_READ = ("The summary page could not be drawn from the signed report (it is not in a format this "
            "version reads). The signed report follows in full and is attached to this PDF.")
NOT_LAID_OUT = ("The summary page could not be laid out for this case (a label in it is too long "
                "for the page). The signed report follows in full and is attached to this PDF.")


def unplaced_story(case_id: str, st: dict[str, ParagraphStyle], why: str = NOT_LAID_OUT) -> list[Any]:
    """The short page 1 printed when the summary cannot be: fixed words and the case id."""
    return [_p("EXCHEQUER · CRYPTOCURRENCY TRACE REPORT", st["micro"]), _p(f"Case {case_id}", st["small"]),
            _p(why, st["cell"])]


def summary_story(sealed_text: str, st: dict[str, ParagraphStyle], case_id: str) -> list[Any]:
    """Page 1's flowables, from the signed text alone."""
    facts = summary_facts(sealed_text)
    if facts is None:
        return unplaced_story(case_id, st, NOT_READ)
    digest, key = _seal_facts(sealed_text)
    return _part_one(facts, st, digest, key)


def render_summary(sealed_text: str) -> list[str]:
    """Page 1 (and any page the summary runs onto) as /verify draws it again:
    each page's text, read back as pdf_verify reads an uploaded PDF. Both
    forms page 1 can take -- the summary, or the short page printed when the
    summary could not be laid out -- in that order."""
    from pypdf import PdfReader

    _register_fonts()
    st = _styles()
    digest, key = _seal_facts(sealed_text)
    facts = summary_facts(sealed_text)
    case_id = facts["case_id"] if facts else ""
    forms = []
    try:
        forms.append(_build(summary_story(sealed_text, st, case_id), case_id, digest, key))
    except LayoutError:
        pass
    forms.append(_build(unplaced_story(case_id, st), case_id, digest, key))
    return ["\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages) for pdf in forms]


# -- reading page 1's facts back from the signed text ------------------------------
_RULE = "-" * 78
_HEADER = {"Reported address : ": "reported_address", "Chain            : ": "chain",
           "Asset followed   : ": "asset", "Direction        : ": "direction",
           "Started from     : ": "started_from", "Traced at        : ": "traced_at"}
_CHAIN_ID = re.compile(r" \(chainid \d+\)$")
_STEP = re.compile(r"  (\d+)\. (\S+)(?:  \[(.*)\])?")
_SENT = re.compile(r"     sent (\S+) ")
_MATCH = re.compile(r"(?P<category>[^:]{1,40}): (?P<address>\S+) (?P<rest>.*)")
_KINDS = {wording: kind for kind, wording in KIND_WORDING.items()}
ALSO_REACHED = "Also reached     : "  # render_text_report's FINDING line, one per other exchange


def _sections(lines: list[str]) -> dict[str, list[str]]:
    """Each section's lines by title, as render_text_report lays them out
    (a title between two rules); the first of a title wins."""
    starts = [n for n in range(1, len(lines) - 1) if lines[n - 1] == lines[n + 1] == _RULE and lines[n]]
    out: dict[str, list[str]] = {}
    for i, n in enumerate(starts):
        end = starts[i + 1] - 1 if i + 1 < len(starts) else len(lines)
        out.setdefault(lines[n], lines[n + 2:end])
    return out


def _section(sections: dict[str, list[str]], title: str) -> list[str]:
    return next((body for name, body in sections.items() if name.startswith(title)), [])


def _items(lines: list[str], bullet: str) -> list[str]:
    """Wrapped bullet items ("- " or "* " then indented lines), joined back into one line each."""
    items: list[str] = []
    for line in lines:
        if line.startswith(bullet):
            items.append(line[len(bullet):])
        elif items and line.startswith(" " * len(bullet)) and line.strip():
            items[-1] += " " + line.strip()
    return items


def _para(lines: list[str], start: int) -> str:
    """The wrapped paragraph from `start` to the next empty line, as one line."""
    end = start
    while end < len(lines) and lines[end]:
        end += 1
    return " ".join(line.strip() for line in lines[start:end])


def summary_facts(sealed_text: str) -> dict[str, Any] | None:
    """What page 1 prints, read back from a signed text report; None if the
    text is not one this version can read. Every fact comes from the text,
    so page 1 can never state anything the signature does not cover."""
    try:
        return _summary_facts(sealed_text)
    except (IndexError, KeyError, ValueError, StopIteration):
        return None


def _summary_facts(sealed_text: str) -> dict[str, Any] | None:
    finding = signed_finding(sealed_text)
    if finding is None:
        return None
    body = sealed_text.replace("\r\n", "\n").split(f"\n{CONTENT_HASH_MARK} (", 1)[0]
    lines = body.split("\n")
    facts: dict[str, Any] = {"case_id": finding["case_id"], "finding": finding,
                             "issued_by": (read_issuer(body) or {}).get("issued_by")}
    header_end = lines.index("", 3)
    for line in lines[3:header_end]:
        for prefix, key in _HEADER.items():
            if line.startswith(prefix):
                facts.setdefault(key, line[len(prefix):])
    facts["chain"] = _CHAIN_ID.sub("", facts["chain"])
    facts["direction"] = facts["direction"].split(" ", 1)[0]
    after = header_end + 1
    facts["warning"] = (_para(lines, after).removeprefix("WARNING: ")
                        if lines[after].startswith("WARNING: ") else None)

    sections = _sections(lines)
    found = _section(sections, "FINDING")
    field = {prefix: next((line[len(prefix):] for line in found if line.startswith(prefix)), None)
             for prefix in (KIND_LINE, "Hops from source : ", "Pro-rata         : ")}
    facts["kind"] = _KINDS.get(field[KIND_LINE] or "")
    facts["hops"] = field["Hops from source : "] or ""
    facts["prorata_unknown"] = (field["Pro-rata         : "] or "").removeprefix("not estimated -- ") or None
    facts["also_reached"] = [line[len(ALSO_REACHED):] for line in found if line.startswith(ALSO_REACHED)]

    confidence = _section(sections, "CONFIDENCE")
    band = next((line[19:] for line in confidence if line.startswith("Band             : ")), "")
    score = next((line[19:] for line in confidence if line.startswith("Score            : ")), "n/a")
    facts["band"] = None if score.startswith("n/a") else ("n/a" if band in ("", "N/a") else band)
    at = next(n for n, line in enumerate(confidence) if line.startswith("Score            : "))
    summary_at = at + 2
    facts["how_sure"] = (_para(confidence, summary_at)
                         if summary_at < len(confidence) and confidence[at + 1] == "" and confidence[summary_at]
                         and confidence[summary_at] != "How this score was reached:" else None)

    path = _section(sections, "PATH THE MONEY TOOK")
    steps, amount = [], None
    for line in path:
        sent = _SENT.match(line)
        if sent:
            amount = sent.group(1)
            continue
        step = _STEP.fullmatch(line)
        if step:
            steps.append({"address": step.group(2), "label": step.group(3) or "",
                          "amount": None if amount in (None, "None") else float(amount)})
            amount = None
    facts["route"] = steps

    screening = _section(sections, "SANCTIONS, MIXER, FREEZE AND STOLEN-FUNDS SCREENING")
    facts["matches"] = _items(screening, "* ")

    listed = _section(sections, "LISTS SCREENED AGAINST")
    entries: list[dict[str, str]] = []
    not_held = None
    blank = listed.index("") if "" in listed else len(listed)
    n = blank + 1
    while n < len(listed) and listed[n]:
        line = listed[n]
        if line.startswith("  ") and not line.startswith("    "):
            if entries and "checked" not in entries[-1]:
                entries[-1]["name"] += " " + line.strip()
            else:
                entries.append({"name": line.strip()})
        elif line.startswith("    ") and entries:
            if "checked" not in entries[-1]:
                entries[-1]["checked"] = line.split(": checked ", 1)[1]
            else:
                entries[-1]["note"] = (entries[-1].get("note", "") + " " + line.strip()).strip()
        n += 1
    rest = listed[n + 1:] if n < len(listed) else []
    if rest and rest[0].startswith("Not loaded for this chain, so not screened: "):
        not_held = _para(rest, 0)
    facts["lists"] = [e for e in entries if "checked" in e]
    facts["not_held"] = not_held

    facts["limitations"] = _items(_section(sections, "LIMITATIONS"), "- ")
    return facts


def _part_one(facts: dict[str, Any], st: dict[str, ParagraphStyle], digest: str, key: str | None) -> list[Any]:
    """Page 1, from summary_facts() alone."""
    case_id = facts["case_id"]
    signed = facts["finding"]

    story: list[Any] = []
    story.append(_p("EXCHEQUER · CRYPTOCURRENCY TRACE REPORT", st["micro"]))
    story.append(_p(f"Case {case_id}", st["small"]))
    story.append(Paragraph(
        f"<font name='Plex-Bold' color='{AMBER.hexval()}'>SUMMARY: NOT SIGNED.</font> The signed record is the "
        "attached text file, also printed as Part 2. This page is a copy for reading.", st["small"]))
    story.append(Spacer(1, 8))

    # -- an old screening list, before anything that relies on the screening ---
    if facts["warning"]:
        stale = Table([[Paragraph(
            f"<font name='Plex-Bold' color='{RED.hexval()}'>WARNING.</font> "
            f"<font color='{RED.hexval()}'>{escape(one_line(facts['warning']))}</font>", st["cell"])]],
            colWidths=[None])
        stale.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, RED),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story += [stale, Spacer(1, 8)]

    # -- the finding --------------------------------------------------------
    exchange = signed["exchange"]
    heading = exchange or "No exchange reached"
    story.append(_p("WHERE THE MONEY WENT" if facts["direction"] == "outgoing" else "WHO FUNDED THE ADDRESS",
                    st["micro"]))
    finding = ParagraphStyle("f2", parent=st["finding"], textColor=GREEN if exchange else INK)
    story.append(_p(heading, finding))
    story.append(_p(signed["summary"], st["lede"]))

    # -- key facts ----------------------------------------------------------
    facts_rows = [
        ("Reported address", facts["reported_address"], True),
        ("Chain · asset · direction", f"{facts['chain']} · {facts['asset']} · {facts['direction']}", False),
        ("Traced at", facts["traced_at"], False),
        ("Started from", facts["started_from"], False),
    ]
    if exchange:
        facts_rows += [
            ({EXPLORER_TAG: "Address to ask the exchange to confirm",
              EXCHANGE_WALLET: "Wallet the funds reached"}.get(facts["kind"], "Address to ask the exchange about"),
             signed["address"] or "", True),
            ("Wallet", _label(signed["label"]), False),
            ("Hops from the reported address", facts["hops"], False),
        ]
        likely = signed["likely_arrived"]
        if likely:
            # The signed text's own line, so Part 1 can never state another figure;
            # it already says what the estimate is capped at (r1-attribution-integrity-7).
            if "(pro-rata; the reported address sent" in likely:
                wording = next((w for w in CAP_WORDING.values() if f" {w} (pro-rata;" in likely),
                               "the trace started from")
                caption = f"Likely arrived (pro-rata; at most what {wording})"
            else:
                caption = "Likely arrived, of what this wallet sent on this route (pro-rata)"
            facts_rows.append((caption, likely, False))
        elif facts["prorata_unknown"]:
            # Said on page 1, not only in the limitations: no amount was measured.
            facts_rows.append(("Pro-rata", f"not estimated — {facts['prorata_unknown']}", False))
        if signed.get("share_of_funds"):
            # Against the whole, from the signed text: the line above is one route's.
            facts_rows.append(("Share of the traced funds", signed["share_of_funds"], False))
        if facts["also_reached"]:
            # The signed text's first such line, and how many more it lists.
            more = len(facts["also_reached"]) - 1
            facts_rows.append(("Material funds also reached", facts["also_reached"][0]
                               + (f" (and {more} more; see the signed report)" if more > 0 else ""), False))
    if facts["band"] is not None:
        # R10: the band, not the decimal; the score's working is in the signed text.
        facts_rows.append(("Confidence", f"{facts['band']} (a rule of three inputs, not a probability)", False))
    rows = [[_p(label, st["small"]), _p(value, st["cellmono"] if mono else st["cell"])]
            for label, value, mono in facts_rows]
    table = Table(rows, colWidths=[52 * mm, None])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [Spacer(1, 10), table]

    if facts["how_sure"]:
        story += [_p("HOW SURE", st["micro"]), _p(_shown_label(facts["how_sure"]), st["cell"])]

    # -- how to verify --------------------------------------------------------
    verify = Table([[Paragraph(
        "<font name='Plex-Bold'>Checking this report.</font> Only the attached text file is signed: "
        f"<font name='PlexMono'>{escape(_attachment_name(case_id))}</font> (your PDF reader's attachments "
        "panel). This page, the printed Part 2 and the footer are copies for reading: they are not covered "
        "by the signature and can be edited without breaking it. Before acting on this page, upload this "
        f"PDF at <font name='PlexMono'>{escape(_verify_at(facts['issued_by']))}</font>: it checks the "
        "attached file and says whether this page holds exactly what Exchequer prints for the signed "
        "report. Text copied from the printed pages will not verify, because copying from a PDF "
        "changes line breaks.<br/>"
        f"<font name='PlexMono' size='7.5'>content SHA-256 {escape(digest)}<br/>"
        f"signing key {escape(key or 'none (unsigned)')}"
        + (f"<br/>issued by {escape(one_line(facts['issued_by']))}" if facts["issued_by"] else "")
        + "</font>", st["small"])]], colWidths=[None])
    verify.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story += [Spacer(1, 8), KeepTogether([verify])]

    # -- screening ------------------------------------------------------------
    matches = facts["matches"]
    story.append(_p("SANCTIONS, MIXER, FREEZE AND STOLEN-FUNDS SCREENING", st["micro"]))
    if not matches:
        story.append(_p("No address in the trace is on the lists below.", st["cell"]))
    else:
        for note in matches[:8]:
            match = _MATCH.fullmatch(note)
            if match is None:
                story.append(_p(short(note, CELL_LABEL_MAX), st["cell"]))
                continue
            category = match.group("category")
            colour = RED if category.startswith(("Sanctioned", "Mixer")) else AMBER
            line = (f"<font name='Plex-Bold' color='{colour.hexval()}'>{escape(category)}</font> · "
                    f"<font name='PlexMono'>{escape(match.group('address'))}</font> · "
                    f"{escape(short(match.group('rest'), CELL_LABEL_MAX))}")
            story.append(Paragraph(line, st["cell"]))
        if len(matches) > 8:
            story.append(_p(f"…and {len(matches) - 8} more, listed in Part 2.", st["small"]))

    # -- the lists and their dates ----------------------------------------------
    if facts["lists"]:
        story.append(_p("LISTS SCREENED AGAINST", st["micro"]))
        for entry in facts["lists"]:
            note = f" {entry['note']}" if entry.get("note") else ""
            story.append(_p(f"{entry['name']}: checked {entry['checked']}.{note}", st["small"]))
    if facts["not_held"]:
        # Said here too: a summary that names only what was held reads as if nothing was left out.
        story.append(_p(facts["not_held"], st["small"]))

    # -- the route ------------------------------------------------------------
    path = facts["route"]
    if len(path) > 1:
        story.append(_p("THE ROUTE (PRINCIPAL PATH)", st["micro"]))
        route = [[_p("Hop", st["small"]), _p("Address", st["small"]), _p("Label", st["small"]),
                  _p("Received", st["small"])]]
        for hop, step in enumerate(path):
            label = _label(step["label"])
            if not label and step["address"] == signed["address"]:
                label = _label(signed["label"])
            if not label and hop == 0:
                label = "reported address"
            amount = step["amount"]
            route.append([
                _p(hop, st["cell"]),
                _p(step["address"], st["cellmono"]),
                _p(label, st["cell"]),
                _p(f"{_num(amount)} {facts['asset']}" if amount is not None else "", st["cellmono"]),
            ])
        t = Table(route, colWidths=[12 * mm, 82 * mm, None, 28 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
            ("LINEBELOW", (0, 1), (-1, -2), 0.3, RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(t)

    # -- limitations ----------------------------------------------------------
    limits = facts["limitations"]
    if limits:
        story.append(_p("READ WITH THESE LIMITATIONS", st["micro"]))
        for item in limits[:3]:
            story.append(Paragraph(f"• {escape(_shown_label(one_line(item)))}", st["small"]))
        if len(limits) > 3:
            story.append(_p(f"…{len(limits) - 3} more in Part 2.", st["small"]))

    return story


def _part_two(sealed_text: str, st: dict[str, ParagraphStyle]) -> list[Any]:
    return [CondPageBreak(90 * mm), Spacer(1, 10), _p("Part 2 · The signed text report", st["h2"]),
            _p("The text the content hash and signature cover, for reading. Lines too long for the "
               "page wrap onto the next line; the exact file is attached to this PDF.", st["small"]),
            Spacer(1, 6), Preformatted(sealed_text, st["pre"], maxLineLength=118, newLineChars="")]


def _build(story: list[Any], case_id: str, digest: str, key: str | None) -> bytes:
    buffer = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("PlexMono", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm,
                          f"Exchequer case {case_id[:8]} · SHA-256 {digest[:16]}… · key {(key or 'unsigned')[:16]}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Exchequer case {case_id}", author="Exchequer", subject="Cryptocurrency trace report",
        creator="Exchequer",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def _verify_at(issued_by: str | None) -> str:
    return f"{one_line(issued_by)}/verify" if issued_by else "/verify on the server that issued it"


def _attachment_name(case_id: str) -> str:
    return f"exchequer-{case_id[:8]}.txt"


def _attach(pdf: bytes, name: str, data: bytes) -> bytes:
    """The PDF with `data` embedded as a file attachment."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    writer.add_attachment(name, data)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
