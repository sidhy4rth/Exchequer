"""Builds the two documents for the B.Tech Director (19 September 2026):

  docs/Exchequer-Proposal.pdf         -- request for institutional support
  docs/Exchequer-Research-Report.pdf  -- crypto fundamentals, the research, and what is built

Run:  cd ~/exchequer && backend/.venv/bin/python docs/make_pdfs.py
Every figure in here comes from README.md, RESEARCH.md, JUDGE_QA.md or DEMO.md.
The mark is the one in frontend/src/components/Mark.jsx: a 4x4 chequer, rounded,
one square red -- the sum being traced.
"""
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle, PageBreak, KeepTogether, Flowable,
                                NextPageTemplate)

for name, path in [("Georgia", "/System/Library/Fonts/Supplemental/Georgia.ttf"),
                   ("GeorgiaB", "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"),
                   ("GeorgiaI", "/System/Library/Fonts/Supplemental/Georgia Italic.ttf")]:
    pdfmetrics.registerFont(TTFont(name, path))

# ---- palette from NOTES.md (the case-file look) ----
INK = colors.HexColor("#16191d"); MUTED = colors.HexColor("#5b6169"); FAINT = colors.HexColor("#8a9098")
RULE = colors.HexColor("#d9d6cf"); PAPER = colors.HexColor("#f5f4f0"); LIGHT = colors.HexColor("#ececea")
NAVY = colors.HexColor("#1f3a5f"); RED = colors.HexColor("#b3261e"); RED_LIT = colors.HexColor("#ff5c5c")
GREEN = colors.HexColor("#1d7a4c"); AMBER = colors.HexColor("#9a5b00")

W, H = A4
M = 20 * mm
CW = W - 2 * M

def S(name, **kw):
    base = dict(fontName="Helvetica", fontSize=10, leading=14, textColor=INK, alignment=TA_JUSTIFY)
    base.update(kw)
    return ParagraphStyle(name, **base)

