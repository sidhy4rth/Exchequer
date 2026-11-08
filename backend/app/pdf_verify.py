"""Checking an Exchequer PDF: its signed attachment, and whether its pages say the same.

Only the attached text file is signed (report_pdf). The pages -- the page 1
summary, the printed copy of the report (Part 2) and the footers -- are
copies for reading, and anyone can edit them without touching the
attachment. The owner chose (8 Nov) not to sign the PDF itself, so this
module does the next best thing for a reader who uploads the PDF to /verify:

1. Pull out the one attached report and check it exactly as pasted text is
   checked (signing.verify_report). If it is not genuine, that is the answer.
2. Read the text the pages hold and compare it with the signed report:
   - page 1 must carry its NOT SIGNED notice, and show the case, exchange,
     address and amount the signed report states;
   - every address or hash, and every amount, page 1 shows must appear in the
     signed report (so one cannot be added beside the genuine one);
   - page 1 must hold no image (text in a picture cannot be read and compared);
   - every footer must name the signed report's case, hash and key, and the
     printed copy must be the signed text, word for word.
   Anything else is named, and the verdict says the pages do not match.

What this cannot catch: the check reads each page's text layer, so a page
made to look different from its own text (glyphs redrawn by a doctored font,
or text painted over) can still pass. The attached file stays the record to
act on, and the result says so.

A PDF from a stranger is hostile input: the body is capped (2 MB, as for
text), pypdf runs with tight decompression limits, the page count is
capped, reading stops after a time limit, and only a few PDFs are read at once.
"""
from __future__ import annotations

import io
import logging
import re
import threading
import time
from typing import Any

from .evidence import CONTENT_HASH_MARK
from .signing import SIGNATURE_MARK, verify_report

logger = logging.getLogger(__name__)

MAX_PAGES = 400              # a 2 MB report prints on about 250 pages
MAX_STREAM_BYTES = 8_000_000  # the largest stream a genuine PDF holds is the attachment, under 2 MB
READ_SECONDS = 20.0          # a genuine 17-page PDF reads in 0.2 s
READERS = threading.BoundedSemaphore(2)

PART_TWO_HEADING = "Part 2 · The signed text report"
PART_TWO_NOTE = ("The text the content hash and signature cover, for reading. Lines too long for the "
                 "page wrap onto the next line; the exact file is attached to this PDF.")
NOT_SIGNED = "SUMMARY: NOT SIGNED."
NOT_LAID_OUT = "The summary page could not be laid out for this case"
MISSING_GLYPH = "\x00"  # what pypdf reads back for a character the font could not draw

DETAILS = {
    "summary_differs": ("The attached report is genuine, but page 1 of this PDF does not match it: {problems} "
                        "Page 1 is not signed. Act only on what the attached report states, shown below."),
    "printed_copy_differs": ("The attached report is genuine, but the printed pages of this PDF do not match "
                             "it: {problems} Act only on the attached report, shown below."),
    "pdf_no_report": "This PDF does not carry exactly one attached Exchequer report, so there is nothing signed to check.",
    "pdf_unreadable": "This file starts like a PDF but cannot be read as one.",
    "pdf_busy": "Other PDFs are being checked right now. Try again in a minute.",
}
MATCHED = (" The PDF's pages match it, as far as their text can be read: page 1 shows the same case, exchange, "
           "address and amount, and Part 2 is the signed text. The pages themselves are not signed, so the "
           "attached report is the record to act on.")
NOT_COMPARED = (" The PDF's pages were not compared: the attached report is in an older format whose finding "
                "this check cannot read. Compare page 1 with the attached report yourself.")


class PdfBusy(Exception):
    """Too many PDFs are being read at once."""


def is_pdf(body: bytes) -> bool:
    return body.lstrip()[:5] == b"%PDF-"


