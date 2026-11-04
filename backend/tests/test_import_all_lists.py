"""Tests for the nightly list refresh.

Two failures matter. A broken source must never replace a good list: a list that
quietly empties stops screening without anyone noticing. And a list that was
checked and has not changed must not go stale, or the report's warning cries wolf.

Dates are fixed and the importers are stand-ins, so nothing here reads the network.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app import config
from scripts import import_all_lists as lists
from scripts.import_all_lists import Family, reason_to_open, render_summary, run_family

from conftest import addr

TODAY = date(2026, 11, 3)
A, B, C = addr("a"), addr("b"), addr("c")


def document(reviewed: str, *addresses: str, source: str = "List, published 01/01/2026") -> dict:
    return {
        "_meta": {"last_reviewed": reviewed},
        "labels": {a: {"category": "sanctioned", "entity": f"Entity {a[-1]}", "label": "x", "source": source}
                   for a in addresses},
    }


def write(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc))


@pytest.fixture
def held(tmp_path) -> Path:
    path = tmp_path / "risk_labels.json"
    write(path, document("2026-11-02", A, B))
    return path


def family(*files: Path) -> Family:
    return Family("OFAC SDN list", "import_ofac_addresses", files)


def importer_writing(path: Path, doc: dict):
    def run(_family: Family) -> int:
        write(path, doc)
        return 0
    return run


# -- what counts as a change -----------------------------------------------------
def test_a_new_address_is_a_change_and_is_named_in_the_summary(held):
    outcome = run_family(family(held), importer_writing(held, document("2026-11-03", A, B, C)))
    assert outcome.status == "ok"
    assert outcome.changes[held].added == [C] and not outcome.changes[held].removed
    assert reason_to_open([outcome], TODAY) == "changed"
    assert C in render_summary([outcome], "changed")


def test_a_small_removal_is_allowed_and_named(tmp_path):
    path = tmp_path / "risk.json"
    many = [addr(f"{i:02x}") for i in range(1, 31)]
    write(path, document("2026-11-02", *many))
    outcome = run_family(family(path), importer_writing(path, document("2026-11-03", *many[1:])))
    assert outcome.status == "ok" and outcome.changes[path].removed == [many[0]]
    assert many[0] in render_summary([outcome], "changed")


def test_a_new_publication_date_in_every_source_is_not_a_change(held):
    """OFAC's source text carries its publish date, so it moves with no address moving."""
    newer = document("2026-11-03", A, B, source="List, published 11/02/2026")
    outcome = run_family(family(held), importer_writing(held, newer))
    assert outcome.status == "ok" and not outcome.changes[held].real


def test_an_address_recategorised_is_a_change(held):
    newer = document("2026-11-03", A, B)
    newer["labels"][A]["category"] = "mixer"
    outcome = run_family(family(held), importer_writing(held, newer))
    assert outcome.changes[held].altered == [A]
    assert reason_to_open([outcome], TODAY) == "changed"


# -- when a pull request opens ---------------------------------------------------
@pytest.mark.parametrize("reviewed, reason", [
    ("2026-11-02", None),        # checked yesterday, nothing moved: stay quiet
    ("2026-10-30", None),        # 4 days: still quiet
    ("2026-10-29", "dates"),     # 5 days: renew it before the report's 7-day warning
    ("2026-09-22", "dates"),
])
def test_an_unchanged_list_asks_for_a_pr_only_when_its_date_is_getting_old(tmp_path, reviewed, reason):
    path = tmp_path / "risk.json"
    write(path, document(reviewed, A, B))
    outcome = run_family(family(path), importer_writing(path, document("2026-11-03", A, B)))
    assert reason_to_open([outcome], TODAY) == reason


def test_a_list_with_no_date_counts_as_old(tmp_path):
    path = tmp_path / "risk.json"
    undated = document("", A)
    del undated["_meta"]
    write(path, undated)
    outcome = run_family(family(path), importer_writing(path, document("2026-11-03", A)))
    assert reason_to_open([outcome], TODAY) == "dates"


def test_when_no_pr_is_needed_the_files_go_back_exactly_as_they_were(held):
    before = held.read_bytes()
    outcome = run_family(family(held), importer_writing(held, document("2026-11-03", A, B)))
    assert held.read_bytes() != before
    lists.settle([outcome], None)
    assert held.read_bytes() == before


def test_when_a_pr_is_needed_the_new_files_stay(held):
    outcome = run_family(family(held), importer_writing(held, document("2026-11-03", A, B, C)))
    lists.settle([outcome], "changed")
    assert C in json.loads(held.read_text())["labels"]