st = {
    "h1": S("h1", fontName="GeorgiaB", fontSize=17, leading=21, spaceAfter=8, alignment=TA_LEFT),
    "h2": S("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=10, spaceAfter=3, textColor=NAVY, alignment=TA_LEFT),
    "p": S("p", spaceAfter=6),
    "lead": S("lead", fontName="Georgia", fontSize=11.5, leading=17, spaceAfter=8),
    "small": S("small", fontSize=8.5, leading=11.5, textColor=MUTED),
    "bullet": S("bullet", leftIndent=12, bulletIndent=2, spaceAfter=3),
    "num": S("num", leftIndent=16, bulletIndent=2, spaceAfter=3),
    "toc": S("toc", fontName="Georgia", fontSize=11.5, leading=20, leftIndent=26, bulletIndent=0, alignment=TA_LEFT, bulletFontName="GeorgiaB", bulletColor=RED),
    "cell": S("cell", fontSize=8.8, leading=11.5, alignment=TA_LEFT),
    "cellh": S("cellh", fontName="Helvetica-Bold", fontSize=8.4, leading=11, alignment=TA_LEFT, textColor=colors.white),
    "mono": S("mono", fontName="Courier", fontSize=8.6, leading=11, alignment=TA_LEFT),
    "def": S("def", spaceAfter=5),
    "sig": S("sig", fontSize=10, leading=14, alignment=TA_LEFT),
    "ah2": S("ah2", fontName="GeorgiaB", fontSize=12, leading=16, spaceBefore=12, spaceAfter=5, alignment=TA_LEFT),
    "aquote": S("aquote", fontName="GeorgiaI", fontSize=9.5, leading=13.5, leftIndent=14, rightIndent=10, textColor=MUTED, spaceAfter=4),
    "aurl": S("aurl", fontName="Courier", fontSize=7.8, leading=10.5, leftIndent=14, textColor=NAVY, wordWrap="CJK", spaceAfter=5, alignment=TA_LEFT),
    "colophon": S("colophon", fontName="GeorgiaI", fontSize=9, leading=13, textColor=MUTED, alignment=1),
}

def P(t, s="p"): return Paragraph(t, st[s])
def H2(t): return Paragraph(t, st["h2"])
def B(items): return [Paragraph(i, st["bullet"], bulletText="•") for i in items]
def N(items): return [Paragraph(i, st["num"], bulletText=f"{n}.") for n, i in enumerate(items, 1)]
def D(term, body): return Paragraph(f"<b>{term}</b> — {body}", st["def"])
def Sp(h=6): return Spacer(1, h)

def mark(c, x, y, size, ink=INK, red=RED):
    """The chequer at (x, y) = bottom-left, y-down cells like the SVG; red at row 2, col 2; rounded clip."""
    s = size / 4
    c.saveState()
    path = c.beginPath(); path.roundRect(x, y, size, size, size * 0.14); c.clipPath(path, stroke=0, fill=0)
    for i in range(4):          # row, from the top
        for j in range(4):      # column
            if (i + j) % 2 == 0:
                c.setFillColor(red if (i, j) == (2, 2) else ink)
                c.rect(x + j * s, y + size - (i + 1) * s, s, s, fill=1, stroke=0)
    c.restoreState()

class H1(Flowable):
    """Section head: a short red rule, the number in red, the title in Georgia."""
    def __init__(self, text):
        super().__init__()
        num, _, title = text.partition(". ")
        self.num, self.title = (num, title) if (title and num.isdigit()) else ("", text)
    def wrap(self, aw, ah):
        self.aw = aw
        self.para = Paragraph(self.title, st["h1"])
        _, ph = self.para.wrap(aw - (34 if self.num else 0), ah)
        self.ph = ph
        self.h = ph + 22
        return aw, self.h
    def draw(self):
        c = self.canv
        c.setFillColor(RED); c.rect(0, self.h - 3, 22, 2.2, fill=1, stroke=0)
        if self.num:
            c.setFont("GeorgiaB", 17); c.setFillColor(RED); c.drawString(0, self.ph - 16, self.num)
            self.para.drawOn(c, 34, 0)
        else:
            self.para.drawOn(c, 0, 0)
    def getSpaceBefore(self): return 16

def table(rows, widths, header=True, zebra=True):
    data = [[Paragraph(c, st["cellh"] if (header and r == 0) else st["cell"]) for c in row]
            for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LINEBELOW", (0, -1), (-1, -1), 0.5, RULE),
             ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), INK), ("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, 0), (-1, 0), 5)]
    if zebra:
        for r in range(1, len(rows)):
            if r % 2 == 0:
                style.append(("BACKGROUND", (0, r), (-1, r), PAPER))
    t.setStyle(TableStyle(style))
    return t

class Rule(Flowable):
    def __init__(self, color=RULE, w=0.6): super().__init__(); self.c = color; self.w = w
    def wrap(self, aw, ah): self.aw = aw; return aw, 8
    def draw(self):
        self.canv.setStrokeColor(self.c); self.canv.setLineWidth(self.w); self.canv.line(0, 4, self.aw, 4)

class Callout(Flowable):
    """A paper-coloured box with a coloured left bar, for one paragraph of emphasis."""
    def __init__(self, text, color=NAVY):
        super().__init__(); self.text = text; self.color = color
    def wrap(self, aw, ah):
        self.aw = aw
        self.para = Paragraph(self.text, st["p"])
        _, ph = self.para.wrap(aw - 26, ah)
        self.h = ph + 18
        return aw, self.h
    def draw(self):
        c = self.canv
        c.setFillColor(PAPER); c.rect(0, 0, self.aw, self.h, fill=1, stroke=0)
        c.setFillColor(self.color); c.rect(0, 0, 3, self.h, fill=1, stroke=0)
        self.para.drawOn(c, 16, 9)

class Colophon(Flowable):
    def __init__(self, text): super().__init__(); self.text = text
    def wrap(self, aw, ah): self.aw = aw; return aw, 70
    def draw(self):
        c = self.canv
        c.setStrokeColor(RULE); c.setLineWidth(0.5); c.line(self.aw / 2 - 60, 66, self.aw / 2 + 60, 66)
        mark(c, self.aw / 2 - 9, 40, 18)
        para = Paragraph(self.text, st["colophon"]); para.wrap(self.aw * 0.7, 40)
        para.drawOn(c, self.aw * 0.15, 40 - para.height - 6)

class Pipeline(Flowable):
    """The seven stages of a trace, drawn as a column of boxes."""
    ROWS = [
        ("chain_data", "Picks the provider for the chain and asset. Ethereum: Etherscan; BSC: NodeReal; Tron: TronGrid. Rate-limit aware, retries with backoff."),
        ("graph_builder", "Breadth-first walk, default 4 hops, outgoing (where the money went) or incoming (who funded it). Highest-value branches first; dust dropped; only transfers made after the funds arrived."),
        ("exchange_matcher", "Exact lookup against that chain's own label file. Labels are never shared between chains."),
        ("risk_matcher", "Exact lookup against the OFAC SDN list. Stops the trace at a mixer."),
        ("pattern_detection", "Peel chain and amount split, as fixed arithmetic rules that print their thresholds."),
        ("scoring", "Hop proximity 40% + amount correlation 35% + match directness 25%."),
        ("report", "Graph, exchange, confidence, flags, evidence manifest; stored in SQLite; exported as text and JSON."),
    ]
    def wrap(self, aw, ah): self.aw = aw; self.h = len(self.ROWS) * 46 + 30; return aw, self.h
    def draw(self):
        c = self.canv
        bx, bw, bh = 0, 132, 30
        c.setFont("Helvetica-Bold", 9); c.setFillColor(RED)
        c.drawString(bx + 8, self.h - 12, "reported address")
        top = self.h - 22
        for i, (name, desc) in enumerate(self.ROWS):
            y = top - i * 46 - bh
            c.setStrokeColor(INK); c.setLineWidth(0.8); c.setFillColor(colors.white)
            c.rect(bx, y, bw, bh, fill=1, stroke=1)
            c.setFillColor(RED); c.rect(bx, y, 3, bh, fill=1, stroke=0)
            c.setFillColor(INK); c.setFont("Courier-Bold", 9); c.drawString(bx + 10, y + 11, name + ".py")
            para = Paragraph(desc, st["cell"]); pw, ph = para.wrap(self.aw - bw - 18, 60)
            para.drawOn(c, bx + bw + 14, y + bh - ph + 2)
            if i < len(self.ROWS) - 1:
                c.setStrokeColor(MUTED); c.line(bx + bw / 2, y, bx + bw / 2, y - 12)
                c.setFillColor(MUTED)
                p = c.beginPath(); p.moveTo(bx + bw / 2 - 3, y - 10); p.lineTo(bx + bw / 2 + 3, y - 10); p.lineTo(bx + bw / 2, y - 16); p.close()
                c.drawPath(p, fill=1, stroke=0)

class HopExample(Flowable):
    """A small drawn trace: reported address -> two hops -> exchange, with amounts."""
    def wrap(self, aw, ah): self.aw = aw; self.h = 92; return aw, self.h
    def draw(self):
        c = self.canv
        nodes = [("reported", "0x7a1f…", "12.0 ETH out", INK), ("hop 1", "0x93c4…", "11.9 ETH", INK),
                 ("hop 2", "0xe0b2…", "11.7 ETH", AMBER), ("Binance 14", "0x28c6…", "labelled", GREEN)]
        n = len(nodes); gap = (self.aw - 40) / (n - 1); y = 50
        for i, (lab, addr, amt, col) in enumerate(nodes):
            x = 20 + i * gap
            if i < n - 1:
                c.setStrokeColor(RED); c.setLineWidth(2); c.line(x + 9, y, x + gap - 9, y)
            c.setFillColor(colors.white); c.setStrokeColor(col); c.setLineWidth(1.6); c.circle(x, y, 9, fill=1, stroke=1)
            c.setFillColor(INK); c.setFont("Helvetica-Bold", 8.5); c.drawCentredString(x, y + 16, lab)
            c.setFont("Courier", 8); c.drawCentredString(x, y - 22, addr)
            c.setFont("Helvetica", 8); c.setFillColor(MUTED); c.drawCentredString(x, y - 33, amt)
        c.setFillColor(MUTED); c.setFont("Helvetica-Oblique", 8)
        c.drawString(0, 2, "Traced funds in red. Hop 2 is an unlabelled wallet whose only outgoing transfers sweep to Binance 14: a probable deposit address (amber).")

# ---------------------------------------------------------------------------
def build(path, story, header_title, cover_info):
    def on_page(c, doc):
        c.saveState()
        mark(c, M, H - M + 1, 11)
        c.setFont("Helvetica", 8); c.setFillColor(MUTED)
        c.drawString(M + 17, H - M + 4, header_title)
        c.drawRightString(W - M, H - M + 4, "Sidhyarth · Alliance University")
        c.setStrokeColor(RULE); c.setLineWidth(0.5); c.line(M, H - M - 3, W - M, H - M - 3)
        c.line(M, M - 4, W - M, M - 4)
        c.drawString(M, M - 15, "Exchequer · 19 September 2026")
        c.setFillColor(RED); c.rect(W - M - 30, M - 14, 4, 4, fill=1, stroke=0)
        c.setFillColor(MUTED); c.drawRightString(W - M, M - 15, f"{doc.page}")
        c.restoreState()
    def on_cover(c, doc):
        title, subtitle, meta, numbers = cover_info
        c.saveState()
        c.setFillColor(INK); c.rect(0, 0, W, H, fill=1, stroke=0)
        # a faint chequer field across the top band, the mark's own geometry at scale
        c.setFillColor(colors.HexColor("#1e2126"))
        cell = 18
        for i in range(0, 4):
            for j in range(0, int(W / cell) + 1):
                if (i + j) % 2 == 0:
                    c.rect(j * cell, H - (i + 1) * cell, cell, cell, fill=1, stroke=0)
        mark(c, M, H - M - 90, 64, ink=LIGHT, red=RED_LIT)
        c.setFillColor(LIGHT); c.setFont("Helvetica", 8.5)
        c.drawString(M + 78, H - M - 44, "E X C H E Q U E R")
        c.setFillColor(FAINT); c.drawString(M + 78, H - M - 58, "Smart India Hackathon 2026 · SIH26183 · Ministry of Home Affairs")
        # title block
        y = H * 0.56
        c.setFillColor(RED_LIT); c.rect(M, y + 58, 28, 3, fill=1, stroke=0)
        c.setFillColor(colors.white); c.setFont("GeorgiaB", 34)
        for line in title:
            c.drawString(M, y + 18, line); y -= 40
        sub = Paragraph(subtitle, ParagraphStyle("cs", fontName="Georgia", fontSize=13.5, leading=19, textColor=LIGHT))
        sub.wrap(CW * 0.8, 200); sub.drawOn(c, M, y + 18 - sub.height + 22)
        y = y + 18 - sub.height + 22
        # meta
        y -= 40
        c.setStrokeColor(colors.HexColor("#33373d")); c.setLineWidth(0.6); c.line(M, y + 14, M + CW * 0.8, y + 14)
        for label, value in meta:
            c.setFont("Helvetica-Bold", 8.5); c.setFillColor(FAINT); c.drawString(M, y, label.upper())
            c.setFont("Helvetica", 9.5); c.setFillColor(LIGHT); c.drawString(M + 92, y, value); y -= 17
        # key numbers strip
        yb = M + 62
        c.setStrokeColor(colors.HexColor("#33373d")); c.line(M, yb + 30, W - M, yb + 30)
        x = M
        for big, small in numbers:
            c.setFont("GeorgiaB", 20); c.setFillColor(colors.white); c.drawString(x, yb + 4, big)
            c.setFont("Helvetica", 8); c.setFillColor(FAINT); c.drawString(x, yb - 9, small)
            x += CW / len(numbers)
        c.setFont("Helvetica", 8); c.setFillColor(FAINT)
        c.drawString(M, M + 6, "Prepared for the Director, B.Tech, Alliance University  ·  19 September 2026")
        c.drawRightString(W - M, M + 6, "github.com/sidhy4rth/Exchequer  ·  private")
        c.restoreState()
    doc = BaseDocTemplate(path, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=M + 6, bottomMargin=M + 4,
                          title=header_title, author="Sidhyarth, Alliance University", subject="Exchequer")
    frame = Frame(M, M + 4, CW, H - 2 * M - 10, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    cover_frame = Frame(M, M, CW, H - 2 * M, id="c")
    doc.addPageTemplates([PageTemplate(id="cover", frames=[cover_frame], onPage=on_cover),
                          PageTemplate(id="body", frames=[frame], onPage=on_page)])
    doc.build(story)

def cover():
    return [Spacer(1, 1), NextPageTemplate("body"), PageBreak()]

# ---------------------------------------------------------------------------
#  RESEARCH.md, rendered as an appendix.  A small converter for the subset of
#  Markdown that file uses: ## headings, > quotes, - lists, **bold**, *italic*,
#  <https://links>, --- rules.  Every URL is a live link on its own line.
import re, os

def _inline(t):
    t = t.replace("₹", "Rs. ").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\*)(.+?)(?<!\*)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"`(.+?)`", r"<font face='Courier' size='8.5'>\1</font>", t)
    return t

