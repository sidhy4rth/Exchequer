"""A case records what its trace ran with, and its report says so.

Before (r2-g2-documented-claims-vs-code-7-3), every export was re-derived on
request: "Tool version" was the commit doing the rendering (the case stored
none), the letter's label-list date was read from today's file, and the
attribution kind came from today's rules. Two downloads of one case either side
of a deploy were two different signed documents that both verified. A trace now
stores its provenance -- the code, each list's date and hash, the settings --
and reports and letters are written from it; a case stored before that says so.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app import config, provenance, report as report_module
from app.models import Case
from app.report import attribution_kind, build_report, render_text_report
from app.request_letters import draft

from test_report import full_result, stored
from test_request_letters import case

DEMOS = {d["demo"]: d["result"] for d in json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "recorded_demos.json").read_text())}


def with_provenance(result: dict, **over) -> dict:
    out = copy.deepcopy(result)
    out["provenance"] = {**provenance.capture(result.get("chain") or "ethereum", follow_swaps=True,
                                              max_follow_ons=2, live_tags=False), **over}
    return out


# -- what a trace stores ---------------------------------------------------------------
def test_capture_records_the_code_the_lists_and_the_settings():
    p = provenance.capture("ethereum", follow_swaps=False, max_follow_ons=2, live_tags=False)
    assert p["tool_version"] == report_module.tool_version()
    labels = p["lists"]["labels_path"]
    assert labels["file"] == config.get_chain("ethereum").labels_path.name
    assert len(labels["sha256"]) == 64 and labels["meta"].get("last_reviewed")
    assert p["settings"]["follow_swaps"] is False and p["settings"]["max_follow_ons"] == 2


def test_a_trace_stores_its_provenance(monkeypatch):
    """Through the real pipeline with a fake provider: no network."""
    from app import pipeline
    from app.evidence import EvidenceLog

    class Empty:
        evidence = EvidenceLog()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_outgoing_transactions(self, address, limit=None):
            return []

        def get_incoming_transactions(self, address, limit=None):
            return []

        def close(self):
            pass

    monkeypatch.setattr(pipeline, "open_source", lambda chain, asset: Empty())
    result = pipeline.run_trace(pipeline.TraceRequest(address="0x" + "1" * 40, chain="ethereum"))
    assert result["provenance"]["tool_version"] == report_module.tool_version()
    assert result["provenance"]["settings"]["follow_swaps"] is True


# -- what the report says ----------------------------------------------------------------
def test_a_case_names_the_version_it_was_traced_with(monkeypatch):
    result = with_provenance(full_result(), tool_version="abc1234")
    monkeypatch.setattr(report_module, "_TOOL_VERSION", "def5678")
    text = render_text_report(build_report(stored(result)))
    assert "Traced with      : Exchequer abc1234" in text
    assert "Rendered with    : Exchequer def5678" in text
    assert build_report(stored(result))["traced_with"] == "abc1234"


def test_an_older_case_says_its_trace_version_was_not_recorded():
    text = render_text_report(build_report(stored(full_result())))
    assert "Traced with      : not recorded" in text


def test_lists_come_from_the_case_not_the_disk(monkeypatch):
    result = with_provenance(full_result())
    result["provenance"]["lists"]["labels_path"]["meta"]["last_reviewed"] = "2026-09-01"
    lists = build_report(stored(result))["screening_lists"]
    labels = next(entry for entry in lists["lists"] if entry["file"] == config.get_chain("ethereum").labels_path.name)
    assert labels["checked"] == "2026-09-01" and labels["state"] != "updated_since_trace"
    assert lists["recorded_at_trace"] is True
    assert "as recorded when this case was traced" in " ".join(render_text_report(build_report(stored(result))).split())


# -- the kind of attribution ---------------------------------------------------------------
def test_the_kind_comes_from_the_case_when_it_was_stored():
    result = case(matches=[{"address": case()["exchange_address"], "wallet_type": "hot_wallet"}])
    result["attribution"] = {"kind": "deposit_label", "source": "label_file", "address": result["exchange_address"]}
    assert attribution_kind(result) == "labelled_deposit"


@pytest.mark.parametrize("name", ["deposit_inferred", "exchange_wallet", "exchange_wallet.live_tag"])
def test_stored_and_derived_kinds_agree_on_every_contract_fixture(name):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "contract" / f"{name}.json").read_text())
    derived = attribution_kind({k: v for k, v in fixture.items() if k != "attribution"})
    assert attribution_kind(fixture) == derived


def test_a_disagreement_is_printed_and_the_stored_kind_is_used():
    result = full_result()
    result.update(attribution_inferred=False, matches=[{"address": result["exchange_address"],
                                                         "wallet_type": "hot_wallet"}])
    result["attribution"] = {"kind": "deposit_label", "source": "label_file", "address": result["exchange_address"]}
    text = render_text_report(build_report(Case(id="case-1", address=result["address"],
                                                created_at="2026-09-15T12:00:00+00:00",
                                                result_json=json.dumps(result))))
    assert "Kind recorded    : labelled deposit" in text and "exchange wallet" in text


# -- the letter --------------------------------------------------------------------------
def test_the_label_list_date_is_the_one_the_trace_used():
    result = with_provenance(case())
    result["provenance"]["lists"]["labels_path"]["meta"]["last_reviewed"] = "2026-09-01"
    result["matches"] = [{"address": result["exchange_address"], "wallet_type": "deposit_wallet"}]
    assert "last checked 2026-09-01" in draft("case-1", result, "exchange")


def test_an_older_case_letter_says_the_list_date_is_todays():
    result = case(matches=[{"address": case()["exchange_address"], "wallet_type": "deposit_wallet"}])
    assert "as held when this letter was drafted" in draft("case-1", result, "exchange")
