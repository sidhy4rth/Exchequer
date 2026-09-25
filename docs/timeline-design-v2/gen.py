"""Generates the nine A4 pages of the Exchequer project timeline canvas."""
import json, math, pathlib, datetime

OUT = pathlib.Path(__file__).parent
W, H = 794, 1123
INK, PAPER, PANEL, RULE = "#16191d", "#f4f2ec", "#ffffff", "#d6d2c8"
MUTED, RED, GREEN, AMBER, NAVY = "#545a61", "#c8322a", "#1d7a4c", "#8a5200", "#1f3a5f"
SERIF = "'IBM Plex Serif', Georgia, serif"
SANS = "'IBM Plex Sans', 'Helvetica Neue', sans-serif"
MONO = "'IBM Plex Mono', Menlo, monospace"
TOTAL = 9


def mark(size, ink=INK, red=RED, x=0, y=0):
    c = size / 4
    sq = []
    for r in range(4):
        for col in range(4):
            if (r + col) % 2 == 0:
                fill = red if (r, col) == (2, 2) else ink
                sq.append(f'<rect x="{x+col*c:.1f}" y="{y+r*c:.1f}" width="{c:.1f}" height="{c:.1f}" fill="{fill}"></rect>')
    return "".join(sq)


def mark_svg(size, ink=INK, red=RED):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" aria-hidden="true">'
            f'<clipPath id="mk{size}"><rect width="{size}" height="{size}" rx="{size*0.14:.1f}"></rect></clipPath>'
            f'<g clip-path="url(#mk{size})">{mark(size, ink, red)}</g></svg>')


def head(n, section):
    return f'''<div style="display: flex; align-items: center; justify-content: space-between; height: 22px; border-bottom: 1px solid {RULE}; padding-bottom: 10px;">
<div style="display: flex; align-items: center; gap: 10px;">{mark_svg(18)}<span style="font-family: {SANS}; font-size: 11px; font-weight: 600; letter-spacing: 2px; color: {INK};">EXCHEQUER · PROJECT TIMELINE</span></div>
<span style="font-family: {SANS}; font-size: 11px; letter-spacing: 1.5px; color: {MUTED};">{section} · {n:02d} / {TOTAL:02d}</span>
</div>'''


def foot():
    return f'''<div style="display: flex; justify-content: space-between; border-top: 1px solid {RULE}; padding-top: 10px; font-family: {SANS}; font-size: 10.5px; color: {MUTED}; letter-spacing: 0.5px;">
<span>Smart India Hackathon 2026 · SIH26183 · Ministry of Home Affairs · Team WiFiBandits</span><span>Sources: git history (91 commits), project notes and deliverables</span>
</div>'''


def page(n, title, section, body, bg=PAPER):
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&amp;family=IBM+Plex+Sans:wght@400;500;600&amp;family=IBM+Plex+Serif:wght@500;600&amp;display=swap">
<style>
body{{margin:0;background:{bg};font-family:{SANS};color:{INK}}}
a{{color:{NAVY}}}a:hover{{color:{INK}}}
</style>
</helmet>
<div style="width: {W}px; height: {H}px; box-sizing: border-box; padding: 44px 52px 40px; background: {bg}; display: flex; flex-direction: column; gap: 0px; overflow: hidden;">
{head(n, section) if n > 1 else ""}
<div style="flex-grow: 1; display: flex; flex-direction: column; gap: 18px; padding-top: {22 if n > 1 else 0}px; min-height: 0px;">
{body}
</div>
{foot()}
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{{"$preview":{{"width":{W},"height":{H}}}}}'>
class Component extends DCLogic {{
renderVals() {{ return {{}}; }}
}}
</script>
</body>
</html>
'''


def h1(text, kicker):
    return f'''<div style="display: flex; flex-direction: column; gap: 6px;">
<span style="font-family: {SANS}; font-size: 11px; font-weight: 600; letter-spacing: 2px; color: {RED};">{kicker}</span>
<h1 style="margin: 0; font-family: {SERIF}; font-size: 34px; font-weight: 600; line-height: 1.12; color: {INK}; text-wrap: balance;">{text}</h1>
</div>'''


def para(text, size=13.5, color=INK, w=None):
    ws = f" max-width: {w}px;" if w else ""
    return f'<p style="margin: 0; font-size: {size}px; line-height: 1.55; color: {color};{ws} text-wrap: pretty;">{text}</p>'


def label(text, color=MUTED):
    return f'<span style="font-family: {SANS}; font-size: 10.5px; font-weight: 600; letter-spacing: 1.6px; color: {color};">{text}</span>'


def card(inner, pad=16, bg=PANEL, border=RULE, extra=""):
    return f'<div style="background: {bg}; border: 1px solid {border}; border-radius: 6px; padding: {pad}px; display: flex; flex-direction: column; gap: 8px; box-sizing: border-box;{extra}">{inner}</div>'


def tag(text, color):
    return f'<span style="display: inline-block; font-family: {MONO}; font-size: 10px; color: {color}; border: 1px solid {color}; border-radius: 3px; padding: 1px 6px; letter-spacing: 0.3px;">{text}</span>'


# ---------------------------------------------------------------- page 1: cover
def p1():
    days = [(d, c) for d, c in [(4, 0), (5, 1), (7, 9), (15, 25), (16, 23), (17, 7), (23, 26)]]
    x0, x1 = 20, 670
    span = lambda d: x0 + (d - 4) / 20 * (x1 - x0)
    ticks = "".join(f'<line x1="{span(d):.1f}" y1="52" x2="{span(d):.1f}" y2="58" stroke="{MUTED}" stroke-width="1"></line>' for d in range(4, 25))
    dots = ""
    for d, c in days:
        r = 4 + math.sqrt(c) * 2.6
        fill = RED if d == 23 else INK
        dots += f'<circle cx="{span(d):.1f}" cy="55" r="{r:.1f}" fill="{fill}"></circle>'
        if c:
            dots += f'<text x="{span(d):.1f}" y="{55 - r - 7:.1f}" text-anchor="middle" font-family="{MONO}" font-size="10" fill="{MUTED}">{c}</text>'
    labels = "".join(f'<text x="{span(d):.1f}" y="82" text-anchor="middle" font-family="{SANS}" font-size="10.5" fill="{INK}">{d}</text>' for d in (4, 5, 7, 15, 16, 17, 20, 23, 24))
    strip = (f'<svg width="690" height="96" viewBox="0 0 690 96" role="img" aria-label="Commits per day, 4 to 23 September">'
             f'<line x1="{x0}" y1="55" x2="{x1}" y2="55" stroke="{INK}" stroke-width="1.5"></line>{ticks}{dots}{labels}</svg>')
    stat = lambda n, t: f'<div style="display: flex; flex-direction: column; gap: 4px;"><span style="font-family: {SERIF}; font-size: 40px; font-weight: 600; color: {INK}; line-height: 1;">{n}</span><span style="font-size: 12px; color: {MUTED};">{t}</span></div>'
    body = f'''
