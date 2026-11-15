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


def _run_main(monkeypatch, tmp_path, demo3_exchange, state_file):
    """main() over a one-demo expectations file, demo 3 answering `demo3_exchange`."""
    import json
    import sys

    expectations = tmp_path / "expect.json"
    expectations.write_text(json.dumps([{
        "demo": 3, "address": "0x" + "5" * 40, "chain": "ethereum", "asset": "ETH",
        "max_depth": 3, "direction": "outgoing", "volatile": True,
        "expect": {"exchange": "Binance", "followed_exchange": None, "confidence": 0.875},
    }]))
    monkeypatch.setattr(check_demos, "EXPECTATIONS", expectations)
    monkeypatch.setattr(check_demos, "trace_with_retry",
                        lambda base, demo: {"exchange": demo3_exchange, "confidence": 0.5})
    monkeypatch.setattr(sys, "argv", ["check_demos", "--state", str(state_file)])
    return check_demos.main()


def test_a_moving_demo_warns_on_its_first_miss_and_fails_on_the_second(monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    assert _run_main(monkeypatch, tmp_path, None, state) == 0   # day 1: warning
    assert _run_main(monkeypatch, tmp_path, None, state) == 1   # day 2: fails


def test_a_hit_clears_the_remembered_miss(monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    assert _run_main(monkeypatch, tmp_path, None, state) == 0
    assert _run_main(monkeypatch, tmp_path, "Binance", state) == 0
    assert _run_main(monkeypatch, tmp_path, None, state) == 0   # a fresh first miss


class _Captured:
    def __init__(self):
        self.headers = None

    def urlopen(self, request, timeout=None):
        import io
        import json
        self.headers = {k.lower(): v for k, v in request.header_items()}
        body = io.BytesIO(json.dumps({"exchange": None}).encode())
        return body


def test_the_demo_code_is_sent_when_the_job_has_one(monkeypatch):
    # The live site refuses live traces without the code once
    # EXCHEQUER_DEMO_CODE is set on Render; the Action passes the repository
    # secret DEMO_CODE in the same variable, and the script must send it.
    captured = _Captured()
    monkeypatch.setattr(check_demos.urllib.request, "urlopen", captured.urlopen)
    monkeypatch.setenv("EXCHEQUER_DEMO_CODE", "river-otter-42")
    check_demos.trace("https://example.test", {"address": "0x1", "chain": "ethereum", "asset": "ETH",
                                                "max_depth": 3, "direction": "outgoing"})
    assert captured.headers["x-exchequer-demo-code"] == "river-otter-42"


def test_no_code_header_on_an_open_site(monkeypatch):
    captured = _Captured()
    monkeypatch.setattr(check_demos.urllib.request, "urlopen", captured.urlopen)
    monkeypatch.delenv("EXCHEQUER_DEMO_CODE", raising=False)
    check_demos.trace("https://example.test", {"address": "0x1", "chain": "ethereum", "asset": "ETH",
                                                "max_depth": 3, "direction": "outgoing"})
    assert "x-exchequer-demo-code" not in captured.headers


def _http_error(code):
    import io
    import urllib.error
    return urllib.error.HTTPError("x/trace", code, "refused", {}, io.BytesIO(b"{}"))


def test_a_refused_request_is_not_retried(monkeypatch):
    """r1-ci-github-6: a 4xx (a wrong or stale demo code) is an answer, not a lost
    request; retrying it adds wrong codes toward the site's lockout."""
    import pytest
    calls = []

    def refused(base, demo):
        calls.append(1)
        raise _http_error(403)

    monkeypatch.setattr(check_demos, "trace", refused)
    with pytest.raises(check_demos.urllib.error.HTTPError):
        check_demos.trace_with_retry("x", {"demo": 4}, wait=0)
    assert len(calls) == 1


def test_a_wrong_demo_code_stops_the_whole_run_after_one_request(monkeypatch, capsys):
    calls = []

    def refused(base, demo):
        calls.append(demo["demo"])
        raise _http_error(403)

    monkeypatch.setattr(check_demos, "trace", refused)
    monkeypatch.setattr("sys.argv", ["check_demos.py", "--base", "x"])
    assert check_demos.main() == 1
    assert len(calls) == 1
    assert "demo code" in capsys.readouterr().out.lower()


def test_a_server_error_is_still_retried_once(monkeypatch):
    calls = []

    def flaky(base, demo):
        calls.append(1)
        if len(calls) == 1:
            raise _http_error(502)
        return {"exchange": None}

    monkeypatch.setattr(check_demos, "trace", flaky)
    assert check_demos.trace_with_retry("x", {"demo": 4}, wait=0) == {"exchange": None}


def _http_429(retry_after=None):
    import io
    import urllib.error
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError("x/trace", 429, "Too Many Requests", headers, io.BytesIO(b"{}"))


def test_only_takes_numbers_and_ranges():
    import argparse

    import pytest
    assert check_demos.parse_only("3,6-8") == {3, 6, 7, 8}
    assert check_demos.parse_only(" 5 ") == {5}
    for bad in ("x", "8-6", "3,", "1-2-3"):
        with pytest.raises(argparse.ArgumentTypeError):
            check_demos.parse_only(bad)


def test_only_refuses_a_demo_that_does_not_exist(monkeypatch):
    import pytest
    monkeypatch.setattr(check_demos, "trace", lambda base, demo: pytest.fail("must not trace"))
    monkeypatch.setattr("sys.argv", ["check_demos.py", "--only", "13"])
    with pytest.raises(SystemExit) as exc:
        check_demos.main()
    assert exc.value.code == 2


def test_only_runs_just_the_chosen_demos(monkeypatch, capsys):
    import json
    demos = {d["demo"]: d for d in json.loads(check_demos.EXPECTATIONS.read_text())}
    calls = []

    def answer(base, demo):
        calls.append(demo["demo"])
        expect = demos[demo["demo"]]["expect"]
        return {"exchange": expect["exchange"], "confidence": expect["confidence"],
                "followed_attribution": {"exchange": expect["followed_exchange"]}}

    monkeypatch.setattr(check_demos, "trace", answer)
    monkeypatch.setattr("sys.argv", ["check_demos.py", "--only", "3,6-8"])
    assert check_demos.main() == 0
    assert calls == [3, 6, 7, 8]
    assert "4 of 4 demos as documented" in capsys.readouterr().out


def test_record_with_only_rewrites_just_those_entries(monkeypatch, tmp_path):
    import json
    original = check_demos.EXPECTATIONS.read_text()
    expectations = tmp_path / "expect.json"
    expectations.write_text(original)
    monkeypatch.setattr(check_demos, "EXPECTATIONS", expectations)
    monkeypatch.setattr(check_demos, "trace", lambda base, demo: {"exchange": "Recorded", "confidence": 0.5})
    monkeypatch.setattr("sys.argv", ["check_demos.py", "--record", "--only", "6"])
    assert check_demos.main() == 0

    before, after = json.loads(original), json.loads(expectations.read_text())
    assert [d for d in after if d["demo"] != 6] == [d for d in before if d["demo"] != 6]
    assert next(d for d in after if d["demo"] == 6)["expect"] == {
        "exchange": "Recorded", "followed_exchange": None, "confidence": 0.5}
    # Byte for byte: the file is exactly what the writer produces, so the
    # untouched entries come out as they went in.
    assert original == json.dumps(before, indent=1, ensure_ascii=False) + "\n"
    assert expectations.read_text() == json.dumps(after, indent=1, ensure_ascii=False) + "\n"


def test_a_429_without_wait_on_429_stops_the_run(monkeypatch):
    calls = []

    def limited(base, demo):
        calls.append(demo["demo"])
        raise _http_429("120")

    monkeypatch.setattr(check_demos, "trace", limited)
    monkeypatch.setattr(check_demos.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("slept")))
    monkeypatch.setattr("sys.argv", ["check_demos.py"])
    assert check_demos.main() == 1
    assert calls == [1]


def test_wait_on_429_honours_retry_after_then_carries_on(monkeypatch, capsys):
    slept, calls = [], []

    def limited_once(base, demo):
        calls.append(demo["demo"])
        if len(calls) == 1:
            raise _http_429("120")
        return {"exchange": None}

    monkeypatch.setattr(check_demos, "trace", limited_once)
    monkeypatch.setattr(check_demos.time, "sleep", slept.append)
    monkeypatch.setattr("sys.argv", ["check_demos.py", "--only", "1-2", "--wait-on-429"])
    assert check_demos.main() == 0
    assert slept == [120.0]
    assert calls == [1, 1, 2]
    assert "waiting 120s" in capsys.readouterr().out


def test_wait_on_429_falls_back_and_caps_the_wait():
    assert check_demos.retry_after(_http_429()) == check_demos.WAIT_429_DEFAULT
    assert check_demos.retry_after(_http_429("soon")) == check_demos.WAIT_429_DEFAULT
    assert check_demos.retry_after(_http_429("999999")) == check_demos.WAIT_429_CAP


def test_wait_on_429_gives_up_after_its_retries(monkeypatch):
    import pytest
    slept, calls = [], []

    def limited(base, demo):
        calls.append(1)
        raise _http_429("5")

    monkeypatch.setattr(check_demos, "trace", limited)
    monkeypatch.setattr(check_demos.time, "sleep", slept.append)
    with pytest.raises(check_demos.urllib.error.HTTPError):
        check_demos.trace_waiting_on_429("x", {"demo": 4}, tries=2)
    assert len(calls) == 3 and slept == [5.0, 5.0]


def test_only_keeps_the_remembered_miss_of_a_demo_it_skipped(monkeypatch, tmp_path):
    import json
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"volatile_misses": ["3"]}))
    monkeypatch.setattr(check_demos, "trace", lambda base, demo: {"exchange": None})
    monkeypatch.setattr("sys.argv", ["check_demos.py", "--only", "1", "--state", str(state)])
    assert check_demos.main() == 0
    assert json.loads(state.read_text()) == {"volatile_misses": ["3"]}
