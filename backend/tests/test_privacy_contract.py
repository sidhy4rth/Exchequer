"""The contract for privacy-protocol notes (#189): optional, typed, never a stop.

`privacy_matches` and `privacy_notes` are present only with the flag
EXCHEQUER_PRIVACY_CATEGORY on; every other case reads them as None.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts import read_case

FIXTURE = Path(__file__).parent / "fixtures" / "contract" / "no_attribution.json"
# Railgun's Relay Adapt contract on Ethereum (Railgun-Community/shared-models network-config.ts @b37e643).
RAILGUN = "0x22af4edbea3de885dda8f0a0653e6209e44e5b84"
MATCH = {"address": RAILGUN, "category": "privacy", "entity": "Railgun", "label": "Railgun: Relay Adapt contract",
         "source": "Railgun shared-models network-config.ts @b37e643", "depth": 2, "value_received_native": 1.5,
         "is_terminal": False, "origin": "privacy_protocols.json"}


def case():
    return json.loads(FIXTURE.read_text())


def test_a_case_without_privacy_notes_reads_them_as_none():
    read = read_case(case())
    assert read.privacy_matches is None and read.privacy_notes is None


def test_a_privacy_match_is_read_typed():
    read = read_case({**case(), "privacy_matches": [MATCH], "privacy_notes": ["Privacy protocol: ..."]})
    [match] = read.privacy_matches
    assert match.entity == "Railgun" and match.category == "privacy" and match.is_terminal is False
    assert read.privacy_notes == ["Privacy protocol: ..."]


@pytest.mark.parametrize("bad", [{"is_terminal": True}, {"category": "mixer"}, {"severity": "high"}])
def test_a_privacy_match_is_never_a_stop_never_another_category_and_has_no_extra_keys(bad):
    with pytest.raises(ValidationError):
        read_case({**case(), "privacy_matches": [{**MATCH, **bad}]})
