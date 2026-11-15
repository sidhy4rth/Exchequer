"""The NCRP acknowledgement number's usual shape (app/ncrp.py): a soft note,
never a refusal. The SOP for NCRP-CFCFRMS (6.1(d), 6.2(c)) gives 14 digits
starting with 2 (portal) or 3 (1930)."""
from __future__ import annotations

import pytest

from app import ncrp
from app.pipeline import TraceRequest


@pytest.mark.parametrize("number", ["21234567890123", "31234567890123", "2123 4567 8901 23", "3123-4567-8901-23"])
def test_a_portal_or_1930_number_gets_no_note(number):
    assert ncrp.shape_note(number) is None


@pytest.mark.parametrize("number", [
    "2123456789012",     # 13 digits
    "51234567890123",    # 14 digits starting with 5
    "212345678901234",   # 15 digits
    "1234567890",        # an older-looking or mistyped number
    "ABC12345",          # letters, as the citizen site takes
])
def test_another_shape_gets_the_note(number):
    assert ncrp.shape_note(number) == ncrp.NOTE


def test_the_note_never_repeats_the_number():
    number = "51234567890123"
    assert number not in ncrp.shape_note(number)
    assert "14 digits starting with 2 or 3" in ncrp.NOTE


@pytest.mark.parametrize("value", [None, "", "   ", 21234567890123])
def test_nothing_given_gets_no_note(value):
    assert ncrp.shape_note(value) is None


@pytest.mark.parametrize("number", ["2123456789012", "51234567890123", "1234567890", "12345678901234567890"])
def test_the_trace_form_still_takes_a_number_with_the_note(number):
    # The note never narrows what was accepted before: 10 to 20 digits.
    assert ncrp.shape_note(number) == ncrp.NOTE
    assert TraceRequest(address="T" + "a" * 33, ncrp_ack=number).ncrp_ack == number
