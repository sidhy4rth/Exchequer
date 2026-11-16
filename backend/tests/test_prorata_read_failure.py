"""A pro-rata window read the provider refused: read once more, then say so.

Found on a re-run of demo 3 (16 Nov): the provider answered HTTP 429 for about
ten minutes, the one window read pro-rata needs failed, the amount component
fell to 0 and the score from 0.6688 to 0.425, and nothing said that a rate
limit, not the money, had lowered it. Now a read refused for a passing reason
is made once more within the case's clock; if it still fails the case flags
it (`prorata.read_failure`) and says so in the score, the limitations, the
signed report and the letter draft. The arithmetic is unchanged (ADR-0007: an
amount that could not be measured earns no credit), and a read that succeeds
gives the same case, byte for byte.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import httpx
import networkx as nx
import pytest

from app import api_budget, pipeline, provider_errors, request_letters
from app.api_budget import TraceBudget
from app.etherscan_client import (EtherscanClient, EtherscanError, EtherscanRateLimitError, ProviderQuotaError,
                                  ProviderResponseError, ProviderUnavailableError, Transaction)
from app.exchange_matcher import ExchangeMatch
from app.models import Case
from app.prorata import estimate
from app.provider_errors import failure_kind, read_again_once
from app.report import build_report, render_text_report
from app.scoring import score_case
from app.tracing_methods import read_once
from conftest import addr

DATA = Path(__file__).resolve().parent.parent / "data"
DEMO3 = next(d["result"] for d in json.loads((DATA / "recorded_demos.json").read_text()) if d["demo"] == 3)
NOTE = ("The amount check could not be done: the data provider did not answer (rate limit). The confidence score "
        "gives the amount no credit; trace again later for a complete score.")

# Etherscan's txlist answer for demo 3's intermediate wallet over its window
# (blocks 13674284-13674291), as recorded by a live re-run of demo 3 on
# 16 Nov 2026 (the rows the client keeps; the hashes are on chain). It is the
# read behind the recorded case's pro-rata hop: 1.0626 + 0.4596 ETH in.
WINDOW_ROWS = [
    {"hash": "0xe60a0d2bdc1a96c619ba9d6e061f845bd0eba7e1b53e37291eb1f332f0338502",
     "from": "0x0067b43cb530e683dbffb43f5caacde867472721", "to": "0x1930f9dfc8f28913a8ce7365a547fac16330f811",
     "value": "1062600000000000000", "timeStamp": "1637716910", "blockNumber": "13674284", "isError": "0",
     "contractAddress": ""},
    {"hash": "0xb8a183ce826a0a2db6b535de6b98d781d6db7282c3b60a105b8397c13db93b70",
     "from": "0xa4f0294dd195f97ebdd166cc2f71a3af21d22fac", "to": "0x1930f9dfc8f28913a8ce7365a547fac16330f811",
     "value": "459600000000000000", "timeStamp": "1637717012", "blockNumber": "13674291", "isError": "0",
     "contractAddress": ""},
    {"hash": "0x5fbed67e123e53ef593abb68b2b56d07e84ff489c2f66460579311e8365c5bf6",
     "from": "0x1930f9dfc8f28913a8ce7365a547fac16330f811", "to": "0x4a1265873468a63a9710a3185fdcff7154a2c50c",
     "value": "1060448566039506000", "timeStamp": "1637717012", "blockNumber": "13674291", "isError": "0",
     "contractAddress": ""},
]


class Clock:
    """A case clock that moves only when the case waits: no test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class CaseBudget(TraceBudget):
    def sleep(self, seconds: float) -> None:
        if seconds >= self.remaining():
            raise api_budget.DeadlineReached()
        self._clock.now += seconds


def budget(walk: float = 180.0, grace: float = 60.0) -> CaseBudget:
    return CaseBudget(walk, grace, clock=Clock())


def demo3_path() -> tuple[nx.DiGraph, list[str]]:
    """Demo 3's route, rebuilt from its recorded transfers."""
    path = [step["address"] for step in DEMO3["trace_path"]]
    g = nx.DiGraph()
    for src, dst in zip(path, path[1:], strict=False):
        txs = [{"hash": t["hash"], "value_native": t["value_native"], "block_number": t["block"],
                "timestamp": t["timestamp"]} for t in DEMO3["transfers"] if t["from"] == src and t["to"] == dst]
        g.add_edge(src, dst, value_native=sum(t["value_native"] for t in txs), transactions=txs)
    return g, path


