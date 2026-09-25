"""Renders project/*.dc.html into the timeline PDF and one PNG per page.

    python3 gen.py && python3 render.py

Uses headless Brave (Chrome works the same with its own path). Each page is a
fixed 794 x 1123 px A4 artboard; the PDF prints them one per page, and each
PNG is a screenshot of one page on its own, for the GitHub gallery.
"""
import pathlib, re, subprocess

HERE = pathlib.Path(__file__).parent
PROJECT = HERE
BUILD = HERE / "build"
BROWSER = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
ORDER = ["Main", "Numbers", "Arc", "Phases-0-2", "Phase-3", "Phases-4-6", "Phase-7", "Phase-8", "Phase-9"]
PDF = HERE.parent / "Exchequer-Project-Timeline-v2.pdf"

HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Exchequer — Project Timeline</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&amp;family=IBM+Plex+Sans:wght@400;500;600&amp;family=IBM+Plex+Serif:wght@500;600&amp;display=swap">
<style>body{margin:0;background:#f4f2ec;font-family:'IBM Plex Sans','Helvetica Neue',sans-serif;color:#16191d}
a{color:#1f3a5f}@page{size:794px 1123px;margin:0}html,body{margin:0;padding:0}
.pg{width:794px;height:1123px;overflow:hidden;break-after:page}.pg:last-child{break-after:auto}</style></head><body>"""


def inner(name: str) -> str:
    html = (PROJECT / f"{name}.dc.html").read_text()
    return re.search(r"</helmet>\s*(.*?)\s*</x-dc>", html, re.S).group(1)


def brave(*args: str) -> None:
    subprocess.run([BROWSER, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--virtual-time-budget=8000", *args], check=True, capture_output=True, timeout=180)


BUILD.mkdir(exist_ok=True)
pages = [inner(n) for n in ORDER]
doc = BUILD / "timeline-print.html"
doc.write_text(HEAD + "".join(f'<section class="pg">{p}</section>' for p in pages) + "</body></html>")
brave("--no-pdf-header-footer", f"--print-to-pdf={PDF}", doc.as_uri())
print("wrote", PDF.name)
for i, p in enumerate(pages, 1):
    one = BUILD / f"page-{i}.html"
    one.write_text(HEAD + f'<section class="pg">{p}</section></body></html>')
    brave(f"--screenshot={HERE / f'page-{i}.png'}", "--window-size=794,1123", "--force-device-scale-factor=2", one.as_uri())
    print("wrote", f"page-{i}.png")
