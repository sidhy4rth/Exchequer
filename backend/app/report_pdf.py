"""The case report as a PDF, for a case file.

Part 1 is a summary an officer can read in a minute: the finding, the
address to ask the exchange about, how sure, what the screening found, the
route. Part 2 is the signed text report, reproduced exactly -- the PDF is a
way to file and print it, and the text is what the content hash and the
signature cover. Every page's footer carries the case id, the content hash
and the signing key, so a single printed page can be matched to its report.

Only the attached text is signed: anyone can edit a PDF's pages without
touching it. Part 1 says so at the top, takes the exchange, the address and
the amount from the signed text (never from anything else), and tells the
reader to upload the PDF at /verify, which checks the attached file and
compares the pages with it (pdf_verify).

Typeset in IBM Plex (app/fonts, SIL Open Font Licence), the app's own family.
"""
from __future__ import annotations

import io
import logging
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
from .report import EXCHANGE_WALLET, EXPLORER_TAG, _shown_label, _when_iso, signed_finding, started_from
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
    _register_fonts()
    st = _styles()
    digest, key = _seal_facts(sealed_text)
    case_id = report["case"]["case_id"]
    try:
        pdf = _build(_part_one(report, st, digest, key, sealed_text) + _part_two(sealed_text, st),
                     case_id, digest, key)
    except LayoutError:
        # Part 1 is a reading aid; the signed report must still be issued.
        logger.warning("Case %s: the PDF summary page could not be laid out; issuing Part 2 only", case_id)
        unplaced = [_p("EXCHEQUER · CRYPTOCURRENCY TRACE REPORT", st["micro"]), _p(f"Case {case_id}", st["small"]),
                    _p("The summary page could not be laid out for this case (a label in it is too long "
                       "for the page). The signed report follows in full and is attached to this PDF.", st["cell"])]
        pdf = _build(unplaced + _part_two(sealed_text, st), case_id, digest, key)
    return _attach(pdf, _attachment_name(case_id), sealed_text.encode("utf-8"))


def _signed_facts(report: dict[str, Any], sealed_text: str) -> dict[str, Any]:
    """Exchange, address, label, amount and summary as the signed text states them.

    The page must show what the signature covers. They come from the same
    report, so they agree; if they ever do not, the signed text wins."""
    attribution = report.get("attribution") or {}
    signed = signed_finding(sealed_text)
    if signed is None:  # not a full text report (a test's stand-in): nothing better to read
        return {"exchange": attribution.get("exchange"), "address": attribution.get("exchange_address"),
                "label": attribution.get("exchange_wallet_label"), "likely_arrived": None,
                "summary": report.get("summary", "")}
    if (signed["exchange"], signed["address"]) != (attribution.get("exchange"), attribution.get("exchange_address")):
        logger.warning("Case %s: the PDF summary disagrees with the signed text; printing the signed finding",
                       report["case"]["case_id"])
    return signed