def replaying(refusals: int):
    """An Etherscan client that refuses the first `refusals` requests with
    HTTP 429, then answers with the recorded window."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= refusals:
            return httpx.Response(429, json={"message": "Too many requests", "result": None, "status": "0"})
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": WINDOW_ROWS})

    client = EtherscanClient(api_key="test-key", chain_id=1, min_interval=0.0,
                             client=httpx.Client(transport=httpx.MockTransport(handler)))
    client._throttle = lambda: None  # the shared pacer widens on each 429, in real seconds
    return client, calls


def prorata_with(refusals: int):
    api_budget.reset()  # each run reads afresh, never from the last one's cache
    client, calls = replaying(refusals)
    client.budget = budget()
    g, path = demo3_path()
    flows = read_once(read_again_once(client.get_flows_between, client.budget))
    return estimate(g, path, client.get_incoming_between, flows_between=flows), calls["n"]


# --- the recorded read -------------------------------------------------------------

def test_a_read_that_succeeds_gives_the_recorded_estimate_unchanged():
    result, requests = prorata_with(refusals=0)
    assert requests == 1
    assert json.dumps(result, sort_keys=True) == json.dumps(DEMO3["prorata"], sort_keys=True)


def test_refused_then_answered_gives_the_same_estimate_byte_for_byte():
    # Five refusals use up the client's own retries; the one re-read gets the answer.
    result, requests = prorata_with(refusals=5)
    assert requests == 6
    assert json.dumps(result, sort_keys=True) == json.dumps(DEMO3["prorata"], sort_keys=True)
    assert "read_failure" not in result


def test_refused_throughout_is_flagged_after_exactly_one_re_read():
    result, requests = prorata_with(refusals=10**6)
    assert requests == 10  # the client's five attempts, twice: bounded
    assert result["status"] == "unknown" and result["read_failure"] == "rate_limit"
    assert "could not be read" in result["reason"]


def test_no_re_read_when_the_case_has_no_time_for_it(monkeypatch):
    reads = []

    def refused(*window):
        reads.append(window)
        raise ProviderUnavailableError("HTTP 429", rate_limited=True)
    short = budget(walk=0.0, grace=provider_errors.REREAD_PAUSE_SECONDS + 1)
    with pytest.raises(ProviderUnavailableError):
        read_again_once(refused, short)(1, 2, 3, 4, 5)
    assert len(reads) == 1 and short.stopped_by is None  # the clock was never run into


@pytest.mark.parametrize("exc", [ProviderQuotaError("x"), ProviderResponseError("x"), EtherscanError("x"),
                                 api_budget.DeadlineReached(), ValueError("x")])
def test_only_a_passing_failure_is_read_again(exc):
    reads = []

    def failing(*window):
        reads.append(window)
        raise exc
    with pytest.raises(type(exc)):
        read_again_once(failing, budget())(1, 2, 3, 4, 5)
    assert len(reads) == 1


def test_each_failure_has_its_kind():
    assert failure_kind(ProviderUnavailableError("x", rate_limited=True)) == "rate_limit"
    assert failure_kind(ProviderUnavailableError("x")) == "no_answer"
    assert failure_kind(EtherscanRateLimitError("x")) == "rate_limit"
    assert failure_kind(ProviderQuotaError("x")) == "quota"
    assert failure_kind(api_budget.DeadlineReached()) == "stopped"
    assert failure_kind(ProviderResponseError("x")) == "bad_response"
    assert failure_kind(EtherscanError("x")) == "provider_error"
    assert failure_kind(ValueError("x")) == "error"


def test_a_client_out_of_retries_says_whether_it_was_refused():
    for status, refused in ((429, True), (503, False)):
        api_budget.reset()
        client = EtherscanClient(api_key="k", chain_id=1, min_interval=0.0, client=httpx.Client(
            transport=httpx.MockTransport(lambda r, s=status: httpx.Response(s))))
        client.budget, client._throttle = budget(), lambda: None
        with pytest.raises(ProviderUnavailableError) as raised:
            client.get_flows_between(addr("a"), 1, 2, 0, 0)
        assert raised.value.rate_limited is refused


# --- what the case says ------------------------------------------------------------

def _scored(prorata):
    g, path = demo3_path()
    lead = ExchangeMatch(address=path[-1], exchange="HitBTC", label="probable HitBTC deposit address",
                         wallet_type="inferred_deposit", depth=len(path) - 1, value_received_native=1.060449,
                         evidence={"sweep_count": 4, "sweep_destination": addr("b")})
    return score_case(g, path[0], lead, prorata=prorata)


def test_the_score_is_unchanged_and_the_failure_is_said():
    failed, _ = prorata_with(refusals=10**6)
    plain = {k: v for k, v in failed.items() if k != "read_failure"}
    flagged, quiet = _scored(failed), _scored(plain)
    assert flagged.score == quiet.score  # ADR-0007: no credit, as before
    amount = next(c for c in flagged.components if c.name == "amount_correlation")
    assert amount.raw_value == 0.0 and amount.explanation.endswith(NOTE)
    at = flagged.caveats.index(NOTE)  # just before the "could not be estimated" limitation
    assert flagged.caveats[:at] + flagged.caveats[at + 1:] == quiet.caveats
    assert flagged.caveats[at + 1].startswith("How much of the value at the exchange")
    assert NOTE not in str(quiet.caveats) and NOTE not in str(quiet.components)


def test_a_path_that_could_not_be_read_in_full_says_nothing_of_a_provider():
    g, path = demo3_path()
    too_many = estimate(g, path, None, flows_between=lambda *w: ([], [], False))
    assert "read_failure" not in too_many
    assert "amount check could not be done" not in str(_scored(too_many).caveats)


# --- end to end: the case, its signed report and the letter --------------------------

SEED, MID = addr("5eed"), addr("a1")
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"  # data/exchange_labels.json
T = 1_700_000_000


def _tx(n, src, dst, value, when):
    return Transaction(hash="0x" + f"{n:064x}", from_address=src, to_address=dst, value_native=value,
                       value_wei=int(value * 1e18), timestamp=when, block_number=when // 12, is_error=False,
                       asset="ETH")


HISTORY = [_tx(1, SEED, MID, 5.0, T + 12), _tx(2, MID, BINANCE_14, 5.0, T + 24)]


@pytest.fixture
def trace(monkeypatch):
    monkeypatch.setattr(provider_errors, "REREAD_PAUSE_SECONDS", 0.01)

    def run(refusals):
        reads = []

        class Fake:
            def get_outgoing_transactions(self, address, limit=None):
                return [t for t in HISTORY if t.from_address == address]

            def get_flows_between(self, address, *window):
                reads.append(address)
                if address == MID and len([a for a in reads if a == MID]) <= refusals:
                    raise ProviderUnavailableError("Etherscan returned HTTP 429", rate_limited=True)
                return ([t for t in HISTORY if t.to_address == address],
                        [t for t in HISTORY if t.from_address == address], True)

        @contextmanager
        def open_source(chain, asset):
            yield Fake()
        monkeypatch.setattr(pipeline, "open_source", open_source)
        monkeypatch.setattr(pipeline, "detect_swaps", lambda *a, **k: [])
        r = pipeline.run_trace(pipeline.TraceRequest(address=SEED, chain="ethereum", asset="ETH", max_depth=3,
                                                     follow_swaps=False))
        return r, reads.count(MID)
    return run


def _stable(r):
    """The case without what differs between any two runs: its id and clock."""
    drop = {"case_id", "created_at", "seconds_elapsed", "provenance"}
    return json.dumps({k: v for k, v in r.items() if k not in drop}, sort_keys=True, default=str)


def test_one_refusal_then_an_answer_gives_the_same_case(trace):
    answered, once = trace(refusals=0)
    retried, twice = trace(refusals=1)
    assert (once, twice) == (1, 2)
    assert answered["prorata"]["status"] == "estimated"
    assert _stable(retried) == _stable(answered)


def test_refused_throughout_the_case_report_and_letter_say_so(trace):
    r, reads = trace(refusals=10**6)
    assert reads == 2
    assert r["prorata"]["status"] == "unknown" and r["prorata"]["read_failure"] == "rate_limit"
    assert NOTE in r["confidence_detail"]["caveats"]
    amount = next(c for c in r["confidence_detail"]["components"] if c["name"] == "amount_correlation")
    assert amount["explanation"].endswith(NOTE)

    text = render_text_report(build_report(Case(id="c1", address=SEED, created_at="2026-11-16T00:00:00+00:00",
                                                result_json=json.dumps(r))))
    flat = " ".join(text.split())
    assert flat.count("The amount check could not be done: the data provider did not answer (rate limit).") == 2

    letter = " ".join(request_letters.draft("c1", r, request_letters.EXCHANGE).split())
    assert ("[Officer: the amount could not be estimated: the data provider did not answer (rate limit). "
            "Trace again later for an estimate, or state the amount from your own records.]") in letter


def test_an_answered_case_carries_no_note(trace):
    r, _ = trace(refusals=0)
    text = render_text_report(build_report(Case(id="c1", address=SEED, created_at="2026-11-16T00:00:00+00:00",
                                                result_json=json.dumps(r))))
    assert "amount check could not be done" not in text and "read_failure" not in r["prorata"]
    assert "could not be estimated" not in request_letters.draft("c1", r, request_letters.EXCHANGE)


def test_the_trace_screen_uses_the_same_read_failure_wording():
    # frontend/src/components/case/readFailureWording.js mirrors
    # READ_FAILURE_WORDING (#322); if one changes without the other, the trace
    # screen and the report word the same failure differently.
    import re

    from app.prorata import READ_FAILURE_WORDING

    js = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "case"
          / "readFailureWording.js").read_text()
    block = js.split("export const READ_FAILURE_WORDING = {", 1)[1].split("}", 1)[0]
    pairs = re.findall(r"^\s*([a-z_]+): (?:'([^']*)'|\"([^\"]*)\"),$", block, re.M)
    assert {key: single or double for key, single, double in pairs} == READ_FAILURE_WORDING
