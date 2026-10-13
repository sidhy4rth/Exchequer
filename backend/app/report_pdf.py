"""The case report as a PDF, for a case file.

Part 1 is a summary an officer can read in a minute: the finding, the
address to ask the exchange about, how sure, what the screening found, the
route. Part 2 is the signed text report, reproduced exactly -- the PDF is a
way to file and print it, and the text is what the content hash and the
signature cover. Every page's footer carries the case id, the content hash
and the signing key, so a single printed page can be matched to its report.

Typeset in IBM Plex (app/fonts, SIL Open Font Licence), the app's own family.
"""
from __future__ import annotations

import io
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
from xml.sax.saxutils import escape

from .evidence import CONTENT_HASH_MARK
from .signing import SIGNATURE_MARK

FONT_DIR = Path(__file__).resolve().parent / "fonts"
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
    return Paragraph(escape("" if text is None else str(text)), style)


def _num(value: Any) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{v:,.6f}".rstrip("0").rstrip(".") if v else "0"


def render_pdf(report: dict[str, Any], sealed_text: str) -> bytes:
    _register_fonts()
    st = _styles()
    case = report["case"]
    attribution = report.get("attribution") or {}
    confidence = report.get("confidence") or {}
    screening = report.get("risk_screening") or {}
    digest, key = _seal_facts(sealed_text)
    case_id = case["case_id"]

    story: list[Any] = []
    story.append(_p("EXCHEQUER · CRYPTOCURRENCY TRACE REPORT", st["micro"]))
    story.append(_p(f"Case {case_id}", st["small"]))
    story.append(Spacer(1, 8))

    # -- the finding --------------------------------------------------------
    exchange = attribution.get("exchange")
    heading = exchange or "No exchange reached"
    story.append(_p("WHERE THE MONEY WENT" if case["direction"] == "outgoing" else "WHO FUNDED THE ADDRESS",
                    st["micro"]))
    finding = ParagraphStyle("f2", parent=st["finding"], textColor=GREEN if exchange else INK)
    story.append(_p(heading, finding))
    story.append(_p(report.get("summary", ""), st["lede"]))

    # -- key facts ----------------------------------------------------------
    facts = [
        ("Reported address", case["reported_address"], True),
        ("Chain · asset · direction", f"{case['chain']} · {case['asset']} · {case['direction']}", False),
        ("Traced at", case.get("traced_at", ""), False),
    ]
    if exchange:
        facts += [
            ("Address to ask the exchange about", attribution.get("exchange_address", ""), True),
            ("Wallet", attribution.get("exchange_wallet_label") or "", False),
            ("Hops from the reported address", attribution.get("hop_count", ""), False),
        ]
        prorata = attribution.get("prorata") or {}
        if prorata.get("status") == "estimated":
            facts.append(("Reported funds that likely arrived (pro-rata)",
                          f"≈ {_num(prorata.get('estimated'))} of {_num(prorata.get('sent'))} "
                          f"{attribution.get('value_currency', '')}", False))
    if confidence.get("score") is not None:
        facts.append(("Confidence", f"{confidence['score']:.2f} ({confidence.get('band', '')})", False))
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
        story += [_p("HOW SURE", st["micro"]), _p(confidence["summary"], st["cell"])]

    # -- how to verify --------------------------------------------------------
    verify = Table([[Paragraph(
        "<font name='Plex-Bold'>Checking this report.</font> The signed text report is attached to "
        f"this PDF as <font name='PlexMono'>{escape(_attachment_name(case_id))}</font> (your PDF reader's "
        "attachments panel) and printed in Part 2. Its last lines carry a SHA-256 content hash and an "
        "Ed25519 signature made with the issuing server's key. Check the attached file at "
        "<font name='PlexMono'>/verify</font> on that server: any edit breaks the signature. Text copied "
        "from the printed pages will not verify, because copying from a PDF changes line breaks.<br/>"
        f"<font name='PlexMono' size='7.5'>content SHA-256 {escape(digest)}<br/>"
        f"signing key {escape(key or 'none (unsigned)')}</font>", st["small"])]], colWidths=[None])
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
        story.append(_p("No address in the trace is on a sanctions, mixer, Tether-freeze or stolen-funds list.",
                        st["cell"]))
    else:
        for m in matches[:8]:
            colour = RED if m.get("category") in ("sanctioned", "mixer") else AMBER
            line = (f"<font name='Plex-Bold' color='{colour.hexval()}'>{escape(str(m.get('category', '')).title())}</font> · "
                    f"<font name='PlexMono'>{escape(m.get('address', ''))}</font> · "
                    f"{escape(str(m.get('entity') or m.get('label') or ''))}")
            story.append(Paragraph(line, st["cell"]))
        if len(matches) > 8:
            story.append(_p(f"…and {len(matches) - 8} more, listed in Part 2.", st["small"]))

    # -- the route ------------------------------------------------------------
    path = report.get("trace_path") or []
    if len(path) > 1:
        story.append(_p("THE ROUTE (PRINCIPAL PATH)", st["micro"]))
        route = [[_p("Hop", st["small"]), _p("Address", st["small"]), _p("Label", st["small"]),
                  _p("Received", st["small"])]]
        for step in path:
            label = step.get("label") or step.get("exchange") or ""
            if not label and step.get("address") == attribution.get("exchange_address"):
                label = attribution.get("exchange_wallet_label") or ""
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
            story.append(Paragraph(f"• {escape(item)}", st["small"]))
        if len(limits) > 3:
            story.append(_p(f"…{len(limits) - 3} more in Part 2.", st["small"]))

    # -- part 2 ---------------------------------------------------------------
    story += [CondPageBreak(90 * mm), Spacer(1, 10), _p("Part 2 · The signed text report", st["h2"]),
              _p("The text the content hash and signature cover, for reading. Lines too long for the "
                 "page wrap onto the next line; the exact file is attached to this PDF.", st["small"]),
              Spacer(1, 6), Preformatted(sealed_text, st["pre"], maxLineLength=118, newLineChars="")]

    buffer = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("PlexMono", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm,
                          f"Exchequer case {case_id[:8]} · SHA-256 {digest[:16]}… · key {key or 'unsigned'}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Exchequer case {case_id}", author="Exchequer", subject="Cryptocurrency trace report",
        creator="Exchequer",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return _attach(buffer.getvalue(), _attachment_name(case_id), sealed_text.encode("utf-8"))


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