class QuoteBlock(Flowable):
    """A quoted passage with a red hairline down its left, the way the case view marks evidence."""
    def __init__(self, paras): super().__init__(); self.paras = paras
    def wrap(self, aw, ah):
        self.aw = aw; self.h = 6
        self.flow = [Paragraph(t, st["aquote"]) for t in self.paras]
        for f in self.flow:
            _, ph = f.wrap(aw - 4, ah); self.h += ph + 4
        return aw, self.h
    def draw(self):
        c = self.canv
        c.setFillColor(RED); c.rect(0, 2, 1.6, self.h - 4, fill=1, stroke=0)
        y = self.h - 3
        for f in self.flow:
            y -= f.height; f.drawOn(c, 4, y); y -= 4

def _text_and_urls(t):
    """Split a paragraph at <http…> links: prose stays a paragraph, each URL becomes its own link line."""
    out = []
    parts = re.split(r"<(https?://[^>]+)>", t)
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(Paragraph(f'<link href="{part}">{part}</link>', st["aurl"]))
        else:
            part = part.lstrip(" .,:;").rstrip() if i > 0 else part.strip()
            if part:
                out.append(Paragraph(_inline(part), st["p"]))
    return out

def research_appendix(path):
    text = open(path, encoding="utf8").read()
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    blocks = re.split(r"\n\s*\n", text.strip())
    flow = []
    for b in blocks:
        lines = b.strip("\n").splitlines()
        first = lines[0]
        if first.startswith("# "):
            continue                       # the file's own title; the appendix has one
        if first.strip() == "---":
            flow.append(Rule()); continue
        if first.startswith("## "):
            flow.append(KeepTogether([Paragraph(_inline(first[3:]), st["ah2"])])); continue
        if first.startswith("> "):
            paras, cur = [], []
            for l in lines:
                l = l[1:].strip()
                if l: cur.append(l)
                elif cur: paras.append(" ".join(cur)); cur = []
            if cur: paras.append(" ".join(cur))
            flow.append(QuoteBlock([_inline(x) for x in paras])); continue
        if first.startswith("- "):
            items, cur = [], []
            for l in lines:
                if l.startswith("- "):
                    if cur: items.append(" ".join(cur))
                    cur = [l[2:].strip()]
                else: cur.append(l.strip())
            if cur: items.append(" ".join(cur))
            for it in items:
                for f in _text_and_urls(it):
                    f.style = st["bullet"] if f.style is st["p"] else f.style
                    flow.append(f if f.style is not st["bullet"] else Paragraph(f.text, st["bullet"], bulletText="•"))
            continue
        flow.extend(_text_and_urls(" ".join(l.strip() for l in lines)))
    return flow

