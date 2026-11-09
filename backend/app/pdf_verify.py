"""Checking an Exchequer PDF: its signed attachment, and whether its pages say the same.

Only the attached text file is signed (report_pdf). The pages -- the page 1
summary, the printed copy of the report (Part 2) and the footers -- are
copies for reading, and anyone can edit them without touching the
attachment. The owner chose (8 Nov) not to sign the PDF itself, so this
module does the next best thing for a reader who uploads the PDF to /verify:

1. Pull out the one attached report and check it exactly as pasted text is
   checked (signing.verify_report). If it is not genuine, that is the answer.
   Every embedded file counts -- the attachments list, a file attached to a
   page as an annotation, and any other embedded file stream -- and there
   must be exactly one.
2. Read the text the pages hold and compare it with the signed report:
   - page 1 is drawn from the signed text alone (report_pdf.summary_facts),
     so it is drawn again here from the attached file, and the uploaded
     page 1's text must be exactly that, whitespace aside: a word, a line or
     an "addendum" added, changed or left out is a difference, whether or
     not it names an address;
   - so it is named plainly, page 1 must also carry its NOT SIGNED notice,
     show the case, exchange, address and amount the signed report states,
     and show no address, hash or amount the signed report lacks;
   - page 1 must hold no image, and no page an annotation (a note, stamp or
     attached file drawn over the page): neither is in the text layer, so
     neither could be compared;
   - every footer must name the signed report's case, hash and key, and the
     printed copy must be the signed text, word for word.
3. Draw the whole PDF again from the attached file (report_pdf.render_issued
   draws it the same way every time) and require the uploaded file to carry
   exactly that, beyond its text: no script, open action, bookmark, form or
   metadata stream; the same title, subject and other document information
   (dates aside); page boxes equal to the paper (no CropBox hiding part of a
   page); the same fonts and resources; and the same drawing operators on
   every page (no shape painted over the text, nothing drawn elsewhere).
   A file-level change is 'pdf_altered'; a page's, 'summary_differs' or
   'printed_copy_differs'.
   Anything else is named, and the verdict says the pages do not match.

What this cannot catch: a viewer's own behaviour outside the file, and a PDF
made by an older version of the page template, which reads as differing (the
attached file then still verifies and is the record to act on). The pages
themselves are not signed, so the attached file stays the record to act on,
and the result says so.

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
NOT_LAID_OUT = "The summary page could not be"  # laid out, or drawn from the signed report (report_pdf)
MISSING_GLYPH = "\x00"  # what pypdf reads back for a character the font could not draw

DETAILS = {
    "summary_differs": ("The attached report is genuine, but page 1 of this PDF does not match it: {problems} "
                        "Page 1 is not signed. Act only on what the attached report states, shown below."),
    "pdf_altered": ("The attached report is genuine, but this PDF was changed after Exchequer issued it: {problems} "
                    "A genuine Exchequer PDF carries none of this. Act only on what the attached report states, "
                    "shown below."),
    "printed_copy_differs": ("The attached report is genuine, but the printed pages of this PDF do not match "
                             "it: {problems} Act only on the attached report, shown below."),
    "pdf_no_report": "This PDF does not carry exactly one attached Exchequer report, so there is nothing signed to check.",
    "pdf_unreadable": "This file starts like a PDF but cannot be read as one.",
    "pdf_busy": "Other PDFs are being checked right now. Try again in a minute.",
}
MATCHED = (" The PDF's pages match it: page 1 holds exactly what Exchequer prints for this report, Part 2 is "
           "the signed text, and the file draws and carries nothing else (no script, bookmark, cropped page or "
           "shape over the text). The pages themselves are not signed, so the attached report is the record to "
           "act on.")
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
        files = _embedded_file_count(reader, started)
    except Exception as exc:  # noqa: BLE001 -- a stranger's file can break a parser in any way; never a 500
        logger.info("An uploaded PDF could not be read: %s", type(exc).__name__)
        return _verdict("pdf_unreadable")
    count_files = max(len(attachments), files)
    if len(attachments) != 1 or files != 1:
        return _verdict("pdf_no_report", f"This PDF carries {count_files} attached files. An Exchequer PDF "
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
        summary_problems, copy_problems, summary_numbers = _compare(reader, pages, text, result["finding"])
        file_problems, summary_drawn, copy_drawn = _against_redraw(
            reader, pages, text, result["finding"].get("case_id") or "", summary_numbers, started)
        # A page whose text already differs is named by that; what it draws adds nothing.
        summary_problems += [] if summary_problems else summary_drawn
        copy_problems += [] if copy_problems else copy_drawn
    except Exception as exc:  # noqa: BLE001 -- as above; the pages then count as not matching
        logger.info("The pages of an uploaded PDF could not be read: %s", type(exc).__name__)
        file_problems, copy_problems = [], []
        summary_problems = ["Its pages could not be read in time, so they cannot be compared."]
    problems = summary_problems + file_problems + copy_problems
    result["pdf"].update(pages_match=not problems, problems=problems)
    if summary_problems:  # page 1 is what a reader acts on: named first
        status = "summary_differs"
    elif file_problems:
        status = "pdf_altered"
    elif copy_problems:
        status = "printed_copy_differs"
    else:
        result["detail"] += MATCHED
        return result
    result.update(status=status, genuine=False,
                  detail=DETAILS[status].format(problems=" ".join(problems)))
    return result


MAX_OBJECTS = 200_000  # a 2 MB PDF holds far fewer; a crafted one is cut off, then refused


def _embedded_file_count(reader: Any, started: float) -> int:
    """Every embedded file the PDF can show a reader: each embedded file
    stream reachable from the document (the attachments list, a page's
    FileAttachment annotation, a page's associated files...), plus any
    FileAttachment annotation whose file is not one of those streams."""
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

    seen: set[tuple[int, int]] = set()
    streams: set[tuple[int, int]] = set()
    stack: list[Any] = [reader.trailer]
    visited = 0
    file_annotations = 0
    while stack:
        visited += 1
        if visited > MAX_OBJECTS or time.monotonic() - started > READ_SECONDS:
            raise TimeoutError
        item = stack.pop()
        ref = None
        if isinstance(item, IndirectObject):
            ref = (item.idnum, item.generation)
            if ref in seen:
                continue
            seen.add(ref)
            item = item.get_object()
        if isinstance(item, DictionaryObject):  # a stream is one too
            if item.get("/Type") == "/EmbeddedFile":
                streams.add(ref or (-visited, 0))
            if item.get("/Subtype") == "/FileAttachment":
                file_annotations += 1
            stack.extend(v for k, v in item.items() if k != "/Parent")
        elif isinstance(item, ArrayObject):
            stack.extend(item)
    return max(len(streams), file_annotations + (1 if streams else 0))


def _annotations(page: Any) -> int:
    annots = page.get("/Annots")
    annots = annots.get_object() if annots is not None else None
    return len(annots) if annots else 0


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


def _differs_from_redrawn(summary: str, signed: str, footer: str, page_line: Any) -> str | None:
    """None if `summary` (the uploaded summary pages' text) is what
    report_pdf draws for `signed`, whitespace aside; else a few words from
    where they first differ."""
    from .report_pdf import render_summary

    got = _compact(summary)
    forms = [_compact("\n".join(line for line in form.split("\n") if line != footer and not page_line.fullmatch(line)))
             for form in render_summary(signed)]
    if any(_same_text(got, wanted) for wanted in forms):
        return None
    wanted = forms[0]
    at = next((i for i, (a, b) in enumerate(zip(got, wanted, strict=False)) if a != b and a != MISSING_GLYPH),
              min(len(got), len(wanted)))
    # Back from the compacted position to the page's own words.
    positions = [i for i, c in enumerate(summary) if not c.isspace()]
    start = positions[at] if at < len(positions) else len(summary)
    before = summary[:start].split()[-4:]  # whole words: the few before the difference
    after = summary[start:start + 70].split()
    return _short(" ".join(before + after) or "the end of the page")


def _short(value: str) -> str:
    value = value.strip()
    return value if len(value) <= 90 else value[:87] + "…"


def _compare(reader: Any, pages: list[str], signed: str,
             finding: dict[str, Any]) -> tuple[list[str], list[str], set[int]]:
    """(problems with page 1, problems with the footers and the printed copy,
    the numbers of the pages the summary is on)."""
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
    marked = [n for n in range(1, len(pages) + 1) if _annotations(reader.pages[n - 1])]
    if marked:
        on_summary = [n for n in marked if n in {m for m, _ in summary_pages}]
        (problems if on_summary else copy_problems).append(
            f"Page{'s' if len(marked) > 1 else ''} {', '.join(map(str, marked))} "
            f"carr{'y' if len(marked) > 1 else 'ies'} an annotation (a note, stamp, link or attached file drawn "
            "over the page). Exchequer adds none, and what an annotation shows is not in the page's text, so "
            "it cannot be compared.")
    if not problems:
        # Page 1 is drawn from the signed text alone: draw it again and require the same text.
        differs = _differs_from_redrawn(summary, signed, footer, page_line)
        if differs is not None:
            problems.append("Page 1 is not exactly what Exchequer would print for the signed report: it "
                            f"differs at \u201c{differs}\u201d. A word, line or note added to the page, or left "
                            "out, is a difference.")

    if not in_part_two:
        copy_problems.append("This PDF has no printed copy of the report (Part 2).")
    else:
        printed = "\n".join(rest)
        note = _compact(PART_TWO_NOTE)
        printed_compact = _compact(printed)
        if not printed_compact.startswith(note) or not _same_text(printed_compact[len(note):], signed):
            copy_problems.append("The printed copy (Part 2) differs from the attached file.")
    return problems, copy_problems, {n for n, _ in summary_pages}


# -- comparing the whole file with the PDF Exchequer issues for the signed text --------
# The text compare above reads only what each page's text layer says. A viewer
# also shows a document's scripts, open actions, bookmarks, title and
# metadata, crops a page to its CropBox, and paints whatever a page's drawing
# operators draw -- none of it in the text layer. report_pdf draws the whole
# PDF from the signed text alone, and does so the same way every time, so it
# is drawn again here from the attachment and the uploaded file must carry
# exactly that: the same catalog and document information (dates aside), the
# same page entries (boxes, rotation, fonts and other resources) and the same
# drawing operators on every page. Rewriting the file without changing what it
# shows (another tool saving it again) keeps all of these.
_DATE = re.compile(r"D:\d{14}(?:Z(?:00'00'?)?|[+-]\d\d'?\d\d'?)?")
_DATES = ("/CreationDate", "/ModDate")
_STREAM_CODING = ("/Length", "/Filter", "/DecodeParms", "/DL")
_FILE_WORDS = {
    "/OpenAction": "an action run when the file is opened (a script, or a jump elsewhere)",
    "/AA": "actions run when the file is opened, closed, saved or printed",
    "/Outlines": "bookmarks, which a viewer shows beside the pages",
    "/AcroForm": "form fields, which a viewer draws over the pages",
    "/Metadata": "a metadata stream, from which a viewer can show a title or description",
    "/ViewerPreferences": "viewer settings (such as showing the document title instead of the file name)",
    "/PageMode": "a setting for what a viewer shows beside the pages",
    "/PageLabels": "page labels, which a viewer shows instead of the page numbers",
    "/OCProperties": "optional content (layers a viewer can show or hide)",
    "/URI": "a link base", "/Dests": "named destinations", "/Threads": "article threads",
    "/Collection": "a portfolio layout",
}
_NAME_WORDS = {
    "/JavaScript": "a script run when the file is opened",
    "/EmbeddedFiles": "an attached file other than the signed report, or the report under another name",
}
_INFO_WORDS = {"/Title": "title", "/Subject": "subject", "/Author": "author", "/Keywords": "keywords",
               "/Creator": "creator", "/Producer": "producer"}
_BOXES = ("/MediaBox", "/CropBox", "/TrimBox", "/ArtBox", "/BleedBox")


class _Canon:
    """A comparable form of a PDF object tree: indirect references resolved,
    each stream read as its decoded bytes, numbers as numbers. Bounded, since
    the tree is a stranger's."""

    def __init__(self, started: float) -> None:
        self.started, self.memo, self.visited = started, {}, 0

    def __call__(self, item: Any, depth: int = 0) -> Any:
        import hashlib

        from pypdf.generic import (
            ArrayObject, BooleanObject, ByteStringObject, DictionaryObject, FloatObject, IndirectObject,
            NameObject, NullObject, NumberObject, StreamObject, TextStringObject,
        )

        self.visited += 1
        if self.visited > MAX_OBJECTS or time.monotonic() - self.started > READ_SECONDS:
            raise TimeoutError
        if depth > 40:
            return ("too deep",)  # never in a genuine PDF, so never equal to the redraw
        ref = None
        if isinstance(item, IndirectObject):
            ref = (item.idnum, item.generation)
            if ref in self.memo:
                return self.memo[ref]
            self.memo[ref] = ("cycle",)  # a loop back to an object being read
            item = item.get_object()
        if isinstance(item, StreamObject):
            entries = tuple(sorted((str(k), self(v, depth + 1)) for k, v in item.items()
                                   if k not in _STREAM_CODING and k != "/Parent"))
            value: Any = ("stream", entries, hashlib.sha256(item.get_data()).hexdigest())
        elif isinstance(item, DictionaryObject):
            value = ("dict", tuple(sorted((str(k), self(v, depth + 1)) for k, v in item.items() if k != "/Parent")))
        elif isinstance(item, ArrayObject):
            value = ("array", tuple(self(v, depth + 1) for v in item))
        elif isinstance(item, BooleanObject):
            value = ("bool", bool(item))
        elif isinstance(item, (FloatObject, NumberObject)):
            value = ("number", round(float(item), 4))
        elif isinstance(item, NameObject):
            value = ("name", str(item))
        elif isinstance(item, TextStringObject):
            value = ("text", str(item))
        elif isinstance(item, ByteStringObject):
            value = ("bytes", bytes(item))
        elif item is None or isinstance(item, NullObject):
            value = ("null",)
        else:
            value = ("other", type(item).__name__, repr(item)[:200])
        if ref is not None:
            self.memo[ref] = value
        return value


def _issued(signed: str, case_id: str, first_page: str) -> Any:
    """The PDF report_pdf issues for `signed`, in the form page 1 shows: the
    summary, or the short page printed when it could not be laid out."""
    from pypdf import PdfReader
    from reportlab.platypus.doctemplate import LayoutError

    from .report_pdf import render_issued

    laid_out = NOT_LAID_OUT not in first_page
    try:
        pdf = render_issued(signed, case_id, laid_out=laid_out)
    except LayoutError:
        pdf = render_issued(signed, case_id, laid_out=False)
    return PdfReader(io.BytesIO(pdf))


def _drawing(page: Any) -> Any:
    """What a page draws: its content stream's operators, in order."""
    from pypdf.generic import ContentStream

    contents = page.get_contents()
    if contents is None:
        return b""
    return contents.get_data(), lambda: ContentStream(contents, page.pdf).operations


def _same_drawing(uploaded: Any, issued: Any) -> bool:
    if uploaded == b"" or issued == b"":
        return uploaded == issued
    (data, ops), (wanted, wanted_ops) = uploaded, issued
    return data == wanted or ops() == wanted_ops()  # the same operators, however the stream is spaced


def _show(value: Any) -> str:
    return _short(str(value.get_object() if hasattr(value, "get_object") else value))


def _against_redraw(reader: Any, pages: list[str], signed: str, case_id: str, summary_numbers: set[int],
                    started: float) -> tuple[list[str], list[str], list[str]]:
    """(problems with the file as a whole, with the summary pages, with the
    rest), from comparing the uploaded PDF with the one Exchequer issues for
    `signed`."""
    issued = _issued(signed, case_id, pages[0] if pages else "")
    up, re_ = _Canon(started), _Canon(started)
    whole: list[str] = []

    root, wanted_root = reader.trailer["/Root"].get_object(), issued.trailer["/Root"].get_object()
    for key in sorted(set(root) | set(wanted_root)):
        if key in ("/Pages", "/Names"):
            continue
        if up(root.get(key)) != re_(wanted_root.get(key)):
            words = _FILE_WORDS.get(key, f"an entry ({key}) Exchequer never writes")
            whole.append(f"It carries {words}." if key not in wanted_root
                         else f"Its {key[1:]} setting is not the one Exchequer writes.")
    names = (root.get("/Names") or {})
    names = names.get_object() if hasattr(names, "get_object") else names
    wanted_names = wanted_root["/Names"].get_object()
    if not hasattr(names, "items"):
        names = {}
    for key in sorted(set(names) | set(wanted_names)):
        if up(names.get(key)) != re_(wanted_names.get(key)):
            whole.append(f"It carries {_NAME_WORDS.get(key, f'a names list ({key}) Exchequer never writes')}.")

    info = reader.trailer.get("/Info")
    info = info.get_object() if info is not None else {}
    info = info if hasattr(info, "items") else {}
    wanted_info = issued.trailer["/Info"].get_object()
    for key in sorted(set(info) | set(wanted_info)):
        if key in _DATES:
            if key in info and not _DATE.fullmatch(str(info[key].get_object())):
                whole.append(f"Its {key[1:]} is not a date: \u201c{_show(info[key])}\u201d.")
            continue
        if up(info.get(key)) != re_(wanted_info.get(key)):
            word = _INFO_WORDS.get(key, f"{key[1:]} entry")
            if key in wanted_info:
                whole.append(f"Its document {word} is \u201c{_show(info.get(key, ''))}\u201d, not the "
                             f"\u201c{_show(wanted_info[key])}\u201d Exchequer writes (a viewer can show it "
                             "in its title bar or document properties).")
            else:
                whole.append(f"Its document information carries a {word} Exchequer never writes: "
                             f"\u201c{_show(info[key])}\u201d.")

    summary: list[str] = []
    rest: list[str] = []
    if len(reader.pages) != len(issued.pages):
        rest.append(f"It has {len(reader.pages)} pages; Exchequer prints {len(issued.pages)} for this report.")
    for n, (page, wanted) in enumerate(zip(reader.pages, issued.pages, strict=False), 1):
        if time.monotonic() - started > READ_SECONDS:
            raise TimeoutError
        problems = summary if n in summary_numbers else rest
        if up(page.get("/AA")) != re_(wanted.get("/AA")):
            whole.append(f"Page {n} carries actions run when it is opened or closed (such as a script).")
        boxes = [b for b in _BOXES
                 if (b == "/MediaBox" and up(page.get(b)) != re_(wanted.get(b)))
                 or (b != "/MediaBox" and b in page and up(page[b]) != up(page.get("/MediaBox")))]
        if boxes:
            problems.append(f"Page {n} has a page box ({', '.join(b[1:] for b in boxes)}) other than the paper "
                            "Exchequer prints on, so a viewer shows only part of the page or more than it.")
        for key in sorted((set(page) | set(wanted)) - {"/Parent", "/Contents", "/Annots", "/AA", *_BOXES}):
            if up(page.get(key)) != re_(wanted.get(key)):
                what = ("fonts or other resources" if key == "/Resources"
                        else f"a {key[1:]} entry")
                problems.append(f"Page {n} uses {what} Exchequer's page does not (a changed font can show "
                                "other words than its text says)." if key == "/Resources"
                                else f"Page {n} carries {what} Exchequer's page does not.")
        if not _same_drawing(_drawing(page), _drawing(wanted)):
            problems.append(f"Page {n} draws something Exchequer's page does not (a shape, a picture, or text "
                            "drawn elsewhere or differently), which its text alone cannot show.")
    return whole, summary, rest
