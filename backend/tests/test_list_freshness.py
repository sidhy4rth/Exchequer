"""Tests for the list dates a report prints, and its warning when a list was old.

"No address matched" means little if the list was months old when the case was
traced, so the report says how old each list was. Age is measured at the trace,
not at the export: re-exporting a well-screened case must not turn it red, and a
refresh today must not make a stale screening look fresh.

Dates are fixed and the lists are temporary files, so nothing depends on today.
"""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from app import config, risk_matcher
from app.report import build_report, render_text_report
from app.risk_matcher import is_stale, list_freshness

from test_label_store import FIELDS, ROWS
from test_report import full_result, stored

TRACED = date(2026, 9, 15)  # the day test_report's stored() case was traced
FRESH, OLD, AFTER = "2026-09-14", "2026-08-01", "2026-10-01"


@pytest.fixture
def lists_dated(tmp_path, monkeypatch):
    """A chain whose list files carry the given dates; None means it has no such file."""
    def make(key="ethereum", ofac=FRESH, intl=FRESH, frozen=FRESH, threat=OLD, labels=OLD, **ofac_meta):
        def file(name, reviewed, **meta):
            if reviewed is None:
                return None
            path = tmp_path / f"{key}_{name}.json"
            path.write_text(json.dumps({"_meta": {"last_reviewed": reviewed, **meta}, "labels": {}}))
            return path

        chain = SimpleNamespace(
            key=key,
            risk_labels_path=file("risk", ofac, **ofac_meta),
            intl_sanctions_path=file("intl", intl),
            frozen_labels_path=file("frozen", frozen),
            threat_labels_path=file("threat", threat),
            labels_path=file("labels", labels),
        )
        monkeypatch.setattr(config, "get_chain", lambda _key=None: chain)
        return chain
    return make


def entry(freshness: dict, name: str) -> dict:
    return next(e for e in freshness["lists"] if e["name"].startswith(name))


# -- is_stale: yours to write in app/risk_matcher.py ------------------------------
@pytest.mark.parametrize("list_date, expected", [
    (date(2026, 9, 15), False),   # checked that same day
    (date(2026, 9, 8), False),    # exactly 7 days old: not yet "over 7 days"
    (date(2026, 9, 7), True),     # 8 days old
    (date(2026, 1, 1), True),     # months old
    (date(2026, 10, 1), False),   # newer than the day being asked about
    (None, True),                 # a list that cannot say when it was checked gets no benefit of the doubt
])
def test_is_stale(list_date, expected):
    assert is_stale(list_date, TRACED) is expected


# -- what each list reports --------------------------------------------------------
def test_a_list_checked_recently_gives_no_warning(lists_dated):
    lists_dated()
    freshness = list_freshness("ethereum", TRACED)
    assert entry(freshness, "OFAC")["state"] == "current"
    assert freshness["warning"] is None


def test_an_old_list_is_named_with_its_date_and_a_fresh_one_is_not(lists_dated):
    lists_dated(ofac=OLD)
    warning = list_freshness("ethereum", TRACED)["warning"]
    assert "OFAC SDN list (checked 2026-08-01)" in warning
    assert "Tether" not in warning


def test_a_list_with_no_date_is_warned_about(tmp_path, lists_dated):
    chain = lists_dated()
    chain.frozen_labels_path.write_text(json.dumps({"_meta": {}, "labels": {}}))
    chain.frozen_labels_path = chain.frozen_labels_path.rename(tmp_path / "undated.json")
    assert "Tether USDT freezes (no date recorded)" in list_freshness("ethereum", TRACED)["warning"]


def test_ofacs_american_date_is_printed_unambiguously(lists_dated):
    """09/10/2026 is 10 September to OFAC and reads as 9 October in India."""
    lists_dated(ofac_publish_date="09/10/2026")
    assert entry(list_freshness("ethereum", TRACED), "OFAC")["published"] == "2026-09-10"


def test_a_list_newer_than_the_trace_says_the_trace_used_an_earlier_one(lists_dated):
    lists_dated(ofac=AFTER)
    freshness = list_freshness("ethereum", TRACED)
    assert entry(freshness, "OFAC")["state"] == "updated_since_trace"
    assert "earlier version" in entry(freshness, "OFAC")["note"]
    assert freshness["warning"] is None