# ===========================================================================
#  DOCUMENT 1 -- THE PROPOSAL
# ===========================================================================
def proposal():
    s = cover()

    s += [H1("1. In one page"),
          P("Exchequer is a piece of software I have built for Smart India Hackathon 2026, for a problem statement set by the "
            "Ministry of Home Affairs. A victim of a cyber-fraud reports the cryptocurrency wallet address they paid into. "
            "Exchequer follows the money outward from that address, hop by hop across the public blockchain, flags the "
            "known laundering shapes it passes, identifies the cryptocurrency exchange where the funds finally landed, and "
            "produces a report an investigating officer can attach to a lawful request to that exchange. The exchange, "
            "which by law holds the customer's identity, is the only party that can turn an address into a person; "
            "Exchequer's job is to get the officer to the right address with the evidence in order.", "lead"),
          P("The problem is not small. By the Ministry's own figures tabled in the Lok Sabha on 2 December 2025, Indian "
            "citizens reported losses of <b>Rs. 2,290 crore</b> to cyber fraud in 2022, <b>Rs. 7,465 crore</b> in 2023 and "
            "<b>Rs. 22,845 crore</b> in 2024, from 2.27 million complaints on the National Cyber Crime Reporting Portal in that "
            "year alone. Much of the proceeds leave the country as stablecoins: Chainalysis measured stablecoins at 84% "
            "of illicit cryptocurrency volume in 2025, and the UN Office on Drugs and Crime describes USDT on the Tron "
            "blockchain as the “preferred choice” of the South-East Asian cyber-fraud operations that target Indian victims."),
          P("The software exists and works today. It traces Ethereum, BNB Smart Chain and Tron; it matches against 407 "
            "exchange wallets that were each verified on-chain before being accepted; it screens every address against the "
            "US Treasury sanctions list; it hashes every piece of evidence so a report can be checked in court; it has 234 "
            "automated tests that run on every change; and it is deployed on a public URL for judges to use. I measured "
            "my own detection rules against 88 real wallets and published the results, including the inconvenient ones."),
          Callout("<b>What I am asking for.</b> The University's support for the running costs of the project \u2014 paid "
                  "data-provider tiers and hosting, and travel to the SIH finale \u2014 a faculty mentor from the department, and a "
                  "letter of introduction so that I can put the tool in front of a working cyber-crime cell. Section 6 sets "
                  "out what each would enable; I would bring a line-item budget to a follow-up meeting."),
          ]

    s += [H1("2. The problem, precisely"),
          P("A cyber-fraud complaint in India starts at the state police or the National Cyber Crime Reporting Portal. "
            "When the victim paid in cryptocurrency, the officer holds one thing: a wallet address. Every transaction that "
            "address ever made is public and permanent, but reading that history by hand means opening a block explorer, "
            "copying each outgoing transfer, opening the recipient, and repeating, across dozens of wallets that the "
            "launderer created precisely to make this tedious. The commercial tools that automate it (Chainalysis, TRM Labs, "
            "Elliptic) cost lakhs per seat per year, are licensed to central agencies, and produce scores from models "
            "that cannot be cross-examined."),
          P("What the officer actually needs is narrower than what those tools sell. The Prevention of Money-Laundering Act "
            "made cryptocurrency exchanges <i>reporting entities</i> on 7 March 2023: they must register with FIU-IND, keep "
            "records that “enable it to reconstruct individual transactions” and identify the customer (section 12), "
            "and hand them over on a summons under section 50 or a police notice. So the whole investigative question "
            "reduces to: <b>which exchange, which deposit address, which transaction hashes, what amounts, when.</b> "
            "That is exactly, and only, what Exchequer produces."),
          H2("Why a student project can do this at all"),
          P("Because the data is public. Every transfer on Ethereum, BSC and Tron can be read from free explorer APIs, and "
            "the exchanges' own hot-wallet addresses are published by those same explorers. The engineering problem is to "
            "walk the graph efficiently within a free API's rate limit, to match honestly against published labels, to "
            "refuse to guess, and to write down what the tool did in a form that survives a courtroom. None of that "
            "needs proprietary data. It needs care, and it needs tests.")]

    s += [H1("3. What I have built"),
          P("The repository holds roughly 9,700 lines of application code across a Python (FastAPI) backend and a React "
            "frontend, written between 3 and 18 September 2026, with 65 commits and a continuous-integration pipeline that "
            "runs the full test suite and the frontend build on every push. The accompanying research report describes "
            "each part in detail; the summary is:"),
          table([["Capability", "State on 19 September 2026"],
                 ["Chains and assets", "Ethereum (ETH, USDT, USDC), BNB Smart Chain (BNB, USDT, USDC), Tron (TRX, USDT). Forward (where did it go) and reverse (who funded it) traces."],
                 ["Exchange attribution", "407 verified wallets across 18 exchanges, including CoinDCX. Each was imported by script from the explorer's own label page and checked on-chain before entry; four mislabelled contracts were rejected by that check."],
                 ["Deposit-address inference", "Names the unlabelled wallet one hop before the exchange when its entire history is sweeps to one labelled wallet, scores it lower, and says what would confirm it. Fired on 0 of 48 control wallets."],
                 ["Sanctions screening", "Every address checked against the OFAC SDN list of 4 September 2026 (124 Ethereum, 282 Tron, 1 BSC addresses). A trace stops at a mixer by design."],
                 ["Pattern detection", "Peel chain and amount split as fixed arithmetic rules that print their thresholds. Measured on 40 documented-illicit and 48 ordinary wallets; results published in the README."],
                 ["Time rule", "Only transfers made at or after the traced funds arrived are followed, so a busy wallet's unrelated prior history is never reported as the victim's money."],
                 ["Swap detection", "A swap at a labelled DEX router is read from the transaction receipt and reported with the output asset and where to resume."],
                 ["Cross-case correlation", "Finds intermediaries shared by traces from different complaints: on 15 September three Phish/Hack-labelled wallets were found to share 61 intermediaries, four of them inferred Binance deposit addresses."],
                 ["Evidence integrity", "Every provider response is SHA-256 hashed with its request and time; the report carries the manifest and ends with a content hash over itself."],
                 ["Confidence score", "A plain weighted sum of three printed inputs. No model, no clustering. Null, not zero, when nothing was attributed."],
                 ["Interface", "A case view with a hop-layered flow diagram, a transfers feed, a sealed text/JSON report, a projector “present mode”, and a live ledger backdrop."],
                 ["Quality", "234 tests, green CI, disk-persistent response cache (flagship trace 43 s cold, 0.12 s cached), Docker image deployed on Railway."],
                 ], [40 * mm, W - 2 * M - 40 * mm]),
          Sp(8),
          P("Three commitments run through the design and I would ask that any support keep them: every attribution is an "
            "exact match against a file a human can open; every rule prints the numbers it compared; and where my sources "
            "said less than I did, I changed my claim, not the source.")]

    s += [H1("4. Why this matters to the University"),
          *B(["<b>A national problem statement, in the open.</b> SIH26183 is set by the Ministry of Home Affairs. A working, "
              "tested, hosted submission with published validation is the kind of result the department can point to, "
              "whatever the competition outcome.",
              "<b>Publishable work.</b> The validation study (two pattern rules, 88 real wallets, a 68-point threshold grid) and "
              "the deposit-address inference rule are, to my knowledge, not written up anywhere in the open literature at "
              "this level of reproducibility. With a mentor I would like to write it as a short paper.",
              "<b>A relationship with law enforcement.</b> The tool is only finished when an officer has used it on a real "
              "complaint. A letter from the University opens that door in a way a student on his own cannot.",
              "<b>A foundation for further projects.</b> The upgrade path (Bitcoin, more chains, PDF reports, a Postgres "
              "backend) is a set of well-scoped tasks that later batches can take up as course or capstone work."])]

    s += [H1("5. Plan for the next six months"),
          table([["When", "Milestone", "Outcome"],
                 ["Oct 2026", "SIH 2026 next round (same judges as the internal round)", "Demo on the hosted instance; four rehearsed cases; Q&A prepared from JUDGE_QA.md"],
                 ["Oct–Nov 2026", "Paid data tiers", "Etherscan Lite unlocks Polygon, Arbitrum, Optimism, Base and Avalanche through code already present; Tron and BSC tiers remove the per-second ceiling that makes a cold trace take 20–40 s"],
                 ["Nov 2026", "PDF report renderer", "The text report already carries the evidence manifest; the PDF is a renderer, not new analysis"],
                 ["Nov–Dec 2026", "Pilot with a cyber-crime cell", "Five real complaints traced with an officer present; findings written up; the tool changed where it fell short"],
                 ["Dec 2026–Jan 2027", "Bitcoin adapter", "A different transaction model (UTXO); its own module, first item on the upgrade path"],
                 ["Jan–Mar 2027", "Postgres, concurrency guard, frontend tests", "Multi-user readiness for a shared instance"],
                 ["Mar 2027", "Short paper", "The validation study and the deposit-address rule, with the mentor as co-author"],
                 ], [28 * mm, 52 * mm, W - 2 * M - 80 * mm])]

    s += [H1("6. What support would enable"),
          P("The project has run so far on free API keys, a free hosting trial and my own time. Each of the items below is "
            "modest; none is a salary, a proprietary data licence or a commercial analytics subscription. Everything the "
            "tool matches against is public and stays public. I would rather agree the direction first and bring exact "
            "figures to a second meeting."),
          table([["Item", "What it enables"],
                 ["Etherscan Lite plan", "Five more EVM chains (Polygon, Arbitrum, Optimism, Base, Avalanche) through code already present, and a higher rate limit"],
                 ["TronGrid and NodeReal paid tiers", "Removes the free-tier per-second ceiling that makes a cold trace take 20\u201340 s on Tron and BSC"],
                 ["Hosting", "A persistent instance with a volume, so the demo is always up rather than brought up two days before a round"],
                 ["Domain and e-mail", "A stable address to give an officer or a judge"],
                 ["SIH finale travel and stay", "Only if the finale is held outside Bengaluru and SIH does not cover it"],
                 ["Printing and demo material", "A poster and printed sample reports for the room"],
                 ], [46 * mm, W - 2 * M - 46 * mm])]

    s += [H1("7. What I ask for beyond costs"),
          *N(["<b>A faculty mentor</b> from the department, ideally with an interest in security, networks or data systems, "
              "for a fortnightly review and as co-author on the paper.",
              "<b>A letter of introduction</b> on University letterhead to a police cyber-crime cell (Bengaluru City or Karnataka "
              "CID), asking for a supervised pilot on closed or ongoing cases at the officer's discretion.",
              "<b>A demonstration slot</b> to the department, so that other students can see the problem and the upgrade path.",
              "<b>Recognition of the work</b> as project credit, if the department's rules allow it."])]

    s += [H1("8. Accountability"),
          *B(["A one-page progress note to the Director at the end of every month, with the commit log and the test count.",
              "The repository stays under version control with continuous integration; the Director or mentor is given read access.",
              "The hosted instance is available for the department to try at any time; the demo sign-in is admin / admin and is not access control.",
              "Any change to a detection rule requires two-sided tests and a written explanation in the README before it ships. "
              "This is already how the project works and I would keep it."])]

    s += [H1("9. About me"),
          P("I am Sidhyarth, a first-year B.Tech student at Alliance University. I built Exchequer on my own for Smart "
            "India Hackathon 2026 \u2014 the backend, the frontend, the label pipeline, the validation study and the "
            "documentation \u2014 and I present it. I would be glad to demonstrate the software live in the Director's "
            "office at any time; a trace of a real fraud address takes under a minute."),
          Sp(30),
          P("Sidhyarth<br/>B.Tech, Alliance University", "sig"),
          Sp(18),
          P("Attached: <i>Exchequer — Research Foundations and Work to Date</i>, the companion report that explains the "
            "cryptocurrency concepts involved, the published evidence the project rests on, and everything built so far.", "small")]
    return s