<div style="display: flex; justify-content: space-between; align-items: center;">
{label("SMART INDIA HACKATHON 2026 · SIH26183", INK)}{label("MINISTRY OF HOME AFFAIRS")}
</div>
<div style="height: 1px; background: {INK};"></div>
<div style="display: flex; flex-direction: column; gap: 26px; padding-top: 70px;">
{mark_svg(176)}
<div style="display: flex; flex-direction: column; gap: 12px;">
<h1 style="margin: 0; font-family: {SERIF}; font-size: 84px; font-weight: 600; line-height: 1; letter-spacing: -1px; color: {INK};">Exchequer</h1>
<p style="margin: 0; font-family: {SERIF}; font-size: 26px; line-height: 1.3; color: {INK}; max-width: 600px;">From idea to execution — the project timeline</p>
<p style="margin: 0; font-size: 14px; line-height: 1.55; color: {MUTED}; max-width: 560px;">How a one-page idea for tracing crypto fraud became a tool that follows a victim's money across five blockchains, screens it against six governments' lists, estimates how much of it reached the exchange, and drafts the letter an officer sends.</p>
</div>
</div>
<div style="flex-grow: 1;"></div>
<div style="display: flex; flex-direction: column; gap: 6px;">
{label("COMMITS PER DAY · 4 → 23 SEPTEMBER 2026")}
{strip}
</div>
<div style="display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; border-top: 1px solid {INK}; padding-top: 20px; padding-bottom: 18px;">
{stat("20", "days, idea to today")}{stat("91", "commits")}{stat("45,003", "labelled addresses")}{stat("311", "tests, no network")}
</div>'''
    return page(1, "Exchequer — project timeline", "COVER", body)


# ---------------------------------------------------------------- page 2: numbers
def p2():
    # log bar chart of labelled addresses
    pts = [("4 Sep", "one-pager", 337), ("5 Sep", "first commit", 374), ("15 Sep", "research", 838), ("18 Sep", "pre-round", 838), ("23 Sep", "now", 45003)]
    cw, ch, base, top = 330, 210, 180, 20
    lo, hi = math.log10(100), math.log10(100000)
    bars = ""
    bw = 44
    for i, (d, s, v) in enumerate(pts):
        x = 30 + i * 62
        h = (math.log10(v) - lo) / (hi - lo) * (base - top)
        fill = RED if i == 4 else INK
        bars += f'<rect x="{x}" y="{base - h:.1f}" width="{bw}" height="{h:.1f}" fill="{fill}"></rect>'
        bars += f'<text x="{x + bw/2}" y="{base - h - 6:.1f}" text-anchor="middle" font-family="{MONO}" font-size="10.5" fill="{INK}">{v:,}</text>'
        bars += f'<text x="{x + bw/2}" y="{base + 14}" text-anchor="middle" font-family="{SANS}" font-size="10" fill="{INK}">{d}</text>'
        bars += f'<text x="{x + bw/2}" y="{base + 26}" text-anchor="middle" font-family="{SANS}" font-size="9.5" fill="{MUTED}">{s}</text>'
    grid = "".join(f'<line x1="24" y1="{base - (math.log10(g) - lo)/(hi-lo)*(base-top):.1f}" x2="{cw}" y2="{base - (math.log10(g) - lo)/(hi-lo)*(base-top):.1f}" stroke="{RULE}" stroke-width="1"></line><text x="20" y="{base - (math.log10(g) - lo)/(hi-lo)*(base-top) + 3:.1f}" text-anchor="end" font-family="{MONO}" font-size="9" fill="{MUTED}">{g:,}</text>' for g in (100, 1000, 10000, 100000))
    chart1 = f'<svg style="display: block; width: 100%; height: auto;" viewBox="-26 0 {cw + 26} {ch}" role="img" aria-label="Labelled addresses over time, log scale">{grid}{bars}</svg>'

    # tests line
    tp = [("5 Sep", 0), ("15 Sep", 140), ("15 Sep+", 172), ("18 Sep", 234), ("23 am", 273), ("23 pm", 311)]
    lx = lambda i: 30 + i * 56
    ly = lambda v: 170 - v / 340 * 140
    path = " ".join(f'{"M" if i == 0 else "L"}{lx(i)},{ly(v):.1f}' for i, (_, v) in enumerate(tp))
    tdots = "".join(f'<circle cx="{lx(i)}" cy="{ly(v):.1f}" r="4" fill="{RED if i == 5 else INK}"></circle><text x="{lx(i)}" y="{ly(v) - 9:.1f}" text-anchor="middle" font-family="{MONO}" font-size="10.5" fill="{INK}">{v}</text>' for i, (_, v) in enumerate(tp))
    tlab = "".join(f'<text x="{lx(i)}" y="190" text-anchor="middle" font-family="{SANS}" font-size="10" fill="{INK}">{d.replace("+", "")}</text>' for i, (d, _) in enumerate(tp))
    chart2 = f'<svg style="display: block; width: 100%; height: auto;" viewBox="0 0 330 {ch}" role="img" aria-label="Tests over time"><line x1="20" y1="170" x2="320" y2="170" stroke="{RULE}"></line><path d="{path}" fill="none" stroke="{INK}" stroke-width="2"></path>{tdots}{tlab}</svg>'

    def stat(n, t, sub, color=INK):
        return card(f'<span style="font-family: {SERIF}; font-size: 30px; font-weight: 600; color: {color}; line-height: 1;">{n}</span><span style="font-size: 12.5px; font-weight: 600; color: {INK};">{t}</span><span style="font-size: 11.5px; color: {MUTED}; line-height: 1.45;">{sub}</span>', pad=14)
    rows = [("Name", "TraceChain", "TraceChain", "TraceChain", "Exchequer", "Exchequer"),
            ("Chains traced", "1", "3", "3", "3", "5"),
            ("Exchange addresses", "337", "374", "407", "407", "25,508"),
            ("Sanctioned screened", "0", "0", "407", "407", "1,085"),
            ("Frozen · mixer · theft", "0", "0", "0", "0", "18,386"),
            ("Tests", "—", "0", "172", "234", "311")]
    th = "".join(f'<div style="font-family: {SANS}; font-size: 10.5px; font-weight: 600; color: {MUTED}; padding: 6px 8px; text-align: {"left" if i == 0 else "right"}; border-bottom: 1px solid {INK};">{h}</div>' for i, h in enumerate(["", "4 Sep", "5 Sep", "15 Sep", "18 Sep", "23 Sep"]))
    tb = ""
    for r in rows:
        for i, c in enumerate(r):
            bold = "font-weight: 600; color: " + RED + ";" if i == 5 else ""
            tb += f'<div style="font-family: {MONO if i else SANS}; font-size: 11.5px; padding: 6px 8px; text-align: {"left" if i == 0 else "right"}; border-bottom: 1px solid {RULE}; {bold}">{c}</div>'
    table = f'<div style="display: grid; grid-template-columns: 1.6fr repeat(5, minmax(0, 1fr)); background: {PANEL}; border: 1px solid {RULE}; border-radius: 6px; padding: 4px 8px 6px;">{th}{tb}</div>'
    body = f'''{h1("The project in numbers", "AT A GLANCE")}