def test_pinned_lists_show_their_date_but_never_warn(lists_dated):
    """Re-running them reads the same data, so a warning could never clear."""
    lists_dated(threat="2020-01-01", labels="2020-01-01")
    freshness = list_freshness("ethereum", TRACED)
    assert entry(freshness, "Mixer")["state"] == entry(freshness, "Exchange")["state"] == "fixed_snapshot"
    assert entry(freshness, "Mixer")["checked"] == "2020-01-01"
    assert freshness["warning"] is None


def test_a_chain_without_a_list_says_so(lists_dated):
    lists_dated(intl=None, frozen=None, threat=None)
    freshness = list_freshness("polygon", TRACED)
    assert any(name.startswith("Tether") for name in freshness["not_held"])
    assert all(not e["name"].startswith("Tether") for e in freshness["lists"])


def test_an_unreadable_list_counts_as_not_held_rather_than_breaking_the_report(lists_dated):
    chain = lists_dated()
    chain.frozen_labels_path.write_text("<html>not a list</html>")
    risk_matcher._list_meta.cache_clear()
    assert any(name.startswith("Tether") for name in list_freshness("ethereum", TRACED)["not_held"])


def test_the_real_lists_all_carry_a_date_and_only_their_own_chain_claims_them():
    freshness = {key: list_freshness(key, date(2030, 1, 1)) for key in config.CHAINS}
    assert all(e["checked"] for f in freshness.values() for e in f["lists"])
    named = lambda key: " ".join(e["name"] for e in freshness[key]["lists"])  # noqa: E731
    assert "Tether" in named("tron") and "Mixer" not in named("tron")
    assert "Tether" not in named("polygon") and "carried over from Ethereum" in named("polygon")


# -- what the report says ----------------------------------------------------------
def test_the_text_report_prints_each_lists_date(lists_dated):
    lists_dated(ofac_publish_date="09/10/2026")
    text = render_text_report(build_report(stored(full_result())))
    assert "LISTS SCREENED AGAINST" in text
    assert "checked 2026-09-14, published 2026-09-10" in text
    assert "WARNING" not in text


def test_an_old_list_puts_a_warning_above_the_summary(lists_dated):
    lists_dated(ofac=OLD)
    text = render_text_report(build_report(stored(full_result())))
    flat = " ".join(text.split())
    assert text.index("WARNING") < text.index("SUMMARY")
    assert "OFAC SDN list (checked 2026-08-01)" in flat
    assert "Over 7 days old when this case was traced" in flat


def test_age_is_measured_at_the_trace_not_the_export(lists_dated):
    """Traced 2026-09-15 with a list from the day before: fine, whenever it is exported."""
    lists_dated(ofac=FRESH)
    report = build_report(stored(full_result()))
    assert report["screening_lists"]["as_of"] == "2026-09-15"
    assert report["screening_lists"]["warning"] is None


def test_no_match_no_longer_claims_lists_the_chain_does_not_have(lists_dated):
    lists_dated(key="polygon", intl=None, frozen=None, threat=None)
    flat = " ".join(render_text_report(build_report(stored(full_result()))).split())
    assert "No address in this trace appeared on the screened lists" in flat
    for not_on_polygon in ("Israeli", "Japanese", "USDT freeze list", "hack or phishing"):
        assert not_on_polygon not in flat
    assert "Not loaded for this chain, so not screened: Other governments' sanctions lists" in flat


def test_a_chain_this_build_does_not_know_still_renders(monkeypatch):
    def unknown(_key=None):
        raise config.UnknownChainError("Unsupported chain")

    monkeypatch.setattr(config, "get_chain", unknown)
    report = build_report(stored(full_result()))
    assert report["screening_lists"] is None
    assert "could not be determined" in render_text_report(report)


def test_the_stale_warning_says_listings_may_have_been_lifted(lists_dated):
    """A stale list misses new listings and may still name lifted ones (r1-labels-data-3)."""
    lists_dated(intl=OLD)
    warning = list_freshness("ethereum", TRACED)["warning"]
    assert "may still name addresses whose listing has since been lifted" in warning
    assert "Other governments' sanctions lists and seizure orders (checked 2026-08-01)" in warning


def test_a_list_says_how_many_of_its_orders_had_ended_by_the_trace(lists_dated):
    """An order past its valid_until is not matched; the report says how many were left out (r1-labels-data-3)."""
    chain = lists_dated()
    labels = {f"T{c * 33}": {"category": "seized", "entity": "NBCTF 1", "valid_until": until}
              for c, until in (("A", "2026-09-01"), ("B", "2026-09-14"), ("C", "2026-09-15"), ("D", None))}
    chain.intl_sanctions_path.write_text(json.dumps({"_meta": {"last_reviewed": FRESH}, "labels": labels}))
    risk_matcher.clear_label_caches()
    intl = entry(list_freshness("ethereum", TRACED), "Other governments")
    assert intl["lapsed"] == 2  # 1 and 14 September; the 15th was still its last day
    assert "2 listings in it had ended by 2026-09-15 and were not matched" in intl["note"]
    assert entry(list_freshness("ethereum", TRACED), "OFAC")["lapsed"] == 0
    flat = " ".join(render_text_report(build_report(stored(full_result()))).split())
    assert "2 listings in it had ended by 2026-09-15" in flat