# ===========================================================================
#  DOCUMENT 2 -- RESEARCH FOUNDATIONS AND WORK TO DATE
# ===========================================================================
def report():
    s = cover()

    s += [H1("Contents"),
          *[Paragraph(t, st["toc"], bulletText=f"{n}") for n, t in enumerate(["The problem in one paragraph",
              "Cryptocurrency fundamentals, for a reader who has not needed them before",
              "How laundering looks on a public ledger",
              "What the published evidence says, claim by claim",
              "The Indian legal framework, and what it needs from a tool",
              "What we built: the pipeline, stage by stage",
              "How we know it behaves: validation on real wallets",
              "What it does not do, stated plainly",
              "Timeline of the work",
              "What comes next",
              "References",
              "Appendix \u2014 RESEARCH.md in full: every claim, the source read, the passage, the verdict, the link"], 1)],
          Sp(10)]

    # ---- 1 ----
    s += [H1("1. The problem in one paragraph"),
          P("A victim pays a fraudster in cryptocurrency and reports the address they paid into. Every transaction that "
            "address ever made is public, permanent and free to read — but the launderer has moved the money through a "
            "dozen throwaway wallets, possibly split it, possibly swapped it for another token, and finally sold it for "
            "rupees or dollars at an exchange. The exchange knows who its customer is; the blockchain does not. So the "
            "investigator's task is to follow the money across the public part of its journey to the exchange's door, and "
            "to arrive there with evidence in a form the exchange's compliance team can match against its own records. "
            "Exchequer automates that journey and refuses to guess at any point along it.", "lead")]

    # ---- 2 ----
    s += [H1("2. Cryptocurrency fundamentals"),
          P("This section is written for a reader who has not needed these concepts before. Each term is defined the way "
            "Exchequer uses it; the definitions are conventional."),
          H2("2.1 The ledger"),
          D("Blockchain", "a public, append-only ledger of transactions, copied across thousands of computers. Once a "
            "transaction is recorded in a <i>block</i> it cannot be altered or removed, and anyone can read it. This is the "
            "single fact that makes tracing possible: the launderer cannot delete the trail."),
          D("Transaction", "a signed instruction that moves value from one address to another. It carries the sender, the "
            "recipient, the amount, the asset, a timestamp (of the block it was included in) and a <i>transaction hash</i> — a "
            "unique 64-character identifier. The hash is what an officer cites in a legal request."),
          D("Address", "a public identifier, such as <font face='Courier'>0x60d02e09…</font> on Ethereum or "
            "<font face='Courier'>TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE</font> on Tron, that can receive and send value. "
            "An address is controlled by whoever holds its <i>private key</i>. Nothing on the blockchain records who that is."),
          D("Wallet", "software that holds private keys and signs transactions. One person can create thousands of "
            "addresses at no cost, which is why launderers use throwaway addresses freely."),
          D("Gas", "the fee paid to have a transaction included in a block. It explains why amounts shrink by a fraction of "
            "a percent at each hop, and why Exchequer's rules carry a 2% tolerance."),
          H2("2.2 Two kinds of chain, and why we chose one"),
          D("Account model (Ethereum, BNB Smart Chain, Tron)", "each address has a balance, like a bank account, and a "
            "transfer reduces one balance and increases another. This makes a trace a walk over a graph of addresses."),
          D("UTXO model (Bitcoin)", "there are no balances, only unspent outputs of earlier transactions; a payment "
            "consumes some and creates new ones, including a <i>change</i> output back to the payer. Tracing needs different "
            "logic. Exchequer does not cover Bitcoin yet, and says so; the published evidence points at the account-model "
            "chains for present-day fraud proceeds (section 4)."),
          H2("2.3 Native coins, tokens and stablecoins"),
          D("Native coin", "the chain's own unit: ETH on Ethereum, BNB on BNB Smart Chain, TRX on Tron. Used to pay gas."),
          D("Token", "a unit of value defined by a <i>smart contract</i> deployed on the chain rather than by the chain "
            "itself. On Ethereum and BSC the standard is ERC-20 (BEP-20); on Tron it is TRC-20. A token transfer is recorded "
            "as an event emitted by the token's contract, which is why a token trace reads a different data source from "
            "a coin trace."),
          D("Stablecoin", "a token pegged to a currency, almost always the US dollar. USDT (Tether) and USDC (Circle) are "
            "the two that matter. They are the launderer's preferred asset because their value does not move while the "
            "money is in transit, and because USDT on Tron is cheap and fast to send. Chainalysis measured stablecoins at "
            "84% of illicit cryptocurrency volume in 2025."),
          H2("2.4 Where the money goes: exchanges and their wallets"),
          D("Centralised exchange", "a company (Binance, Coinbase, CoinDCX, WazirX) that holds customers' cryptocurrency "
            "and lets them sell it for rupees or dollars. It is <i>custodial</i>: the exchange controls the keys, and by "
            "law it knows its customers (KYC). This is the point at which cryptocurrency becomes a bank account, and the "
            "only point at which an address becomes a person."),
          D("Hot wallet", "an exchange-controlled address that holds working funds. Block explorers publish the "
            "addresses of the major exchanges' hot wallets under labels such as “Binance 14”. Exchequer's attribution "
            "is an exact match against those published labels."),
          D("Deposit address", "the address an exchange hands to one customer to receive their deposit. The exchange "
            "controls it, but it is unlabelled, and after a while the exchange <i>sweeps</i> the balance into a hot wallet. "
            "A deposit address is the address a legal request must name, because a hot wallet receives from thousands "
            "of customers and identifies nobody. Exchequer infers deposit addresses from their sweep behaviour (section 6.4)."),
          D("Cold wallet", "an exchange's long-term storage, rarely used; labelled the same way."),
          H2("2.5 Things that break the trail"),
          D("Decentralised exchange (DEX) and router", "a smart contract that swaps one token for another with no "
            "company in the middle (Uniswap, PancakeSwap). A trace that follows ETH ends when the ETH is swapped for "
            "USDT, unless the tool reads the transaction's receipt to see what came back. Exchequer does, and reports "
            "where to resume."),
          D("Mixer (tumbler)", "a service that pools many users' deposits and pays out from the pool, so no payout is "
            "linked to any deposit. A trace cannot pass a mixer, and Exchequer stops there by design rather than "
            "manufacture a trail. Tornado Cash is the well-known example on Ethereum."),
          D("Bridge", "a service that moves value to a different blockchain. A bridge to a chain Exchequer does not "
            "cover ends the trace."),
          D("Explorer and its API", "a website (Etherscan, BscScan, TronScan) that indexes the chain so that it can be "
            "queried by address. Their free APIs are the data source for the whole project; their rate limits are the "
            "reason a first trace takes 20–40 seconds."),
          H2("2.6 What “tracing” therefore means"),
          P("Start at the reported address. Read its outgoing transfers. For each recipient, read <i>its</i> outgoing "
            "transfers, but only those made after the victim's money arrived. Stop when a recipient is a labelled exchange "
            "wallet, a sanctioned address, a mixer, or when the depth limit is reached. Along the way, note shapes that "
            "launderers use. At the end, say which exchange, which deposit address, which hashes, what amounts, and how "
            "confident the arithmetic allows one to be. The picture below is a trace of three hops."),
          Sp(4), HopExample(), Sp(4)]

    # ---- 3 ----
    s += [H1("3. How laundering looks on a public ledger"),
          P("Three shapes recur in the literature and in the cases we read. Exchequer detects the first two as fixed rules "
            "and reports the third as a stop."),
          H2("3.1 The peel chain"),
          P("Named by Meiklejohn et al. in <i>A Fistful of Bitcoins</i> (IMC 2013): a large sum sits at one address; a "
            "small amount is peeled off to one destination and the remainder passes to a fresh address, and the process "
            "repeats, so that the funds walk through a series of single-use wallets and shrink at each step. The paper "
            "warns in the same paragraph that the shape “extends well beyond criminal activity” — exchange "
            "withdrawals and mining payouts produce it too. Our validation confirms that warning: the rule fires on "
            "mining-pool payouts."),
          H2("3.2 The amount split (fan-out)"),
          P("One wallet receives a sum and divides it across several recipients, multiplying the paths an investigator "
            "must follow. Elliptic's 2025 typology of pig-butchering proceeds describes funds moved “through dozens of "
            "intermediary wallets” before reaching an exchange where “dozens of money mules” convert them. "
            "This is sometimes called <i>structuring</i>, but that is a legal term (31 CFR § 1010.100(xx)) for splitting "
            "<i>currency</i> transactions to evade a reporting threshold, and there is no reporting threshold on a public "
            "blockchain — so we describe a shape, not an offence. Payroll and exchanges produce the same shape."),
          H2("3.3 The mixer"),
          P("Deposits are pooled, payouts come from the pool. Meiklejohn et al. stop their own tracking at mixers for "
            "this reason. So does Exchequer. The link does not exist in the data and no amount of traversal recovers it."),
          H2("3.4 The shape that matters most: the deposit address"),
          P("Most real cash-outs do not land on a labelled hot wallet. They land on an unlabelled deposit address that the "
            "exchange then sweeps. So a trace usually reaches an unlabelled wallet one hop before the exchange — and "
            "that wallet is the one to name in a lawful request. The tell is its <i>whole</i> history: a deposit address "
            "does one thing, every time, to one place. A personal wallet does other things with its money.")]

    # ---- 4 ----
    s += [H1("4. What the published evidence says, claim by claim"),
          P("On 15 September 2026 we applied to our own README the standard we apply to attributions: every claim the "
            "project makes about laundering was listed, the primary source was fetched and read, the exact passage was "
            "copied, and a verdict was recorded. Where the README said more than the source, the README was rewritten. "
            "This is the summary; the full document is reproduced as the Appendix, with every source linked."),
          table([["Claim", "Source read", "What it says", "Verdict"],
                 ["Most illicit crypto moves as stablecoins", "Chainalysis 2025 and 2026 Crypto Crime Reports; TRM Labs 2026; FATF June 2025 update (via CNP Law summary)",
                  "Stablecoins were 63% of illicit volume in 2024 and 84% in 2025; illicit addresses received at least USD 154 billion in 2025, up 162%, driven mainly by sanctioned entities", "Supported, with scope stated"],
                 ["USDT on Tron is the cash-out rail for Indian scam proceeds", "UNODC 2024 casino and underground-banking report; TRM Labs 2025; Elliptic 2025; ED case coverage (The Week, July 2026)",
                  "UNODC: USDT on Tron is the “preferred choice” of regional cyber-fraud operations. TRM: Tron carried 58% of illicit volume in 2024, halving in 2025. ED froze 160,339 USDT in a Rs. 303 crore case. No source measures India-specific rails", "Partially supported; README softened"],
                 ["Peel chains are a laundering pattern", "Meiklejohn et al., IMC 2013; Elliptic 2025", "Named and described in 2013; still described in 2025. Same paragraph warns it appears in legitimate use. Our thresholds are our own", "Supported, with warning"],
                 ["Amount split is a laundering pattern", "31 CFR § 1010.100(xx); Elliptic 2025", "“Structuring” is a statutory term about currency; on-chain fan-out is a shape analysts describe. Thresholds are our own", "Partially supported; wording changed"],
                 ["Laundering hops that matter are close to the source", "None", "An engineering judgement about where to stop; Meiklejohn followed peel chains for 100 hops", "Not supported; kept as a documented cost limit"],
                 ["A mixer's outputs have no link to its deposits", "Meiklejohn et al. §6", "The paper stops its own tracking at mixers", "Supported"],
                 ["Scale of the problem in India", "MHA answer to Lok Sabha Unstarred Question 432, 2 Dec 2025", "Losses: Rs. 2,290 cr (2022), Rs. 7,465 cr (2023), Rs. 22,845.73 cr (2024); 2.27 million NCRP incidents in 2024", "Supported"],
                 ["Issuers and exchanges freeze scam-linked USDT", "Tether T3 unit, Jan 2025; Hyderabad police coverage, Jan 2025", "USD 100 million frozen globally; Rs. 40 lakh USDT seized in Hyderabad. No Tether announcement names an Indian scam", "Partially supported"],
                 ], [34 * mm, 42 * mm, W - 2 * M - 108 * mm, 32 * mm]),
          Sp(6),
          P("Two primary sources could not be retrieved (the FATF site returned HTTP 403; the Enforcement Directorate's "
            "press pages were unreachable) and are cited through named secondary coverage, labelled as such.", "small")]

    # ---- 5 ----
    s += [H1("5. The Indian legal framework and what it needs from a tool"),
          *B(["<b>The offence and the agency.</b> The Prevention of Money-Laundering Act, 2002 is enforced by the Directorate "
              "of Enforcement on the basis of a predicate offence — in the Rs. 303 crore case, two CBI FIRs. A cyber-fraud "
              "complaint starts at the state police or the National Cyber Crime Reporting Portal and reaches PMLA through an FIR.",
              "<b>Exchanges are reporting entities.</b> Ministry of Finance notification of 7 March 2023: providers of virtual "
              "digital asset services fall under section 2(1)(sa)(vi) of PMLA. FIU-IND's guidelines of 10 March 2023 require "
              "them to register.",
              "<b>What the exchange must hold.</b> PMLA section 12(1): a record of all transactions “in such manner as to "
              "enable it to reconstruct individual transactions” and documents evidencing the identity of clients and "
              "beneficial owners, retained for five years.",
              "<b>How an investigator gets it.</b> PMLA section 50: ED officers may summon any person to produce records. "
              "State police obtain the same by notice under section 94 of the Bharatiya Nagarik Suraksha Sanhita, 2023."]),
          Callout("<b>What this means for the tool.</b> A trace ends at an address. The record that links that address to a "
                  "person exists only at the exchange, under section 12, and is obtained under section 50 or a police notice. "
                  "So every attribution Exchequer prints carries the sentence: <i>an exchange match identifies where funds "
                  "arrived, not who controls the account; only the exchange can link a deposit address to a customer "
                  "identity, via a lawful request.</i> The report's job is to give the officer the address, the hashes, the "
                  "amounts and the times, in a form the compliance team can match. That is why the report lists every hash.")]

    # ---- 6 ----
    s += [H1("6. What we built: the pipeline, stage by stage"),
          P("Exchequer is a FastAPI backend (Python) and a React frontend, about 9,700 lines of application code, with "
            "234 automated tests and continuous integration. One request to <font face='Courier'>POST /trace</font> "
            "runs the seven stages below and stores the result as a case."),
          Sp(4), Pipeline(), Sp(6),
          H2("6.1 Data: three chains, three providers"),
          P("Ethereum through Etherscan, BNB Smart Chain through NodeReal, Tron through TronGrid, all on free keys. "
            "<font face='Courier'>chain_data.py</font> is the only module that knows where data comes from. Each provider "
            "is rate-limit aware; we measured Etherscan's free tier and found the documented 5 requests/second is not what "
            "is granted — at 0.5 s spacing 4% of requests are refused, at 0.2 s spacing 67% are — so the pacer "
            "defaults to the measured optimum. Tron and BSC pagination is bounded by records <i>read</i> (1,000), not "
            "records kept, after a busy Tron wallet paged its whole history for minutes on the hosted demo."),
          H2("6.2 The walk, and the time rule"),
          P("A breadth-first walk to a default depth of 4 hops, following the 10 highest-value counterparties of each "
            "address and dropping dust, in either direction. Its one rule about <i>when</i>: money cannot be forwarded "
            "before it arrives. When the trace reaches a wallet it knows when the traced funds landed, and follows only "
            "transfers made at or after that moment. Without this, a busy wallet that once received the victim's funds "
            "would have its entire earlier history reported as where the money went. Every node reports how many "
            "transfers the rule excluded, so the effect is visible rather than silent. An optional time budget "
            "(10–600 s) stops a long trace and reports which addresses were left unexpanded."),
          H2("6.3 Attribution: exact match, verified labels"),
          P("Labels are per chain and never shared between chains. 337 Ethereum wallets across 18 exchanges, 30 BSC "
            "wallets across 9 (including CoinDCX), 40 Tron wallets across 18 — 407 in total. Ethereum and BSC are "
            "imported from a public dataset pinned to one commit; Tron labels are read live from TronScan's own API. "
            "Nothing is accepted on the label alone: every address must show no contract bytecode and at least one "
            "received transfer on the live chain before it enters the file. Four mislabelled contracts were rejected by "
            "that check. WazirX and ZebPay are absent because no source met the standard."),
          H2("6.4 Deposit-address inference"),
          P("An unlabelled wallet is a <i>probable deposit address of exchange E</i> when it is not the reported address, "
            "has made at least two outgoing transfers, and every one of them went to the same labelled E wallet and "
            "nowhere else. It is scored as a weaker attribution (match directness 0.5 instead of 1.0), the response says "
            "<font face='Courier'>attribution_inferred: true</font>, and the report prints the evidence and the sentence "
            "that would confirm it. It fired on 0 of 48 control wallets."),
          H2("6.5 Screening"),
          P("Every address is checked against the US Treasury's SDN list, generated straight from Treasury's XML with "
            "the sanctions programme kept on each entry: 124 Ethereum, 282 Tron and 1 BSC address as of 4 September 2026. "
            "A trace stops at a mixer. The designation carries no automatic force in Indian law; it is an escalation trigger."),
          H2("6.6 Patterns and swaps"),
          P("Peel chain: runs of at least 2 single-use intermediates, amounts never growing (2% tolerance), ending lower "
            "than they started, each hop forwarding at least 50%. Amount split: 4 or more recipients, 90–102% of the "
            "inflow passed through, no recipient above 60%, and the address is not itself an exchange. Every finding "
            "prints the thresholds it applied. A pattern <b>never moves the score</b>; it is a caveat beside it. When a "
            "transfer's recipient is a labelled DEX router, the transaction receipt is read and the swap's output asset "
            "and amount are reported with where to re-run; the trace is not resumed on the output asset, because amount "
            "correlation across 1 ETH and 2,400 USDT has no defensible definition yet."),
          H2("6.7 The score"),
          table([["Component", "Weight", "What it measures"],
                 ["Hop proximity", "40%", "Fewer hops, less room for the trail to be broken by a wallet we cannot see. Linear from 1.0 at a direct deposit."],
                 ["Amount correlation", "35%", "How much of the value that left the reported address arrived. Capped at 100%; both figures are printed so dilution is visible."],
                 ["Match directness", "25%", "1.0 for a labelled wallet, 0.5 for an inferred deposit address."],
                 ], [34 * mm, 18 * mm, W - 2 * M - 52 * mm]),
          Sp(4),
          P("No attribution scores <i>null</i>, never a low number that might be over-read. There is no model and no "
            "clustering, because a conclusion that reaches a courtroom has to be one an officer can re-check by hand."),
          H2("6.8 Cross-case correlation"),
          P("Every trace is stored with its full graph, so finding intermediaries shared by traces from <i>different</i> "
            "complaints is a query, not new tracing. Exchange hot wallets are excluded on purpose (two victims whose money "
            "ended at Binance share a bank, not an offender). On 15 September three wallets carrying Etherscan's "
            "Phish/Hack label were found to share 61 intermediaries, four of them inferred Binance deposit addresses — "
            "the shape of one operation run from several wallets, which three separate complaints would never show."),
          H2("6.9 Evidence integrity"),
          P("Every provider response is SHA-256 hashed as it arrives, with the request that produced it (credential "
            "removed, parameters in fixed order) and the UTC time, and stored with the case as a manifest. One hash over "
            "the sorted records is the manifest hash. The text report prints the manifest as an appendix and ends with a "
            "content hash over every byte above it, so the document that leaves the tool can be checked against the "
            "document that reaches a court. Cached responses are marked as such with their original retrieval time."),
          H2("6.10 Interface and hosting"),
          P("The case view is one finding bar, a hop-layered flow diagram (traced funds in red, zoom and pan), a feed of "
            "the transfers that matter, and a folded evidence rail; a bubble graph sits behind a toggle. A present mode "
            "turns a case into four projector screens. A demo sign-in (admin / admin, front-end only, not access control) "
            "sits over a live ledger drawn from the stored cases. Reports export as sealed text and JSON. The backend is a "
            "Docker image on Railway with a persistent volume; at boot it traces the demo addresses into a disk cache, "
            "so the flagship case answers in 0.12 s instead of 43 s.")]

    # ---- 7 ----
    s += [H1("7. How we know it behaves: validation on real wallets"),
          P("A threshold that was chosen rather than derived has to be shown to behave. We built two corpora, every "
            "address fetched by script from a named source and checked on chain for contract bytecode, with provenance "
            "recorded per entry:"),
          *B(["<b>40 positives</b> — wallets publicly documented as fraud or theft proceeds: 20 from the OFAC SDN list "
              "(Lazarus Group and others), 17 carrying Etherscan's own Phish/Hack label, and the 3 WazirX-hack attacker "
              "addresses named by CloudSEK.",
              "<b>48 controls</b> — ordinary wallets with no fraud association from the same pinned dataset the exchange "
              "importer uses: funds, mining pools, charities, payment processors, OTC desks, treasuries, airdrop distributors. "
              "The pools, processors and distributors are there on purpose: they fan out by design."]),
          P("Each wallet was traced forward at depth 3 with the real pipeline (1,416 provider requests; 37 addresses per "
            "trace on average). 32 positives and 47 controls had at least one outgoing transfer; a rule counts as fired if "
            "it produced a finding anywhere in the graph."),
          table([["Rule", "Thresholds", "Fired on positives (of 32)", "Fired on controls (of 47)"],
                 ["Peel chain", "3 transfers, 2 intermediates, 50% retention (defaults)", "2", "2"],
                 ["Peel chain", "3 intermediates", "0", "0"],
                 ["Amount split", "previous defaults: 3 recipients, 50–110%, 90% cap", "12", "19"],
                 ["Amount split", "current defaults: 4 recipients, 90–102%, 60% cap", "6", "5"],
                 ["Amount split", "5 recipients, 90–102%, 60% cap", "3", "5"],
                 ["Deposit-address inference", "2 sweeps, 100% to one labelled wallet", "—", "0 of 48 seeds"],
                 ], [36 * mm, 60 * mm, 37 * mm, W - 2 * M - 133 * mm]),
          Sp(6),
          P("What the numbers establish, and what they do not. <b>Neither rule separates documented-illicit wallets from "
            "ordinary high-volume ones within three hops</b>, and no point in the 68-point threshold grid brought control "
            "firings to zero while still firing on any positive. The amount split at its old defaults flagged 40% of "
            "ordinary wallets, which is unusable in a report that names people, so the defaults moved to the grid point "
            "with the fewest control firings that still fired on positives — 11% of controls, 19% of positives — an "
            "estimate from 79 wallets, not a law. The design already assumed this: a pattern is a reason to look closer, "
            "and it never moves the score. What the tool establishes with confidence is different and narrower: that "
            "funds reached a wallet published in an exchange label file. 19 of the 32 illicit wallets reached one within "
            "three hops; so did 35 of the 47 ordinary ones, because almost everyone's money passes through an exchange. "
            "The fraud is established by the complaint; the tool establishes where the money went."),
          P("Only Ethereum was measured. No scripted source of Tron controls with the same provenance discipline was "
            "found, so no number is claimed for the other chains. The table regenerates offline from the committed "
            "snapshot with one command.", "small")]

    # ---- 8 ----
    s += [H1("8. What it does not do, stated plainly"),
          P("Every limitation below is also printed in every exported report."),
          *B(["<b>One asset per trace.</b> A swap is detected and reported, not followed; a swap into the native coin, a swap "
              "through a liquidity pool, or a bridge to an uncovered chain ends the trail.",
              "<b>The graph is a sample.</b> Only the 10 highest-value counterparties of each address are followed, so a "
              "launderer who sends the real money as the eleventh-largest transfer defeats the walk. Raising the limit costs "
              "geometrically more requests; it does not remove the gap.",
              "<b>Only the newest 200 transfers of each address are read.</b> On a busy wallet the relevant one may lie beyond.",
              "<b>The reported address is not time-windowed</b>, because the trace does not know when the victim's funds "
              "arrived there. Every later hop is.",
              "<b>Internal (contract-moved) value is read on Ethereum only</b>, at double the request cost, and only for "
              "contract-shaped addresses on a forward trace. On BSC, Tron and every token trace it is invisible.",
              "<b>BSC covers a recent window</b> (about 17 days by default) because NodeReal caps a query at 100,000 blocks.",
              "<b>Attribution is only as good as the label file.</b> A null result may mean the exchange is absent from it.",
              "<b>A trace stops at a mixer and cannot resume.</b> The link does not exist in the data.",
              "<b>Screening covers the OFAC list only</b>; absence from it establishes nothing.",
              "<b>A first-time trace is as fast as the free tier allows</b>: 20–40 s cold, well under a second cached."]),
          Callout("The one thing an evidentiary tool must not do is report money that was never the victim's, and we found "
                  "ours could — by following transfers made before the funds arrived. That is fixed, tested and written down. "
                  "We publish the ways a launderer can defeat the tool because its value is in what it <i>can</i> establish "
                  "cheaply and reproducibly, and an investigator has to know where its edge is.", RED)]

    # ---- 9 ----
    s += [H1("9. Timeline of the work"),
          table([["Date (2026)", "What landed"],
                 ["3–5 Sep", "Project started as TraceChain: tracing across Ethereum, BSC and Tron; Etherscan pacing measured; first hosted deployment on Railway."],
                 ["7 Sep", "Test suite for attribution and detection rules; reverse tracing; sanctions and mixer screening from the live OFAC list (407 addresses); two verified reverse-trace demos; internal-round presentation."],
                 ["15 Sep", "Adaptive request pacer and response cache; the time rule; every laundering claim sourced and the README softened where sources said less; deposit-address inference; validation on 88 real wallets and the amount-split thresholds tightened; judge Q&A; internal transactions and the service-contract brake; swap detection at DEX routers; cross-case correlation; evidence manifest and content hash; UI direction set (light case-file look)."],
                 ["16 Sep", "Renamed Exchequer (a rival team ships as TraceChain); officer sign-in built and then removed at the team's decision (chain of custody rests on evidence hashing instead); persistent cache and warm-up at boot; Railway seed script; GitHub Actions CI."],
                 ["17 Sep", "Optional time budget; hop-layered flow view with zoom, pan and the traced-funds animation; the chequer mark; demo sign-in over the live ledger; present mode; scout script and the procedure for a judge to pick a live address."],
                 ["18 Sep", "Tron and BSC pagination bounded by records read after a busy Tron wallet paged for minutes on the hosted demo; tests for both. 234 tests green; main at 4409aea."],
                 ], [26 * mm, W - 2 * M - 26 * mm]),
          Sp(4),
          P("65 commits by one author. The internal round used the same judges the next round will.", "small")]

    # ---- 10 ----
    s += [H1("10. What comes next"),
          *B(["<b>Before the next round:</b> no new heuristic rules. Rehearse the four cases (sanctions hit; an attribution the "
              "time rule removed, which is the honesty argument; an inferred deposit; three complaints converging). Bring the "
              "hosted instance up two days before.",
              "<b>Paid tiers:</b> Etherscan Lite (USD 49/month) unlocks Polygon, Arbitrum, Optimism, Base and Avalanche through "
              "code already present; Tron and BSC tiers remove the per-second ceiling.",
              "<b>PDF report:</b> the text report already carries everything; this is a renderer.",
              "<b>Bitcoin:</b> a different model (UTXO); its own adapter.",
              "<b>Cross-asset following:</b> needs a defensible definition of amount correlation across two assets.",
              "<b>Engineering debt:</b> block windowing in the Ethereum client so the 200-newest cap cannot hide a followed "
              "transfer; a concurrency guard on <font face='Courier'>/trace</font>; Postgres; frontend tests; streamed progress.",
              "<b>A pilot with a cyber-crime cell</b>, which is the only test that matters."]),
          H2("Against the field"),
          P("A rival SIH26183 submission we studied has more tests (506), PDF export, a Postgres/Redis worker and six pattern "
            "rules — and 17 exchange labels, all Binance on Tron. We have 407 labels across 18 exchanges and three chains, "
            "the time rule, cross-case correlation, swap detection, evidence hashing and published failure rates. We would "
            "rather be right about less than confident about more.")]

    # ---- 11 ----
    s += [H1("11. References"),
          P("All read on 15 September 2026 unless stated; full passages in RESEARCH.md.", "small"),
          *N(["Chainalysis, <i>2026 Crypto Crime Report — Introduction</i>, 8 January 2026; and <i>2025 Crypto Crime Trends</i>, 15 January 2025.",
              "TRM Labs, <i>2026 Crypto Crime Report — Key Insights</i>, 10 January 2026; and <i>2025 Crypto Crime Report</i>, p. 6.",
              "UNODC, <i>Casinos, Money Laundering, Underground Banking, and Transnational Organized Crime in East and Southeast Asia</i>, January 2024, pp. 20, 65.",
              "Elliptic, <i>Typologies Report: Detecting the money flows behind the global pig butchering ecosystem</i>, 16 October 2025.",
              "S. Meiklejohn et al., <i>A Fistful of Bitcoins: Characterizing Payments Among Men with No Names</i>, IMC 2013, §5.2 and §6.",
              "31 CFR § 1010.100(xx), definition of structuring (Cornell LII).",
              "Ministry of Home Affairs, answer to Lok Sabha Unstarred Question No. 432, 2 December 2025.",
              "The Week, <i>ED uncovers Rs. 303-crore transnational cyber fraud syndicate</i>, 13 July 2026.",
              "Tether, <i>T3 Financial Crime Unit … $100 Million in Criminal Assets Frozen</i>, 2 January 2025; The Crypto Times, <i>India Police Seize Rs. 40L in Tether</i>, 30 January 2025.",
              "Prevention of Money-Laundering Act, 2002, sections 12 and 50; Ministry of Finance notification of 7 March 2023; FIU-IND <i>AML &amp; CFT Guidelines for Reporting Entities Providing Services Related to Virtual Digital Assets</i>, 10 March 2023, §5.1; AZB &amp; Partners and Oxford Business Law Blog commentaries (July 2023).",
              "CNP Law, <i>FATF Identifies Stablecoins as a Major Risk</i>, 11 August 2025 (secondary; FATF site returned HTTP 403).",
              "CloudSEK, write-up of the WazirX hack, 19 July 2024 (source of three attacker addresses in the validation corpus)."]),
          PageBreak(),
          H1("Appendix. RESEARCH.md, in full"),
          P("What follows is the project's research file exactly as it stands in the repository on 19 September 2026, "
            "converted from Markdown with nothing added or removed. It lists every claim the README makes about laundering, "
            "the primary source that was fetched and read for it, the exact passage copied from that document, and a "
            "verdict. Where the README said more than the source supports, the README was changed. Every address below is "
            "a live link.", "lead"),
          *research_appendix(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "RESEARCH.md")),
          Sp(40),
          Colophon("Exchequer is named for the medieval treasury that counted the Crown's money on a chequered cloth. "
                   "One square of the mark is red: the sum being traced.")]
    return s

if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    numbers = [("3", "blockchains traced"), ("407", "verified exchange wallets"), ("234", "automated tests"), ("88", "real wallets measured")]
    build(os.path.join(here, "Exchequer-Proposal.pdf"), proposal(), "Proposal for institutional support",
          (["Exchequer"],
           "A proposal for institutional support: tracing cryptocurrency fraud from a victim\u2019s wallet to the exchange that cashed it out",
           [("Submitted by", "Sidhyarth, B.Tech, Alliance University  (SIH entry: WiFiBandits)"),
            ("Request", "Running costs, a faculty mentor, and a letter of introduction to a police cyber-crime cell"),
            ("Status", "Working software, hosted, tested, with a published validation study")],
           numbers))
    build(os.path.join(here, "Exchequer-Research-Report.pdf"), report(), "Research foundations and work to date",
          (["Exchequer"],
           "Research foundations and work to date: the cryptocurrency concepts, the published evidence, and what has been built",
           [("Prepared by", "Sidhyarth, B.Tech, Alliance University  (SIH entry: WiFiBandits)"),
            ("Companion to", "The proposal for institutional support of the same date"),
            ("Sources", "Every figure is from a document read and quoted in the project\u2019s RESEARCH.md")],
           numbers))
    print("done")