def _limits():
    from pypdf import apply_configuration

    return apply_configuration(
        maximum_declared_stream_length=MAX_STREAM_BYTES,
        array_based_stream_maximum_output_length=MAX_STREAM_BYTES,
        zlib_maximum_output_length=MAX_STREAM_BYTES,
        lzw_maximum_output_length=MAX_STREAM_BYTES,
        run_length_maximum_output_length=MAX_STREAM_BYTES,
        brotli_maximum_output_length=MAX_STREAM_BYTES,
        jbig2_maximum_output_length=MAX_STREAM_BYTES,
        image_maximum_buffer_size=MAX_STREAM_BYTES,
        stream_decoding_work_maximum_length=4 * MAX_STREAM_BYTES,
        page_tree_maximum_entries=MAX_PAGES * 4,
        jbig2dec_binary=None,  # never run an outside program on a stranger's file
    )


def _verdict(status: str, detail: str | None = None) -> dict[str, Any]:
    return {"status": status, "genuine": False, "sealed": False, "hash_ok": False, "signed": False,
            "signature_ok": False, "signature_checked": False, "extra_content": False, "finding": None,
            "detail": detail or DETAILS[status], "pdf": {"pages_match": None, "problems": []}}


def verify_pdf(body: bytes) -> dict[str, Any]:
    """The /verify result for an uploaded PDF (see the module docstring)."""
    if not READERS.acquire(blocking=False):
        raise PdfBusy()
    try:
        with _limits():
            return _verify(body)
    finally:
        READERS.release()


def _verify(body: bytes) -> dict[str, Any]:
    from pypdf import PdfReader

    started = time.monotonic()
    try:
        reader = PdfReader(io.BytesIO(body), strict=False)
        if reader.is_encrypted:
            return _verdict("pdf_unreadable", "This PDF is encrypted. Exchequer never encrypts its PDFs.")
        count = len(reader.pages)
        if count > MAX_PAGES:
            return _verdict("pdf_unreadable", f"This PDF has {count} pages, more than any Exchequer report.")
        attachments = [(name, data) for name, datas in reader.attachments.items() for data in datas]
    except Exception as exc:  # noqa: BLE001 -- a stranger's file can break a parser in any way; never a 500
        logger.info("An uploaded PDF could not be read: %s", type(exc).__name__)
        return _verdict("pdf_unreadable")
    if len(attachments) != 1:
        return _verdict("pdf_no_report", f"This PDF carries {len(attachments)} attached files. An Exchequer PDF "
                                         "carries exactly one, the signed report, so there is nothing to check.")
    name, data = attachments[0]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _verdict("pdf_no_report", "The file attached to this PDF is not an Exchequer text report.")

    result = verify_report(text)
    result["pdf"] = {"attachment": str(name)[:120], "pages": count, "pages_match": None, "problems": []}
    if result["status"] not in ("genuine", "genuine_earlier_key"):
        return result  # the record itself fails: the pages cannot rescue it
    if result.get("finding") is None:
        result["detail"] += NOT_COMPARED
        return result
    try:
        pages = _page_texts(reader, started)
        summary_problems, copy_problems = _compare(reader, pages, text, result["finding"])
    except Exception as exc:  # noqa: BLE001 -- as above; the pages then count as not matching
        logger.info("The pages of an uploaded PDF could not be read: %s", type(exc).__name__)
        summary_problems, copy_problems = ["Its pages could not be read in time, so they cannot be compared."], []
    problems = summary_problems + copy_problems
    result["pdf"].update(pages_match=not problems, problems=problems)
    if summary_problems:
        status = "summary_differs"
    elif copy_problems:
        status = "printed_copy_differs"
    else:
        result["detail"] += MATCHED
        return result
    result.update(status=status, genuine=False,
                  detail=DETAILS[status].format(problems=" ".join(problems)))
    return result


def _page_texts(reader: Any, started: float) -> list[str]:
    texts = []
    for page in reader.pages:
        if time.monotonic() - started > READ_SECONDS:
            raise TimeoutError
        texts.append(page.extract_text() or "")
    return texts