<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px;">
{card(label("LABELLED ADDRESSES · LOG SCALE") + chart1, pad=14)}
{card(label("TESTS IN THE SUITE") + chart2, pad=14)}
</div>
<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px;">
{stat("25,508", "exchange addresses", "On five chains, incl. CoinDCX and Delta Exchange; 24,018 are Bitget and Binance customer deposit addresses", RED)}
{stat("1,085", "sanctioned addresses", "Six governments: US, UK, EU, Israel, Japan, France. Lifted measures excluded.")}
{stat("9,392", "frozen by Tether", "Read from the USDT contracts’ own blacklist events on Ethereum and Tron.")}
{stat("8,940", "hack and scam wallets", "WazirX, Bybit, BingX, Ronin exploiters; ScamSniffer and Etherscan phishing reports.")}
{stat("54", "mixer pools", "Tornado Cash, Typhoon, Privacy Pools. The trace stops here, by rule.")}
{stat("12", "verified demo traces", "Re-run against the live site every morning; a drift fails CI.")}
</div>
{table}'''
    return page(2, "The project in numbers", "NUMBERS", body)


# ---------------------------------------------------------------- page 3: arc
def p3():
    phases = [
        ("≤ 4 SEP", "0", "The idea", "SIH26183. The stance: no model, no clustering, no proprietary score. The TraceChain one-pager: Ethereum only, 337 wallets, first trace to Binance 14.", INK),
        ("5–7 SEP", "1", "The foundation", "Three chains from day one. Tests written two-sided. Reverse tracing. 407 OFAC addresses screened; the trace stops at a mixer.", INK),
        ("7–15 SEP", "2", "The judging round", "“Have you done any research to support your claims?” The honest answer was no — and it set the next agenda.", AMBER),
        ("15 SEP", "3", "Research and correctness", "25 commits. The time-rule bug fixed. RESEARCH.md. Rules measured on 88 real wallets. Deposit inference, swaps, evidence hashing.", INK),
        ("16 SEP", "4", "Becoming Exchequer", "Renamed. Hosted on Railway. CI on every push. Demos cached at startup: 43 s cold → 0.12 s.", INK),
        ("17 SEP", "5", "The mark and the room", "The chequer mark. A sign-in page over the real ledger. Present mode for the projector.", INK),
        ("18–20 SEP", "6", "Documents and the film", "Director proposal and Research Report PDFs. The launch film, three cuts, 43.2 s.", INK),
        ("22–23 SEP", "7", "407 → 44,588 labels", "Six governments, Tether freezes, mixers, 8,940 scam wallets, 24,018 deposit addresses, swaps followed, request letters.", INK),
        ("23 SEP · AM", "8", "Bug hunt", "Every endpoint, every page. A false Tether-freeze finding on burns, fixed; the time budget made to hold.", INK),
        ("23 SEP · PM", "9", "Wider, and honest about amounts", "Five chains. TronScan tags and warnings read live. A BSC wallet that found nothing, fixed. Pro-rata amounts. Demos checked every morning.", RED),
    ]
    rows = ""
    for i, (d, n, t, s, c) in enumerate(phases):
        last = i == len(phases) - 1
        line = "" if last else f'<div style="position: absolute; left: 13px; top: 30px; width: 2px; height: 64px; background: {RULE};"></div>'
        rows += f'''<div style="display: flex; gap: 16px; align-items: flex-start; height: 84px;">
<span style="width: 78px; flex-shrink: 0; padding-top: 6px; font-family: {MONO}; font-size: 11px; color: {MUTED}; text-align: right;">{d}</span>
<div style="position: relative; width: 28px; flex-shrink: 0; height: 84px;">{line}<div style="width: 28px; height: 28px; border-radius: 4px; background: {c}; color: {PAPER}; font-family: {MONO}; font-size: 13px; font-weight: 500; display: flex; align-items: center; justify-content: center;">{n}</div></div>
<div style="display: flex; flex-direction: column; gap: 4px; padding-top: 3px; flex-grow: 1;">
<span style="font-family: {SERIF}; font-size: 18px; font-weight: 600; color: {INK};">{t}</span>
<span style="font-size: 12.5px; line-height: 1.5; color: {MUTED}; max-width: 520px;">{s}</span>
</div>
</div>'''
    body = f'''{h1("The arc, in ten phases", "OVERVIEW")}