def _part_one(report: dict[str, Any], st: dict[str, ParagraphStyle], digest: str, key: str | None,
              sealed_text: str = "") -> list[Any]:
    case = report["case"]
    attribution = report.get("attribution") or {}
    confidence = report.get("confidence") or {}
    screening = report.get("risk_screening") or {}
    case_id = case["case_id"]
    signed = _signed_facts(report, sealed_text)
    issuer = read_issuer(sealed_text.split(f"\n{CONTENT_HASH_MARK} (", 1)[0]) or {}

    story: list[Any] = []
    story.append(_p("EXCHEQUER · CRYPTOCURRENCY TRACE REPORT", st["micro"]))
    story.append(_p(f"Case {case_id}", st["small"]))
    story.append(Paragraph(
        f"<font name='Plex-Bold' color='{AMBER.hexval()}'>SUMMARY: NOT SIGNED.</font> The signed record is the "
        "attached text file, also printed as Part 2. This page is a copy for reading.", st["small"]))
    story.append(Spacer(1, 8))

    # -- an old screening list, before anything that relies on the screening ---
    screening_lists = report.get("screening_lists") or {}
    if screening_lists.get("warning"):
        stale = Table([[Paragraph(
            f"<font name='Plex-Bold' color='{RED.hexval()}'>WARNING.</font> "
            f"<font color='{RED.hexval()}'>{escape(one_line(screening_lists['warning']))}</font>", st["cell"])]],
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
    story.append(_p("WHERE THE MONEY WENT" if case["direction"] == "outgoing" else "WHO FUNDED THE ADDRESS",
                    st["micro"]))
    finding = ParagraphStyle("f2", parent=st["finding"], textColor=GREEN if exchange else INK)
    story.append(_p(heading, finding))
    story.append(_p(signed["summary"], st["lede"]))

    # -- key facts ----------------------------------------------------------
    facts = [
        ("Reported address", case["reported_address"], True),
        ("Chain · asset · direction", f"{case['chain']} · {case['asset']} · {case['direction']}", False),
        ("Traced at", _when_iso(case.get("traced_at")), False),
        ("Started from", started_from(report.get("intake"), case.get("asset") or ""), False),
    ]
    if exchange:
        facts += [
            ({EXPLORER_TAG: "Address to ask the exchange to confirm",
              EXCHANGE_WALLET: "Wallet the funds reached"}.get(attribution.get("kind"), "Address to ask the exchange about"),
             signed["address"] or "", True),
            ("Wallet", _label(signed["label"]), False),
            ("Hops from the reported address", attribution.get("hop_count", ""), False),
        ]
        prorata = attribution.get("prorata") or {}
        cap = prorata.get("seed_cap") or {}
        if signed["likely_arrived"]:
            # The signed text's own line, so Part 1 can never state another figure;
            # it already says what the estimate is capped at (r1-attribution-integrity-7).
            caption = (f"Likely arrived (pro-rata; at most what "
                       f"{CAP_WORDING.get(cap.get('basis'), 'the trace started from')})"
                       if prorata.get("status") == "estimated" and cap.get("applied")
                       else "Likely arrived, of what this wallet sent on this route (pro-rata)")
            facts.append((caption, signed["likely_arrived"], False))
        elif prorata.get("status") == "estimated":
            facts.append(("Likely arrived, of what this wallet sent on this route (pro-rata)",
                          f"≈ {_num(prorata.get('estimated'))} of {_num(prorata.get('sent'))} "
                          f"{attribution.get('value_currency', '')}", False))
        elif prorata.get("status") == "unknown":
            # Said on page 1, not only in the limitations: no amount was measured.
            facts.append(("Pro-rata", f"not estimated — {prorata.get('reason')}", False))
        if signed.get("share_of_funds"):
            # Against the whole, from the signed text: the line above is one route's.
            facts.append(("Share of the traced funds", signed["share_of_funds"], False))
        if signed.get("also_reached"):
            # The signed text's first such line; every one is in the signed report.
            more = len(attribution.get("also_reached") or []) - 1
            facts.append(("Material funds also reached", signed["also_reached"]
                          + (f" (and {more} more; see the signed report)" if more > 0 else ""), False))
    if confidence.get("score") is not None:
        # R10: the band, not the decimal; the score's working is in the signed text.
        band = (confidence.get("band") or "").capitalize() or "n/a"
        facts.append(("Confidence", f"{band} (a rule of three inputs, not a probability)", False))
    rows = [[_p(label, st["small"]), _p(value, st["cellmono"] if mono else st["cell"])]
            for label, value, mono in facts]
    table = Table(rows, colWidths=[52 * mm, None])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [Spacer(1, 10), table]

    if confidence.get("summary"):
        story += [_p("HOW SURE", st["micro"]), _p(_shown_label(confidence["summary"]), st["cell"])]

    # -- how to verify --------------------------------------------------------
    verify = Table([[Paragraph(
        "<font name='Plex-Bold'>Checking this report.</font> Only the attached text file is signed: "
        f"<font name='PlexMono'>{escape(_attachment_name(case_id))}</font> (your PDF reader's attachments "
        "panel). This page, the printed Part 2 and the footer are copies for reading: they are not covered "
        "by the signature and can be edited without breaking it. Before acting on this page, upload this "
        f"PDF at <font name='PlexMono'>{escape(_verify_at(issuer.get('issued_by')))}</font>: it checks the "
        "attached file and says whether this page shows the exchange, the address and the amount the signed "
        "report states. Text copied from the printed pages will not verify, because copying from a PDF "
        "changes line breaks.<br/>"
        f"<font name='PlexMono' size='7.5'>content SHA-256 {escape(digest)}<br/>"
        f"signing key {escape(key or 'none (unsigned)')}"
        + (f"<br/>issued by {escape(one_line(issuer['issued_by']))}" if issuer.get("issued_by") else "")
        + "</font>", st["small"])]], colWidths=[None])
    verify.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story += [Spacer(1, 8), KeepTogether([verify])]

    # -- screening ------------------------------------------------------------
    matches = screening.get("matches") or []
    story.append(_p("SANCTIONS, MIXER, FREEZE AND STOLEN-FUNDS SCREENING", st["micro"]))
    if not screening.get("screened"):
        story.append(_p("This chain has no screening lists loaded; no screening was done.", st["cell"]))
    elif not matches:
        story.append(_p("No address in the trace is on the lists below.", st["cell"]))
    else:
        for m in matches[:8]:
            colour = RED if m.get("category") in ("sanctioned", "mixer") else AMBER
            line = (f"<font name='Plex-Bold' color='{colour.hexval()}'>{escape(one_line(m.get('category', '')).title())}</font> · "
                    f"<font name='PlexMono'>{escape(one_line(m.get('address', '')))}</font> · "
                    f"{escape(_label(m.get('entity') or m.get('label') or ''))}")
            story.append(Paragraph(line, st["cell"]))
        if len(matches) > 8:
            story.append(_p(f"…and {len(matches) - 8} more, listed in Part 2.", st["small"]))

    # -- the lists and their dates ----------------------------------------------
    if screening_lists.get("lists"):
        story.append(_p("LISTS SCREENED AGAINST", st["micro"]))
        for entry in screening_lists["lists"]:
            published = f", published {entry['published']}" if entry.get("published") else ""
            note = f" {entry['note']}" if entry.get("note") else ""
            story.append(_p(f"{entry['name']}: checked {entry['checked'] or 'no date recorded'}{published}.{note}",
                            st["small"]))
    if screening_lists.get("not_held"):
        # Said here too: a summary that names only what was held reads as if nothing was left out.
        story.append(_p(f"Not loaded for this chain, so not screened: {', '.join(screening_lists['not_held'])}.",
                        st["small"]))

    # -- the route ------------------------------------------------------------
    path = report.get("trace_path") or []
    if len(path) > 1:
        story.append(_p("THE ROUTE (PRINCIPAL PATH)", st["micro"]))
        route = [[_p("Hop", st["small"]), _p("Address", st["small"]), _p("Label", st["small"]),
                  _p("Received", st["small"])]]
        for step in path:
            label = _label(step.get("label") or step.get("exchange"))
            if not label and step.get("address") == attribution.get("exchange_address"):
                label = _label(attribution.get("exchange_wallet_label"))
            if not label and step.get("depth") == 0:
                label = "reported address"
            amount = step.get("value_native")
            route.append([
                _p(step.get("depth", ""), st["cell"]),
                _p(step.get("address", ""), st["cellmono"]),
                _p(label, st["cell"]),
                _p(f"{_num(amount)} {case['asset']}" if amount is not None else "", st["cellmono"]),
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
    limits = report.get("limitations") or []
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