# -- comparing the pages with the signed text ---------------------------------------
# A long run of letters and digits: an address or a hash on any chain.
_LONG_TOKEN = re.compile(r"[0-9A-Za-z]{25,}")
# An amount, as Exchequer prints one: 1,234.5 or 0.25 -- or a whole number
# followed by the asset's symbol (12 ETH). Not part of a date (2026-09-15), a
# time (17:30), a word (SHA-256, v2) or a long token. Hop counts and other
# small whole numbers are not amounts and are left alone.
_NUMBER = r"(?<![\w.,:/-])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+{asset})(?![\w:/-]|\.\d|,\d)"
_ASSET_LINE = "Asset followed   : "


def _compact(text: str) -> str:
    return "".join(text.split())


def _seal_facts(text: str) -> tuple[str, str]:
    digest, key = "", "unsigned"
    for line in text.splitlines():
        if line.startswith(CONTENT_HASH_MARK + " ("):
            digest = line.rsplit(": ", 1)[-1].strip()
        elif line.startswith(SIGNATURE_MARK + " ("):
            key = line.split("key ", 1)[-1].split(")", 1)[0].strip()
    return digest, key


def _footer(case_id: str, digest: str, key: str) -> str:
    """What report_pdf._build prints at the foot of every page."""
    return f"Exchequer case {case_id[:8]} · SHA-256 {digest[:16]}… · key {key[:16]}"


def _found(needle: str, haystack: str) -> bool:
    """`needle` in `haystack`, whitespace aside; a character the font could not
    draw (read back as NUL) stands for any one character."""
    needle, haystack = _compact(needle), _compact(haystack)
    if not needle:
        return True
    if MISSING_GLYPH not in haystack:
        return needle in haystack
    pattern = "".join(f"(?:{re.escape(c)}|\\x00)" for c in needle)
    return re.search(pattern, haystack) is not None


def _same_text(printed: str, signed: str) -> bool:
    """The printed copy is the signed text, whitespace aside (the page wraps
    long lines) and a NUL standing for a character the font could not draw."""
    printed, signed = _compact(printed), _compact(signed)
    if len(printed) != len(signed):
        return False
    return all(p == s or p == MISSING_GLYPH for p, s in zip(printed, signed, strict=True))


def _numbers(text: str, asset: str) -> list[str]:
    whole = rf"|\d+(?=\s*{re.escape(asset)}\b)" if asset else ""
    return re.findall(_NUMBER.replace("{asset}", whole), text)


def _asset(signed: str) -> str:
    line = next((line for line in signed.splitlines() if line.startswith(_ASSET_LINE)), "")
    return line[len(_ASSET_LINE):].split(" ", 1)[0].strip()


def _value(number: str) -> float | None:
    try:
        return float(number.replace(",", ""))
    except ValueError:
        return None


def _has_image(page: Any) -> bool:
    from pypdf.generic import ContentStream

    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") or {}
    for ref in xobjects.values():
        if (ref.get_object() or {}).get("/Subtype") in ("/Image", "/Form"):
            return True  # report_pdf draws neither on a summary page
    contents = page.get_contents()
    if contents is None:
        return False
    return any(op == b"INLINE IMAGE" for _, op in ContentStream(contents, page.pdf).operations)


# The captions report_pdf._part_one prints above the exchange and beside the address.
HEADING_CAPTIONS = ("WHERE THE MONEY WENT", "WHO FUNDED THE ADDRESS")
ADDRESS_CAPTIONS = ("Address to ask the exchange about", "Address to ask the exchange to confirm",
                    "Wallet the funds reached")


def _follows(lines: list[str], captions: tuple[str, ...], value: str) -> bool:
    """Whether the text right after the first of `captions` on the page starts
    with `value`, whitespace aside (a caption may wrap in its table cell)."""
    page = _compact("".join(lines))
    found = [(page.find(_compact(c)), _compact(c)) for c in captions if _compact(c) in page]
    if not found:
        return False
    at, caption = min(found)
    pattern = "".join(f"(?:{re.escape(c)}|\\x00)" for c in _compact(value))
    return re.match(pattern, page[at + len(caption):]) is not None


def _short(value: str) -> str:
    value = value.strip()
    return value if len(value) <= 90 else value[:87] + "…"