<div style="display: flex; flex-direction: column; gap: 0px; padding-top: 6px;">{rows}</div>'''
    return page(3, "The arc in ten phases", "OVERVIEW", body)


# ---------------------------------------------------------------- page 4: phases 0-2
def p4():
    steps = ["Fetch", "Traverse", "Attribute", "Detect", "Score", "Report"]
    subs = ["Etherscan V2, rate-limit aware", "BFS, 4 hops, highest value first", "exact match, published list", "peel chain · amount split", "40% hops · 35% amount · 25% match", "stored case, JSON + text"]
    pipe = ""
    for i, (s, sub) in enumerate(zip(steps, subs)):
        x = i * 116
        fill = RED if s == "Attribute" else INK
        pipe += f'<rect x="{x}" y="0" width="104" height="40" rx="4" fill="{fill}"></rect><text x="{x+52}" y="25" text-anchor="middle" font-family="{SANS}" font-size="13" font-weight="600" fill="{PAPER}">{s}</text>'
        pipe += f'<foreignObject x="{x}" y="46" width="104" height="44"><div xmlns="http://www.w3.org/1999/xhtml" style="font-family: {SANS}; font-size: 10.5px; line-height: 1.35; color: {MUTED}; text-align: center;">{sub}</div></foreignObject>' if False else ""
        pipe += "".join(f'<text x="{x+52}" y="{58 + j*13}" text-anchor="middle" font-family="{SANS}" font-size="10" fill="{MUTED}">{part}</text>' for j, part in enumerate(_wrap(sub, 20)))
        if i < 5:
            pipe += f'<path d="M{x+106},20 L{x+114},20" stroke="{INK}" stroke-width="1.5"></path><path d="M{x+110},16 L{x+114},20 L{x+110},24" fill="none" stroke="{INK}" stroke-width="1.5"></path>'
    pipe_svg = f'<svg style="display: block; width: 100%; height: auto;" viewBox="0 0 690 96" role="img" aria-label="The six-step pipeline from the one-pager">{pipe}</svg>'
    chains = ""
    for i, (name, prov, col) in enumerate([("Ethereum", "Etherscan", INK), ("BNB Smart Chain", "NodeReal", AMBER), ("Tron", "TronGrid", RED)]):
        chains += f'<div style="display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; border-left: 3px solid {col}; background: {PANEL};"><span style="font-size: 13px; font-weight: 600;">{name}</span><span style="font-family: {MONO}; font-size: 10.5px; color: {MUTED};">via {prov}</span></div>'
    body = f'''{h1("Phases 0–2 · from an idea to a question", "UP TO 15 SEPTEMBER")}
{card(label("PHASE 0 · THE IDEA · UP TO 4 SEP", RED) + para("SIH26183 asks what a police officer should do with a victim’s wallet address. The answer the team chose was a stance before it was code: <strong>no model, no clustering, no proprietary score</strong> — a conclusion that reaches a courtroom must be one an officer can re-check by hand. The one-pager of 4 September laid it out as six steps.") + pipe_svg + para("First live result: a reported address traced to <strong>Binance 14 in 2 hops, confidence 0.80</strong>, 138 addresses mapped. 337 verified wallets, 18 exchanges, Ethereum only.", 12.5, MUTED), pad=18)}
{card(label("PHASE 1 · THE FOUNDATION · 5–7 SEP", RED) + para("The first commit traced three chains from day one, because Etherscan’s free tier serves Ethereum mainnet only. One asset per trace — amounts in different coins cannot be compared or scored.") + f'<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px;">{chains}</div>' + para("By 7 September: a two-sided test suite (every rule must fire on its shape <em>and</em> stay silent on ordinary activity), reverse tracing to find the other people who paid a scammer, and <strong>407 addresses from OFAC’s live sanctions list</strong>. The mixer list came back empty — Tornado Cash had been delisted — and that was written down as the correct answer.", 12.5), pad=18)}
<div style="display: flex; gap: 18px; align-items: stretch;">
<div style="width: 6px; background: {AMBER}; border-radius: 2px; flex-shrink: 0;"></div>
<div style="display: flex; flex-direction: column; gap: 10px; padding: 6px 0;">
{label("PHASE 2 · THE INTERNAL JUDGING ROUND · BETWEEN 7 AND 15 SEP", AMBER)}
<p style="margin: 0; font-family: {SERIF}; font-size: 24px; line-height: 1.3; color: {INK}; max-width: 600px;">“Since you pointed out money laundering, have you done any research to support your claims?”</p>
{para("The honest answer was no. The README asserted that laundering moves as stablecoins, that USDT on Tron is the dominant rail for Indian scam proceeds, and that its thresholds were right — and cited nothing. The same judges would sit the next round. The exact date of this round is not recorded in the repository.", 12.5, MUTED, 600)}
</div>
</div>'''
    return page(4, "Phases 0 to 2", "PHASES 0–2", body)


def _wrap(s, n):
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            lines.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return lines


# ---------------------------------------------------------------- page 5: 15 Sep
def p5():
    # grouped bars: amount split old vs new, positives vs controls
    groups = [("Old thresholds", 12 / 32, 19 / 47, "12 / 32", "19 / 47"), ("New thresholds", 6 / 32, 5 / 47, "6 / 32", "5 / 47")]
    g = ""
    for i, (name, p, c, pl, cl) in enumerate(groups):
        x = 40 + i * 150
        for j, (v, lab, col) in enumerate([(p, pl, INK), (c, cl, RED)]):
            h = v * 300
            g += f'<rect x="{x + j*48}" y="{150 - h:.1f}" width="40" height="{h:.1f}" fill="{col}"></rect><text x="{x + j*48 + 20}" y="{150 - h - 6:.1f}" text-anchor="middle" font-family="{MONO}" font-size="10" fill="{INK}">{round(v*100)}%</text>'
        g += f'<text x="{x + 44}" y="168" text-anchor="middle" font-family="{SANS}" font-size="10.5" fill="{INK}">{name}</text>'
    legend = f'<rect x="40" y="184" width="10" height="10" fill="{INK}"></rect><text x="56" y="193" font-family="{SANS}" font-size="10" fill="{MUTED}">documented illicit wallets</text><rect x="190" y="184" width="10" height="10" fill="{RED}"></rect><text x="206" y="193" font-family="{SANS}" font-size="10" fill="{MUTED}">ordinary wallets (false alarms)</text>'
    chart = f'<svg width="340" height="200" viewBox="0 0 340 200" role="img" aria-label="Amount-split rule fired on"><line x1="30" y1="150" x2="330" y2="150" stroke="{RULE}"></line>{g}{legend}</svg>'
    tiles = [
        ("The time rule", "The one real correctness bug: the trace followed transfers made before the victim’s money arrived. Now only later transfers are followed.", RED),
        ("RESEARCH.md", "Every laundering claim with the source read, the exact passage and a verdict. Two overstated claims rewritten.", INK),
        ("Deposit inference", "A wallet whose every outflow sweeps to one exchange is named its probable deposit address — the one a request must name.", INK),
        ("Swaps at routers", "20 Ethereum and 4 BSC routers. A swap’s receipt is read so the trace says what the money became.", INK),
        ("Tron 7 → 40", "Tron labels read from TronScan’s own tags and checked on chain: 7 wallets / 4 exchanges → 40 / 18.", INK),
        ("Related cases", "Stored cases whose money converges. Three phishing wallets were found to share 61 intermediaries.", INK),
        ("Evidence hashing", "Every provider response hashed on arrival; the report sealed with a content hash.", INK),
        ("A case file UI", "The results view answers the officer’s questions in order; a dark console skin by default.", INK),
    ]
    tgrid = "".join(card(f'<span style="font-size: 13.5px; font-weight: 600; color: {c};">{t}</span><span style="font-size: 11.5px; line-height: 1.5; color: {MUTED};">{s}</span>', pad=12) for t, s, c in tiles)
    body = f'''{h1("Phase 3 · research, correctness and measurement", "15 SEPTEMBER · 25 COMMITS")}
{para("One long session, run from a written brief with a fixed budget and ordered phases — adversarial review first, evidence second, features after. Tests went from 140 to 172.", 13.5, MUTED)}
<div style="display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px;">{tgrid}</div>
<div style="display: flex; gap: 18px; align-items: stretch;">
{card(label("THE AMOUNT-SPLIT RULE, MEASURED ON 79 REAL WALLETS") + chart, pad=14, extra=" flex-shrink: 0;")}
<div style="display: flex; flex-direction: column; gap: 10px; justify-content: center;">
{label("THE INCONVENIENT RESULT, PUBLISHED", RED)}
<p style="margin: 0; font-family: {SERIF}; font-size: 20px; line-height: 1.35; color: {INK};">The old thresholds flagged 40% of ordinary wallets. The new ones flag 11% — and no threshold separates the two groups.</p>
{para("So a pattern is a reason to look closer and is never scored. 40 documented-illicit and 48 ordinary wallets were fetched by script, 1,416 provider requests snapshotted so the run reproduces offline, 68 threshold combinations swept.", 12, MUTED)}
</div>
</div>'''
    return page(5, "Phase 3", "PHASE 3", body)


# ---------------------------------------------------------------- page 6: 16-20 Sep
def p6():
    beats = [("The report", 5.28), ("The trace", 7.37), ("The map", 4.74), ("Screened", 4.21), ("3 complaints", 5.27), ("The handoff", 6.84), ("The stance", 5.27), ("Exchequer", 4.23)]
    total = sum(b for _, b in beats)
    x = 0
    strip = ""
    for i, (n, d) in enumerate(beats):
        w = d / total * 690
        fill = RED if n == "Exchequer" else (INK if i % 2 == 0 else "#3a3f45")
        strip += f'<rect x="{x:.1f}" y="0" width="{w - 3:.1f}" height="54" fill="{fill}"></rect>'
        strip += f'<text x="{x + 8:.1f}" y="22" font-family="{SANS}" font-size="10.5" font-weight="600" fill="{PAPER}">{n}</text><text x="{x + 8:.1f}" y="40" font-family="{MONO}" font-size="9.5" fill="#c9c6bd">{d:.1f} s</text>'
        x += w
    film = f'<svg style="display: block; width: 100%; height: auto;" viewBox="0 0 690 54" role="img" aria-label="Launch film v3 storyboard, 43.2 seconds">{strip}</svg>'
    rename = f'''<div style="display: flex; align-items: center; gap: 18px;">
