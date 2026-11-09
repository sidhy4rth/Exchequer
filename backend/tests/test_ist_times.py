"""Reports and letters give IST beside UTC; what is stored stays UTC.

An Indian officer reads IST, and a block explorer often shows UTC, so a reader
needs both. The failure to catch is the date: a transfer at 20:00 UTC happened on
the next day in India, and a letter or report that gets that wrong sends someone
to the wrong day's records.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from pypdf import PdfReader

from app import request_letters
from app.report import _when, _when_iso, build_report, render_text_report
from app.report_pdf import render_pdf
from app.request_letters import draft

from test_report import full_result, stored
from test_report_pdf import REPORT
from test_request_letters import case as letter_case


def utc(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.mark.parametrize("moment, printed", [
    (utc(2026, 11, 3, 16, 10), "2026-11-03 21:40 IST (16:10 UTC)"),               # the brief's example
    (utc(2026, 11, 3, 20, 0), "2026-11-04 01:30 IST (2026-11-03 20:00 UTC)"),     # the next IST date
    (utc(2026, 11, 3, 18, 29), "2026-11-03 23:59 IST (18:29 UTC)"),               # a minute before the boundary
    (utc(2026, 11, 3, 18, 30), "2026-11-04 00:00 IST (2026-11-03 18:30 UTC)"),    # exactly on it
    (utc(2026, 12, 31, 18, 30), "2027-01-01 00:00 IST (2026-12-31 18:30 UTC)"),   # the next year
])
def test_a_time_prints_in_both_zones_and_names_the_utc_date_only_when_it_differs(moment, printed):
    assert _when(int(moment.timestamp())) == printed
    assert _when_iso(moment.isoformat()) == printed


@pytest.mark.parametrize("missing", [None, 0])
def test_a_missing_block_time_still_says_so(missing):
    assert _when(missing) == "time unknown"


@pytest.mark.parametrize("stored_value, printed", [
    ("2026-11-03T20:00:00+00:00", "2026-11-04 01:30 IST (2026-11-03 20:00 UTC)"),
    ("2026-11-03T20:00:00Z", "2026-11-04 01:30 IST (2026-11-03 20:00 UTC)"),
    ("2026-11-03T20:00:00", "2026-11-04 01:30 IST (2026-11-03 20:00 UTC)"),          # no zone: stored times are UTC
    ("2026-11-04T01:30:00+05:30", "2026-11-04 01:30 IST (2026-11-03 20:00 UTC)"),
    ("not a time", "not a time"),                                                     # never crash, never guess
    (None, "time unknown"),
    ("", "time unknown"),
])
def test_a_stored_timestamp_prints_in_both_zones(stored_value, printed):
    assert _when_iso(stored_value) == printed


# -- reports -----------------------------------------------------------------------
def test_the_report_shows_ist_beside_utc_where_a_person_reads_a_time():
    flat = " ".join(render_text_report(build_report(stored(full_result()))).split())
    assert "Traced at : 2026-09-15 17:30 IST (12:00 UTC)" in flat
    assert "between 2023-11-15 03:43 IST (2023-11-14 22:13 UTC) and 2023-11-16 07:30 IST (02:00 UTC) to" in flat
    assert "sweeps between : 2023-11-15 03:43 IST (2023-11-14 22:13 UTC) and" in flat


def test_every_line_of_appendix_b_fits_the_page():
    result = full_result()
    result["transfers"] = [{"hash": "0x" + "a" * 64, "from": "0x" + "1" * 40, "to": "0x" + "2" * 40,
                            "value_native": 123456789.1234, "timestamp": 1_700_000_000, "internal": True}]
    text = render_text_report(build_report(stored(result)))
    appendix = text[text.index("APPENDIX B"):text.index("APPENDIX C")]
    assert "2023-11-15 03:43 IST (2023-11-14 22:13 UTC)" in appendix
    assert max(len(line) for line in appendix.splitlines()) <= 78


def test_list_ages_say_they_are_in_utc():
    """List dates are UTC, so a late-evening trace is the next day in IST: the label prevents a false mismatch."""
    flat = " ".join(render_text_report(build_report(stored(full_result()))).split())
    assert "compared with 2026-09-15 (UTC), the day this case was traced" in flat


def test_stored_data_and_the_json_report_stay_utc():
    result = full_result()
    report = build_report(stored(result))
    assert report["case"]["traced_at"] == "2026-09-15T12:00:00+00:00"
    assert report["generated_at"].endswith("+00:00")
    assert report["trace_path"][1]["first_seen"] == 1_700_000_000


def test_the_evidence_manifest_keeps_its_utc_record():
    result = full_result()
    result["evidence"] = {
        "count": 1, "retrieved": 1, "from_cache": 0, "providers": ["etherscan"],
        "first_retrieved_at": "2026-09-15T15:40:36Z", "last_retrieved_at": "2026-09-15T15:40:36Z",
        "manifest_sha256": "ab" * 32,
        "records": [{"provider": "etherscan", "request": "GET x", "retrieved_at": "2026-09-15T15:40:36Z",
                     "sha256": "cd" * 32, "bytes": 812, "from_cache": False}],
    }
    text = render_text_report(build_report(stored(result)))
    manifest = text[text.index("APPENDIX C"):]
    assert "2026-09-15T15:40:36Z" in manifest and "IST" not in manifest


def test_the_pdf_shows_when_it_was_traced_in_both_zones():
    pdf = render_pdf(REPORT, render_text_report(REPORT))
    assert "2026-10-13 12:51 IST (07:21 UTC)" in PdfReader(io.BytesIO(pdf)).pages[0].extract_text()


# -- letters -----------------------------------------------------------------------
@pytest.mark.parametrize("now, dated", [
    (utc(2026, 11, 2, 20, 0), "03 November 2026"),   # already the 3rd in India
    (utc(2026, 11, 2, 10, 0), "02 November 2026"),   # the same day in both
])
def test_a_letter_is_dated_in_ist(monkeypatch, now, dated):
    monkeypatch.setattr(request_letters, "_utc_now", lambda: now)
    assert f"Date      : {dated}" in draft("case-1", letter_case(), "exchange")


def test_a_letter_gives_every_time_in_both_zones():
    text = draft("case-1", letter_case(), "exchange")
    assert "traced 2026-09-24 15:30 IST (10:00 UTC)," in text
    assert "received 2.500000 ETH in 1 transfer(s), 2025-09-16 10:50 IST (05:20 UTC)" in text
    assert "all times UTC" not in text


def test_the_tether_letter_gives_every_time_in_both_zones():
    result = letter_case(asset="USDT")
    text = draft("case-1", result, "tether")
    assert "2025-09-16 10:50 IST (05:20 UTC)" in text
    assert "(UTC):" not in text
