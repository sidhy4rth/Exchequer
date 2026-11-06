"""The signed METHODOLOGY describes what this case did, not a fixed text.

Before (r2-g2-documented-claims-vs-code-7-4), every report said a swap "ends
there and is not continued on the other asset" -- in the same signed report
that printed FOLLOW-ON TRACES continuing it (demo 3) -- and the exchange
sentence left out attributions made from TronScan tags read at trace time.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from app.report import build_report, render_text_report

from test_report import full_result, stored

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contract"
DEMOS = {d["demo"]: d["result"] for d in json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "recorded_demos.json").read_text())}
OLD_SENTENCE = "is not continued on the other asset"


def methodology(result: dict) -> str:
    return " ".join(build_report(stored(result))["methodology"])


def test_methodology_describes_follow_ons_when_they_ran():
    demo3 = json.loads((FIXTURES / "deposit_inferred.json").read_text())
    text = methodology(demo3)
    assert OLD_SENTENCE not in text
    assert "followed as its own trace" in text and "FOLLOW-ON TRACES" in text
    flat = " ".join(render_text_report(build_report(stored(demo3))).split())
    assert OLD_SENTENCE not in flat and "FOLLOW-ON TRACES" in flat


def test_methodology_says_the_trace_stops_when_follow_ons_were_off():
    result = copy.deepcopy(DEMOS[8])  # a swap, nothing followed
    result["provenance"] = {"settings": {"follow_swaps": False}}
    assert "switched off for this case" in methodology(result)


def test_methodology_says_when_a_swap_was_found_but_not_followed():
    text = methodology(DEMOS[8])
    assert "was not followed for this case" in text and "followed as its own trace from" not in text


def test_methodology_keeps_the_old_sentence_for_an_incoming_trace():
    assert OLD_SENTENCE in methodology(DEMOS[4])


def test_methodology_keeps_the_old_sentence_for_a_case_stored_before_follow_ons():
    result = full_result()
    result.pop("follow_ons", None)
    result["swaps"] = [{"output_read": True, "asset_out": "USDT", "router_label": "Uniswap"}]
    assert OLD_SENTENCE in methodology(result)


def test_methodology_names_tronscan_tags_when_they_were_read():
    text = methodology(DEMOS[12])
    assert "TronScan" in text and "public tags at trace time" in text
    assert "TronScan" not in methodology(DEMOS[1])