# -- a broken source never replaces a good list ------------------------------------
def test_an_emptied_list_is_refused_and_restored(held):
    before = held.read_bytes()
    outcome = run_family(family(held), importer_writing(held, document("2026-11-03")))
    assert outcome.status == "refused" and "empty" in outcome.detail
    assert held.read_bytes() == before
    assert reason_to_open([outcome], TODAY) is None


def test_a_large_shrink_is_refused_and_restored(tmp_path):
    path = tmp_path / "risk.json"
    many = [addr(f"{i:02x}") for i in range(1, 31)]
    write(path, document("2026-11-02", *many))
    before = path.read_bytes()
    outcome = run_family(family(path), importer_writing(path, document("2026-11-03", *many[:20])))
    assert outcome.status == "refused"
    assert path.read_bytes() == before


def test_one_refused_file_restores_the_whole_family(tmp_path):
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    write(good, document("2026-11-02", A))
    write(bad, document("2026-11-02", B))
    before = good.read_bytes(), bad.read_bytes()

    def run(_family: Family) -> int:
        write(good, document("2026-11-03", A, C))
        write(bad, document("2026-11-03"))
        return 0

    assert run_family(family(good, bad), run).status == "refused"
    assert (good.read_bytes(), bad.read_bytes()) == before


def test_an_unreadable_result_is_refused_and_restored(held):
    before = held.read_bytes()

    def run(_family: Family) -> int:
        held.write_text("<html>rate limited</html>")
        return 0

    assert run_family(family(held), run).status == "refused"
    assert held.read_bytes() == before


def test_an_importer_that_crashes_partway_is_undone(held):
    before = held.read_bytes()

    def run(_family: Family) -> int:
        write(held, document("2026-11-03", A))
        return 1

    outcome = run_family(family(held), run)
    assert outcome.status == "failed"
    assert held.read_bytes() == before


def test_a_failed_list_does_not_stop_a_good_one_from_opening_a_pr(tmp_path, held):
    other = tmp_path / "frozen.json"
    write(other, document("2026-11-02", A))
    failed = run_family(family(held), lambda _family: 1)
    good = run_family(family(other), importer_writing(other, document("2026-11-03", A, C)))
    assert reason_to_open([failed, good], TODAY) == "changed"
    assert "failed" in render_summary([failed, good], "changed")


def test_an_importer_without_its_key_is_skipped_not_run(held, monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", None)
    needs_key = Family("Tether USDT freezes", "import_tether_freezes", (held,), needs=("ETHERSCAN_API_KEY",))

    def run(_family: Family) -> int:
        raise AssertionError("an importer with no key must not run")

    outcome = run_family(needs_key, run)
    assert outcome.status == "skipped" and "ETHERSCAN_API_KEY" in outcome.detail


def test_only_a_failure_or_a_refusal_turns_the_run_red(held, monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", None)
    skipped = run_family(Family("T", "m", (held,), needs=("ETHERSCAN_API_KEY",)), lambda _family: 0)
    refused = run_family(family(held), importer_writing(held, document("2026-11-03")))
    assert not lists.has_problem([skipped])
    assert lists.has_problem([skipped, refused])


# -- what the job runs and stages ----------------------------------------------------
def test_threat_and_exchange_lists_are_not_refreshed_nightly():
    """Both are pinned to a commit: re-running reads the same data, so a new date would be false."""
    modules = {f.module for f in lists.families()}
    assert modules == {"import_ofac_addresses", "import_intl_sanctions",
                       "import_tether_freezes", "port_evm_labels"}


def test_each_file_belongs_to_one_family_and_polygon_comes_after_its_sources():
    families = lists.families()
    files = [p for f in families for p in f.files]
    assert len(files) == len(set(files))
    assert [f.module for f in families][-1] == "port_evm_labels"


def test_the_workflow_stages_only_named_list_files():
    """Only the lists belong in this pull request, whatever else a run leaves in backend/."""
    text = (Path(__file__).resolve().parents[2] / ".github/workflows/refresh-lists.yml").read_text()
    assert "git add -- data/risk_labels*.json data/intl_sanctions*.json data/frozen_labels*.json" in text
    for careless in ("git add .", "git add -A", "git add --all", "git commit -a"):
        assert careless not in text
    assert "pull_request_target" not in text


def test_two_refresh_runs_never_race_to_the_same_branch():
    text = (Path(__file__).resolve().parents[2] / ".github/workflows/refresh-lists.yml").read_text()
    assert "concurrency:\n  group: refresh-lists\n  cancel-in-progress: false" in text
