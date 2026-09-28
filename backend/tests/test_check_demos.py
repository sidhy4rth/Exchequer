"""The daily demo check: strict for settled demos, tolerant for the one built to move."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_demos", Path(__file__).resolve().parent.parent / "scripts" / "check_demos.py")
check_demos = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_demos)
drift = check_demos.drift

EXPECT = {"exchange": "Binance", "followed_exchange": None, "confidence": 0.875}


def test_a_settled_demo_fails_when_its_exchange_changes():
    assert drift(EXPECT, {**EXPECT, "exchange": "OKX"})


def test_a_settled_demo_tolerates_a_small_score_wobble():
    assert drift(EXPECT, {**EXPECT, "confidence": 0.85}) == []


def test_a_moving_demo_may_change_exchange_and_score():
    assert drift(EXPECT, {**EXPECT, "exchange": "OKX", "confidence": 0.39}, volatile=True) == []


def test_a_moving_demo_still_fails_if_it_reaches_nothing():
    assert drift(EXPECT, {**EXPECT, "exchange": None, "confidence": None}, volatile=True)


def test_only_demo_3_is_marked_as_moving():
    import json
    demos = json.loads(check_demos.EXPECTATIONS.read_text())
    assert [d["demo"] for d in demos if d.get("volatile")] == [3]


def test_a_request_lost_once_is_retried(monkeypatch):
    calls = []

    def flaky(base, demo):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("The read operation timed out")
        return {"exchange": None}

    monkeypatch.setattr(check_demos, "trace", flaky)
    assert check_demos.trace_with_retry("x", {"demo": 4}, wait=0) == {"exchange": None}
    assert len(calls) == 2


def test_a_request_lost_twice_is_a_failure(monkeypatch):
    import pytest

    def down(base, demo):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(check_demos, "trace", down)
    with pytest.raises(TimeoutError):
        check_demos.trace_with_retry("x", {"demo": 4}, wait=0)