# -- every source a trace screens against is named (audit r1-labels-data-9) --------
STORE = "Flagged-address label store"


def _build(tmp_path, rows):
    """A label store built from `rows` the way a release is (scripts/build_label_store.py)."""
    import csv

    from scripts.build_label_store import build

    src = tmp_path / "new_flagged.csv"
    with open(src, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    build(src, tmp_path / "label_store.db")
    return tmp_path / "label_store.db"


@pytest.fixture
def held_store(monkeypatch, tmp_path):
    """The server holds a small label store (rows on Ethereum and Arbitrum only)."""
    from app.label_store import LabelStore

    store = LabelStore(_build(tmp_path, ROWS))  # 2 rows on Ethereum, 1 on Arbitrum
    monkeypatch.setattr(risk_matcher, "get_label_store", lambda: store)
    return store


def test_the_gambling_list_is_named():
    freshness = list_freshness("ethereum", date(2030, 1, 1))
    gambling = entry(freshness, "Gambling platform wallets")
    assert gambling["file"] == "gambling_labels.json" and gambling["state"] == "fixed_snapshot"


def test_without_the_label_store_it_is_named_as_not_screened():
    assert STORE in list_freshness("ethereum", TRACED)["not_held"]


def test_the_label_store_is_listed_with_its_build_and_rows(held_store):
    freshness = list_freshness("ethereum", date(2030, 1, 1))
    store = entry(freshness, STORE)
    assert store["file"] == "label_store.db" and store["rows"] == 2
    assert store["built_from"] == "new_flagged.csv" and store["checked"] == store["built_at"][:10]
    assert "2 addresses on this chain" in store["note"]
    assert STORE not in freshness["not_held"]


def test_the_store_records_the_release_the_image_was_built_with(held_store, monkeypatch):
    """The Dockerfile bakes the release tag it fetched into EXCHEQUER_LABEL_STORE_TAG."""
    monkeypatch.setenv("EXCHEQUER_LABEL_STORE_TAG", "labels-2026-11-05b")
    recorded = risk_matcher.label_store_entry(held_store, "ethereum")
    assert recorded["release"] == "labels-2026-11-05b"
    store = entry(list_freshness("ethereum", TRACED, store=recorded), STORE)
    assert store["release"] == "labels-2026-11-05b" and "Release labels-2026-11-05b, built" in store["note"]
    monkeypatch.delenv("EXCHEQUER_LABEL_STORE_TAG")
    assert risk_matcher.label_store_entry(held_store, "ethereum")["release"] is None
    assert entry(list_freshness("ethereum", TRACED), STORE)["note"].startswith("Built ")


def test_a_store_with_nothing_for_the_chain_is_not_screened_on_it(held_store):
    assert STORE in list_freshness("polygon", date(2030, 1, 1))["not_held"]


def test_the_store_the_trace_recorded_is_named_not_todays(held_store):
    recorded = {"name": STORE, "file": "label_store.db", "built_at": "2026-09-01T10:00:00",
                "built_from": "old_flagged.csv", "rows": 7}
    store = entry(list_freshness("ethereum", TRACED, store=recorded), STORE)
    assert (store["checked"], store["rows"]) == ("2026-09-01", 7)
    assert "Recorded when this case was traced" in store["note"]
    # Traced without one: not screened, although this server holds one now.
    assert STORE in list_freshness("ethereum", TRACED, store=None)["not_held"]


def test_the_report_names_the_store_its_trace_used():
    recorded = {"name": STORE, "file": "label_store.db", "built_at": "2026-09-01T10:00:00",
                "built_from": "new_flagged.csv", "rows": 7}
    flat = " ".join(render_text_report(build_report(stored({**full_result(), "label_store": recorded}))).split())
    assert f"{STORE} label_store.db: checked 2026-09-01" in flat
    without = " ".join(render_text_report(build_report(stored({**full_result(), "label_store": None}))).split())
    assert "so not screened:" in without and STORE in without.split("so not screened:")[1]
