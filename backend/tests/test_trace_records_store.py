"""A trace records the label store it screened against, or that it had none (audit r1-labels-data-9).

The store is replaced with each release, so a report rendered later cannot tell
which build made, or missed, a 'Reported scam' finding unless the trace wrote it down.
"""
from __future__ import annotations

from app import pipeline
from app.label_store import LabelStore
from app.risk_matcher import RiskMatcher

from test_attribution_by_share import BASE, trace  # noqa: F401 -- the fixture
from test_label_store import ROWS
from test_list_freshness import _build


def test_a_trace_without_the_store_records_none(trace):  # noqa: F811
    assert trace(BASE)["label_store"] is None


def test_a_trace_records_the_store_build_it_screened_against(trace, monkeypatch, tmp_path):  # noqa: F811
    store = LabelStore(_build(tmp_path, ROWS))
    monkeypatch.setattr(pipeline, "get_risk_matcher", lambda key=None: RiskMatcher({}, chain="ethereum", store=store))
    recorded = trace(BASE)["label_store"]
    assert recorded["file"] == "label_store.db" and recorded["rows"] == 2
    assert recorded["built_from"] == "new_flagged.csv" and recorded["built_at"]
