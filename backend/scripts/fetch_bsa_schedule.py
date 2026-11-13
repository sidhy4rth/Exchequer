"""Copy the s.63(4) certificate's wording from the official text of the Act. Run by hand.

The certificate an electronic record goes to court with is THE SCHEDULE of the
Bharatiya Sakshya Adhiniyam, 2023 (Act 47 of 2023), "[See section 63(4)(c)]".
Its wording is legal text, so it is never typed: this script downloads India
Code's PDF of the Act, cuts out the Schedule, and writes it to
data/bsa_schedule_certificate.txt with where it came from, the date the PDF says
the text is current on, and the PDF's SHA-256. The draft certificates
(app/certificates.py) are built from that file, and its tests check it.

Two readings of the PDF must agree before anything is written: poppler's
pdftotext, whose spacing is kept, and pypdf, already a dependency. They are
compared with all spaces removed, so a word one of them splits ("electro nic",
which pypdf reads on page 52) is caught by the other, and nothing in the legal
text is corrected by hand.

    cd backend && python scripts/fetch_bsa_schedule.py           # needs pdftotext (poppler-utils)
    cd backend && python scripts/fetch_bsa_schedule.py --pdf aa202347.pdf   # a copy already downloaded

Never edit the data file by hand: run this again. Tests never touch the network.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE_URL = "https://www.indiacode.nic.in/bitstream/123456789/20063/1/aa202347.pdf"
OUT = Path(__file__).resolve().parent.parent / "data" / "bsa_schedule_certificate.txt"
START = "THE SCHEDULE"
END = "STATEMENT OF OBJECTS AND REASONS"  # what follows the Schedule in India Code's PDF
MUST_HAVE = ("[See section 63(4)(c)]", "CERTIFICATE", "PART A", "(To be filled by the Party)",
             "PART B", "(To be filled by the Expert)", "SHA256", "(Hash report to be enclosed with the certificate)")


def download(url: str) -> bytes:
    import httpx  # only this script needs the network

    response = httpx.get(url, timeout=60, follow_redirects=False, headers={"User-Agent": "Exchequer (BSA Schedule copy)"})
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        sys.exit(f"{url} did not send a PDF.")
    return response.content


def with_pdftotext(pdf: Path) -> str:
    if not shutil.which("pdftotext"):
        sys.exit("pdftotext not found: install poppler-utils (apt) or poppler (brew).")
    return subprocess.run(["pdftotext", "-layout", str(pdf), "-"], check=True, capture_output=True, text=True).stdout


def with_pypdf(pdf: Path) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages)


def schedule(text: str) -> list[str]:
    """The Schedule's lines, page numbers and blank lines dropped, runs of spaces made one."""
    begin = text.rfind(START)  # the last one: the first is in the table of contents
    end = text.find(END, begin)
    if begin < 0 or end < 0:
        sys.exit("The Schedule was not found where India Code's PDF keeps it.")
    lines = []
    for raw in text[begin:end].splitlines():
        line = re.sub(r"\s+", " ", raw.replace("\f", " ")).strip()
        if line and not re.fullmatch(r"\d{1,3}", line):  # a page number on its own line
            lines.append(line)
    return lines


def current_on(text: str) -> str:
    found = re.search(r"\[As on the ([^\]]+)\]", text)
    if not found:
        sys.exit("The PDF does not say what date its text is current on.")
    return found.group(1).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pdf", type=Path, help="a copy of the PDF already downloaded from SOURCE_URL")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        pdf = args.pdf or Path(tmp) / "bsa.pdf"
        if not args.pdf:
            pdf.write_bytes(download(SOURCE_URL))
        data = pdf.read_bytes()
        poppler, pypdf = with_pdftotext(pdf), with_pypdf(pdf)
    lines = schedule(poppler)
    if "".join(lines).replace(" ", "") != "".join(schedule(pypdf)).replace(" ", ""):
        sys.exit("pdftotext and pypdf read the Schedule differently; nothing written.")
    missing = [m for m in MUST_HAVE if not any(m in line for line in lines)]
    if missing:
        sys.exit(f"The Schedule is missing {missing}; nothing written.")
    header = [
        "# THE SCHEDULE [See section 63(4)(c)] of the Bharatiya Sakshya Adhiniyam, 2023 (Act 47 of 2023).",
        f"# Source: {SOURCE_URL}",
        f"# Text as on: {current_on(poppler)}",
        f"# Source PDF SHA-256: {hashlib.sha256(data).hexdigest()}",
        "# Written by scripts/fetch_bsa_schedule.py from pdftotext, checked against pypdf. Never edit by hand.",
    ]
    OUT.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    print(f"{OUT}: {len(lines)} lines of the Schedule, text as on {current_on(poppler)}.")


if __name__ == "__main__":
    main()