def _compare(reader: Any, pages: list[str], signed: str, finding: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(problems with page 1, problems with the footers and the printed copy)."""
    case_id = finding.get("case_id") or ""
    digest, key = _seal_facts(signed)
    footer = _footer(case_id, digest, key)
    page_line = re.compile(r"page \d+")

    summary_pages, rest, copy_problems, in_part_two = [], [], [], False
    for n, text in enumerate(pages, 1):
        lines = text.split("\n")
        if footer not in lines:
            copy_problems.append(f"The footer of page {n} does not name this report's case, hash and key.")
        body = [line for line in lines if line != footer and not page_line.fullmatch(line)]
        if not in_part_two and PART_TWO_HEADING in body:
            at = body.index(PART_TWO_HEADING)
            summary_pages.append((n, body[:at]))
            rest += body[at + 1:]
            in_part_two = True
        elif in_part_two:
            rest += body
        else:
            summary_pages.append((n, body))

    summary = "\n".join(line for _, lines in summary_pages for line in lines)
    problems: list[str] = []
    first_lines = summary_pages[0][1] if summary_pages else []
    first = "\n".join(first_lines)
    laid_out = NOT_LAID_OUT not in first
    if laid_out and not _found(NOT_SIGNED, first):
        problems.append(f"Page 1 does not carry the '{NOT_SIGNED[:-1]}' notice every Exchequer PDF prints.")
    if not _found(f"Case {case_id}", first):
        problems.append(f"Page 1 does not name the case the signed report is about ({case_id}).")
    if laid_out:
        # Each fact where page 1 prints it: the heading under its caption, the
        # address in its row. Elsewhere on the page proves nothing.
        exchange = finding.get("exchange")
        if not _follows(first_lines, HEADING_CAPTIONS, exchange or "No exchange reached"):
            problems.append(f"Page 1 does not name the exchange the signed report names ({exchange})." if exchange
                            else "Page 1 names an exchange, but the signed report says none was reached.")
        if finding.get("address") and not _follows(first_lines, ADDRESS_CAPTIONS, finding["address"]):
            problems.append(f"Page 1 does not show the address the signed report names ({finding['address']}).")
        if finding.get("likely_arrived") and not _found(finding["likely_arrived"], first):
            problems.append(f"Page 1 does not state the amount the signed report states "
                            f"({_short(finding['likely_arrived'])}).")
    strangers = sorted({t for t in _LONG_TOKEN.findall(summary) if t not in signed})
    if strangers:
        shown = ", ".join(strangers[:3]) + (f" and {len(strangers) - 3} more" if len(strangers) > 3 else "")
        problems.append(f"Page 1 shows {'an address or hash' if len(strangers) == 1 else 'addresses or hashes'} "
                        f"the signed report never mentions: {shown}.")
    asset = _asset(signed)
    known = {_value(n) for n in _numbers(signed, asset)} | {_value(n) for n in re.findall(r"\d[\d,]*\.?\d*", signed)}
    odd = []
    for number in _numbers(summary, asset):
        value = _value(number)
        if value is not None and value not in known and not any(
                k is not None and abs(k - value) <= 1e-6 * max(1.0, abs(value)) for k in known):
            odd.append(number)
    if odd:
        shown = ", ".join(dict.fromkeys(odd))
        problems.append(f"Page 1 shows {'a figure' if len(set(odd)) == 1 else 'figures'} the signed report never "
                        f"states: {_short(shown)}.")
    if any(_has_image(reader.pages[n - 1]) for n, _ in summary_pages):
        problems.append("Page 1 holds an image. Exchequer's summary never does, and text in a picture cannot "
                        "be read and compared.")

    if not in_part_two:
        copy_problems.append("This PDF has no printed copy of the report (Part 2).")
    else:
        printed = "\n".join(rest)
        note = _compact(PART_TWO_NOTE)
        printed_compact = _compact(printed)
        if not printed_compact.startswith(note) or not _same_text(printed_compact[len(note):], signed):
            copy_problems.append("The printed copy (Part 2) differs from the attached file.")
    return problems, copy_problems