<span style="font-family: {SERIF}; font-size: 24px; color: {MUTED}; text-decoration: line-through;">TraceChain</span>
<svg width="34" height="14" viewBox="0 0 34 14" aria-hidden="true"><path d="M0,7 L30,7 M25,2 L31,7 L25,12" fill="none" stroke="{INK}" stroke-width="1.6"></path></svg>
{mark_svg(34)}<span style="font-family: {SERIF}; font-size: 28px; font-weight: 600; color: {INK};">Exchequer</span>
</div>'''
    body = f'''{h1("Phases 4–6 · becoming Exchequer, and showing it", "16–20 SEPTEMBER")}
{card(label("PHASE 4 · 16 SEP · 23 COMMITS", RED) + rename + para("Renamed at 00:15 because a rival SIH26183 team ships as “TraceChain”. The Exchequer was named for the chequered cloth on which the Crown’s money was counted — one square red, the sum being traced.", 12.5) + f'<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px;">' + "".join(card(f'<span style="font-size: 12.5px; font-weight: 600;">{t}</span><span style="font-size: 11px; line-height: 1.45; color: {MUTED};">{s}</span>', pad=10, bg=PAPER) for t, s in [("Hosted on Railway", "One Docker image, a /data volume. Sign-in added, then removed at the user’s request."), ("Instant demos", "Responses kept on disk and the demos traced at startup: flagship 43 s cold → 0.12 s."), ("CI on every push", "Tests and the frontend build; a live pick from Etherscan’s phishing list; “Stop after 1:30”.")]) + '</div>', pad=18)}
{card(label("PHASE 5 · 17 SEP · 7 COMMITS", RED) + f'<div style="display: flex; gap: 18px; align-items: center;">{mark_svg(64)}' + para("The chequer mark. A sign-in page drawn over the real ledger of addresses the tool knows, coloured by what it knows. <strong>Present mode</strong>: any case as four projector screens. Tron and BSC pagination bounded by records read, after a busy wallet paged for minutes on the hosted demo. 234 tests.", 12.5) + '</div>', pad=18)}
{card(label("PHASE 6 · 18–20 SEP · DOCUMENTS AND THE LAUNCH FILM", RED) + para("19 September: the <strong>Director proposal</strong> (5 pages) and the <strong>Research Report</strong> (12 pages, with RESEARCH.md as an 18-page appendix). 19–20 September: the launch film in three cuts — v1 screenshots (rejected as bland), v2 “one red square”, and <strong>v3, 43.2 seconds, the latest</strong>: drawn SVG and type only, narrated by the Emma voice, with its own score.", 12.5) + label("V3 STORYBOARD · 43.2 S") + film + f'<p style="margin: 0; font-family: {SERIF}; font-size: 15px; font-style: italic; color: {INK};">“No model, no clustering, no proprietary score. But everything hand-checked. That’s Exchequer for you in a nutshell.”</p>', pad=18)}'''
    return page(6, "Phases 4 to 6", "PHASES 4–6", body)


# ---------------------------------------------------------------- page 7: 22-23 Sep
def p7():
    comp = [("Exchange wallets", 1099, INK), ("Deposit addresses", 24018, "#3a3f45"), ("Frozen by Tether", 9392, NAVY), ("Hack & scam", 8940, AMBER), ("Sanctioned", 1061, RED), ("Mixers + routers", 78, MUTED)]
    tot = sum(v for _, v, _ in comp)
    x = 0; bar = ""; leg = ""
    for i, (n, v, c) in enumerate(comp):
        w = v / tot * 690
        bar += f'<rect x="{x:.1f}" y="0" width="{max(w, 2):.1f}" height="30" fill="{c}"></rect>'
        x += w
    for i, (n, v, c) in enumerate(comp):
        col, row = i % 3, i // 3
        leg += f'<rect x="{col*230}" y="{46 + row*22}" width="11" height="11" fill="{c}"></rect><text x="{col*230 + 18}" y="{56 + row*22}" font-family="{SANS}" font-size="11" fill="{INK}">{n}</text><text x="{col*230 + 212}" y="{56 + row*22}" text-anchor="end" font-family="{MONO}" font-size="11" fill="{INK}">{v:,}</text>'
    compsvg = f'<svg style="display: block; width: 100%; height: auto;" viewBox="0 0 690 92" role="img" aria-label="Composition of 44,588 labelled addresses">{bar}{leg}</svg>'
    commits = [
        ("00:05", "2dda364", "Exchange labels 337 → 1,020 · OFAC refreshed", False),
        ("00:12", "3053ab5", "Stolen-funds category · mixer pools rebuilt", False),
        ("00:24", "f825542", "Five more governments’ sanctions lists", True),
        ("00:40", "966ffec", "All demos re-verified cold", True),
        ("03:21", "53740c1", "8,600 reported phishing and scam wallets", False),
        ("05:25", "8803efb", "19,027 Bitget customer deposit addresses", True),
        ("06:55", "1971e33", "README rewritten · every data source documented", False),
        ("07:06", "318426a", "Tether’s USDT freeze list · demo 11", False),
        ("07:13", "2dcdec1", "Swaps into USDT/USDC followed onward", False),
        ("08:05", "073b1c6", "Draft request letters to exchange and Tether", False),
        ("08:09", "68ba2af", "4,991 Binance customer deposit addresses", True),
    ]
    rows = ""
    for t, h, s, dep in commits:
        pill = f'<span style="font-family: {SANS}; font-size: 9.5px; font-weight: 600; letter-spacing: 1px; color: {PAPER}; background: {RED}; border-radius: 3px; padding: 2px 6px;">DEPLOYED</span>' if dep else ""
        rows += f'<div style="display: flex; align-items: center; gap: 12px; padding: 6px 0; border-bottom: 1px solid {RULE};"><span style="width: 42px; font-family: {MONO}; font-size: 11px; color: {MUTED};">{t}</span><span style="width: 62px; font-family: {MONO}; font-size: 11px; color: {NAVY};">{h}</span><span style="flex-grow: 1; font-size: 12.5px; color: {INK};">{s}</span>{pill}</div>'
    body = f'''{h1("Phase 7 · from 407 labels to 44,588", "22–23 SEPTEMBER · 11 COMMITS · 4 DEPLOYMENTS")}
{card(label("WHAT THE 44,588 LABELLED ADDRESSES ARE") + compsvg, pad=16)}
{card(label("23 SEPTEMBER, COMMIT BY COMMIT") + f'<div style="display: flex; flex-direction: column;">{rows}</div>', pad=16)}
<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px;">
{card(label("CAUGHT BEFORE IT SHIPPED", RED) + para("EigenLayer operator tags read as exchanges · a verified Tron wallet dropped by a re-scan · an exchange count first given as 106 (really 92) · a Tornado pool Tether froze losing its mixer label.", 12, INK), pad=14)}
{card(label("HOW EVERY ADDRESS GOT IN", GREEN) + para("Each import names a pinned source, checks every address on chain before accepting it, and records where it came from. Government lists are copied exactly as published.", 12, INK), pad=14)}
</div>'''
    return page(7, "Phase 7", "PHASE 7", body)


# ---------------------------------------------------------------- page 8: bug hunt + now
def p8():
    steps = [("Static", "ruff over backend, scripts and tests"), ("Endpoints", "every endpoint on 15 real cases, error paths too"), ("Browser", "every page in headless Brave; errors captured")]
    flow = ""
    for i, (t, s) in enumerate(steps):
        x = i * 232
        flow += f'<rect x="{x}" y="0" width="212" height="58" rx="4" fill="{PANEL}" stroke="{RULE}"></rect><text x="{x+14}" y="24" font-family="{SANS}" font-size="13" font-weight="600" fill="{INK}">{i+1}. {t}</text>'
        flow += "".join(f'<text x="{x+14}" y="{41 + j*12}" font-family="{SANS}" font-size="10" fill="{MUTED}">{part}</text>' for j, part in enumerate(_wrap(s, 38)))
        if i < 2:
            flow += f'<path d="M{x+214},29 L{x+228},29 M{x+223},24 L{x+229},29 L{x+223},34" fill="none" stroke="{INK}" stroke-width="1.5"></path>'
    flowsvg = f'<svg width="690" height="60" viewBox="0 0 690 60" role="img" aria-label="Three-step bug hunt">{flow}</svg>'
    caps = [("Tracing", "3 chains · 8 assets · both directions · the time rule · swaps into stablecoins followed"),
            ("Attribution", "25,117 exchange addresses · 24,018 customer deposit addresses · probable deposits inferred"),
            ("Screening", "6 governments · Tether freezes · mixers stop the trace · hack and scam wallets"),
            ("Outputs", "case view · Present mode · sealed report · draft letters to the exchange and Tether")]
    capg = "".join(f'<div style="display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid {RULE};"><span style="width: 92px; flex-shrink: 0; font-size: 12px; font-weight: 600;">{t}</span><span style="font-size: 12px; line-height: 1.45; color: {MUTED};">{s}</span></div>' for t, s in caps)
    opens = [("Push and deploy the bug fix <span style=\"font-family: " + MONO + ";\">0b46c4e</span>", True),
             ("Licences before commercial use: OpenSanctions (non-commercial), ScamSniffer (GPL-3.0)", False),
             ("Demo order: skip trace 2; trace 11 answers “why Tron?”", False),
             ("Letters: an officer confirms the legal provision", False),
             ("SIH registration as Exchequer; the deck still says TraceChain", False),
             ("Still to build: live TronScan tags on Tron traces; Bitcoin; a PDF report", False)]
    ol = "".join(f'<div style="display: flex; gap: 10px; align-items: flex-start; padding: 5px 0;"><span style="width: 12px; height: 12px; margin-top: 3px; flex-shrink: 0; border: 1.5px solid {RED if hot else INK}; border-radius: 2px; background: {RED if hot else "transparent"};"></span><span style="font-size: 12px; line-height: 1.45; color: {INK};">{t}</span></div>' for t, hot in opens)
    bug = lambda n, t, s: card(f'<div style="display: flex; gap: 10px; align-items: baseline;"><span style="font-family: {MONO}; font-size: 12px; color: {RED};">BUG {n}</span><span style="font-size: 14px; font-weight: 600;">{t}</span></div>' + para(s, 12, MUTED), pad=14)
    body = f'''{h1("Phase 8 · the bug hunt, and where it stood", "23 SEPTEMBER · MORNING")}
{flowsvg}
<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px;">
{bug(1, "A false “Frozen by Tether”", "Tether’s blacklist holds the zero address and 24 system addresses where tokens are burned. A USDC burn was flagged as a freeze and offered a letter about the zero address. Fixed in the importer and the matcher.")}
{bug(2, "“Stop after 1:30” did not hold", "Each swap follow-on got a fresh time budget, so a case could run 4.5 minutes. Follow-ons now share what is left.")}
</div>
{para("Zero JavaScript errors across 15 cases. Committed as <span style=\"font-family: " + MONO + ";\">0b46c4e</span> at 08:26 and deployed the same morning. Two database backups swept into that commit by mistake were taken out before anything left the machine.", 12, MUTED)}
<div style="display: grid; grid-template-columns: 1.15fr 1fr; gap: 16px; flex-grow: 1;">
{card(label("WHAT EXISTED THAT MORNING") + f'<div style="display: flex; flex-direction: column;">{capg}</div>' + label("ALSO") + para("RESEARCH.md sources every claim and every dataset · DEMO.md: 11 verified traces · JUDGE_QA.md: 15 answers · 273 tests · CI on every push · the one-pager, two PDFs and the launch film.", 11.5, MUTED), pad=16)}
{card(label("OPEN ITEMS THAT MORNING", RED) + ol, pad=16)}
</div>'''
    return page(8, "Phase 8", "PHASE 8", body)


# ---------------------------------------------------------------- page 9: 23 Sep pm + now
def p9():
    commits = [
        ("11:46", "87e02bd", "TronScan’s own tag read live for Tron wallets no file names", False),
        ("12:03", "f9bd400", "Faster tag lookups · mistyped Tron addresses caught by checksum", True),
        ("12:08", "cd4e113", "Repository tidied · proposal PDFs and the launch film committed", False),
        ("12:12", "f9ded52", "Judge Q&amp;A to 18 answers · demo 12, an exchange found live", False),
        ("12:19", "5af080a", "TronScan warning tags (“Suspicious”) become screening hits", False),
        ("12:21", "2a5cba2", "Related cases search follow-ons and flagged-but-unnamed wallets", False),
        ("12:56", "a4a842a", "Polygon and Arbitrum — five chains", True),
        ("13:28", "8df02c2", "BSC: quiet wallets found by nonce · 38 → 184 labels · wallet statement", True),
        ("21:02", "8558ab6", "Pro-rata tracing: how much of the money is the victim’s", True),
        ("21:16", "b5eed01", "Demos re-run every morning by CI · the amount in the exchange letter", True),
        ("21:23", "3e3fe05", "Demo expectations recorded: 12 of 12 as documented", False),
    ]
    rows = ""
    for t, h, s, dep in commits:
        pill = f'<span style="font-family: {SANS}; font-size: 9.5px; font-weight: 600; letter-spacing: 1px; color: {PAPER}; background: {RED}; border-radius: 3px; padding: 2px 6px;">DEPLOYED</span>' if dep else ""
        rows += f'<div style="display: flex; align-items: center; gap: 12px; padding: 4px 0; border-bottom: 1px solid {RULE};"><span style="width: 42px; font-family: {MONO}; font-size: 11px; color: {MUTED};">{t}</span><span style="width: 62px; font-family: {MONO}; font-size: 11px; color: {NAVY};">{h}</span><span style="flex-grow: 1; font-size: 12px; color: {INK};">{s}</span>{pill}</div>'
    # pro-rata before / after on the real BSC wallet
    full = 600
    part = full * 9.42 / 40
    pr = (f'<rect x="0" y="6" width="{full}" height="16" fill="{RULE}"></rect>'
          f'<rect x="0" y="6" width="{part:.1f}" height="16" fill="{RED}"></rect>'
          f'<text x="{part + 8:.1f}" y="19" font-family="{MONO}" font-size="11" fill="{INK}">≈ 9.42 of 40 USDT likely the victim’s</text>'
          f'<text x="{full}" y="38" text-anchor="end" font-family="{SANS}" font-size="10" fill="{MUTED}">40 USDT sent down this path · at one wallet it was 9.6% of what came in</text>')
    prsvg = f'<svg style="display: block; width: 100%; height: auto;" viewBox="0 0 {full} 42" role="img" aria-label="Pro-rata estimate on a real BSC wallet">{pr}</svg>'
    before_after = f'''<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
