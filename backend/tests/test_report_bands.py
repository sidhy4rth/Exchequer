"""R10 in the signed text report: the band leads, and the score appears only beside its working."""
from __future__ import annotations

from app.report import _band_word, build_report, render_text_report

from test_report import full_result, stored


def test_band_words_match_the_scoring_thresholds():
    assert [_band_word(s) for s in (1.0, 0.75, 0.74, 0.5, 0.25, 0.1, None)] == [
        "High", "High", "Moderate", "Moderate", "Low", "Very low", "n/a"]


def test_the_confidence_section_leads_with_the_band():
    result = full_result()
    text = render_text_report(build_report(stored(result)))
    section = text[text.index("\nCONFIDENCE"):]
    band = _band_word(result["confidence"])
    assert section.index(f"Band             : {band}") < section.index("Score            :")
    assert "not a probability" in section