<div style="display: flex; flex-direction: column; gap: 4px;">{label("BEFORE")}<span style="font-family: {SERIF}; font-size: 17px; color: {MUTED}; text-decoration: line-through;">“28,679.41 USDT arrived” · 0.73</span></div>
<div style="display: flex; flex-direction: column; gap: 4px;">{label("AFTER", RED)}<span style="font-family: {SERIF}; font-size: 17px; color: {INK};">“≈ 9.42 of 40 USDT likely arrived” · 0.47</span></div>
</div>'''
    caps = [("Tracing", "5 chains · native coins, USDT, USDC · both directions · the time rule · swaps followed"),
            ("Attribution", "25,508 exchange addresses · TronScan tags read live · deposits inferred · a pro-rata amount"),
            ("Screening", "6 governments · Tether freezes · mixers stop the trace · scam wallets · TronScan warnings"),
            ("Outputs", "case view · wallet statement · Present mode · sealed report · letters that name the amount")]
    capg = "".join(f'<div style="display: flex; gap: 12px; padding: 6px 0; border-bottom: 1px solid {RULE};"><span style="width: 84px; flex-shrink: 0; font-size: 11.5px; font-weight: 600;">{t}</span><span style="font-size: 11.5px; line-height: 1.4; color: {MUTED};">{s}</span></div>' for t, s in caps)
    opens = ["Licences before commercial use: OpenSanctions (non-commercial), ScamSniffer (GPL-3.0)",
             "Letters: an officer confirms the legal provision",
             "Old BSC wallets take about a minute on the free provider",
             "Still to build: Bitcoin · a PDF report · pro-rata on reverse traces",
             "The 25-second social cut of the film · Railway config before 1 Dec"]
    ol = "".join(f'<div style="display: flex; gap: 10px; align-items: flex-start; padding: 4px 0;"><span style="width: 11px; height: 11px; margin-top: 3px; flex-shrink: 0; border: 1.5px solid {INK}; border-radius: 2px;"></span><span style="font-size: 11.5px; line-height: 1.4; color: {INK};">{t}</span></div>' for t in opens)
    body = f'''{h1("Phase 9 · wider, and honest", "23 SEPTEMBER · AFTERNOON AND NIGHT · 11 COMMITS · 5 DEPLOYMENTS")}
{card(label("COMMIT BY COMMIT") + f'<div style="display: flex; flex-direction: column;">{rows}</div>', pad=14)}
{card(label("PRO-RATA, ON A REAL BSC WALLET", RED) + prsvg + before_after, pad=14)}
<div style="display: grid; grid-template-columns: 1.15fr 1fr; gap: 14px; flex-grow: 1;">
{card(label("WHAT EXISTS NOW") + f'<div style="display: flex; flex-direction: column;">{capg}</div>' + para("DEMO.md: 12 traces, checked every morning · JUDGE_QA.md: 19 answers · 311 tests · the site stays up for judges.", 11, MUTED), pad=14)}
{card(label("OPEN ITEMS", RED) + ol, pad=14)}
</div>'''
    return page(9, "Phase 9 and where it stands", "PHASE 9", body)


pages = {"Main.dc.html": p1(), "Numbers.dc.html": p2(), "Arc.dc.html": p3(), "Phases-0-2.dc.html": p4(),
         "Phase-3.dc.html": p5(), "Phases-4-6.dc.html": p6(), "Phase-7.dc.html": p7(), "Phase-8.dc.html": p8(), "Phase-9.dc.html": p9()}
titles = ["Cover", "The project in numbers", "The arc", "Phases 0–2", "Phase 3", "Phases 4–6", "Phase 7", "Phase 8", "Phase 9 · now"]
boards, order = {}, []
for i, (name, html) in enumerate(pages.items()):
    (OUT / name).write_text(html)
    col, row = i % 4, i // 4
    boards[name] = {"x": col * (W + 80), "y": row * (H + 120), "w": W, "h": H, "title": titles[i], "paper": "a4"}
    order.append(name)
index = {"v": 3, "createdOnFiles": {"v": 1, "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
         "title": "Exchequer — Project Timeline", "launch": {"view": "canvas"}, "pages": [], "boards": boards,
         "order": order, "notes": {}, "designSystems": []}
(OUT / "canvas.json").write_text(json.dumps(index, indent=1))
print("wrote", len(pages), "pages")
