"""A list the nightly refresh cannot run is not a quiet success.

Three families need an Etherscan key. Without it they came back 'skipped', and
a skip never turned the run red, so those lists (the Tron seizure orders, the
Tether freezes) could go stale with every night green (audit r1-ci-github-2).
Now a strict run (the nightly job) is red on any skip, any run is red once a
skipped list is past the reports' age limit, and each skip is a warning on the
run's page. The importers are stand-ins; nothing here reads the network.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app import config
from scripts import import_all_lists as lists
from scripts.import_all_lists import Family, run_family

from conftest import addr

TODAY = date(2026, 11, 6)


def held_list(path: Path, reviewed: str | None) -> Path:
    meta = {"last_reviewed": reviewed} if reviewed else {}
    path.write_text(json.dumps({"_meta": meta, "labels": {addr("a"): {"category": "frozen", "entity": "x"}}}))
    return path


def keyed(*files: Path) -> Family:
    return Family("Tether USDT freezes", "import_tether_freezes", files, needs=("ETHERSCAN_API_KEY",))


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", None)


def never_run(_family: Family) -> int:
    raise AssertionError("an importer with no key must not run")


def test_a_skipped_family_turns_a_strict_run_red(tmp_path):
    fresh = held_list(tmp_path / "frozen_labels.json", TODAY.isoformat())
    skipped = run_family(keyed(fresh), never_run)
    assert skipped.status == "skipped"
    assert lists.has_problem([skipped], strict=True, today=TODAY)
    assert not lists.has_problem([skipped], strict=False, today=TODAY)  # fresh, so a hand run can wait


@pytest.mark.parametrize("reviewed, red", [
    ((TODAY - timedelta(days=config.LIST_STALE_DAYS)).isoformat(), False),  # the limit itself is not over it
    ((TODAY - timedelta(days=config.LIST_STALE_DAYS + 1)).isoformat(), True),
    ("2026-09-23", True),  # today's shipped Tether files
    (None, True),  # a list that cannot say when it was checked
])
def test_a_skip_on_a_stale_list_is_red_even_without_strict(tmp_path, reviewed, red):
    skipped = run_family(keyed(held_list(tmp_path / "frozen_labels.json", reviewed)), never_run)
    assert lists.has_problem([skipped], today=TODAY) is red


def test_a_skip_whose_list_is_missing_is_red(tmp_path):
    skipped = run_family(keyed(tmp_path / "frozen_labels_tron.json"), never_run)
    assert skipped.reviewed == (None,)
    assert lists.has_problem([skipped], today=TODAY)


def test_one_stale_file_of_a_family_is_enough(tmp_path):
    skipped = run_family(keyed(held_list(tmp_path / "frozen_labels.json", TODAY.isoformat()),
                               held_list(tmp_path / "frozen_labels_tron.json", "2026-09-23")), never_run)
    assert lists.has_problem([skipped], today=TODAY)


def test_skips_are_warnings_and_failures_errors_on_the_run_page(tmp_path, monkeypatch, capsys):
    step_summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))
    skipped = run_family(keyed(held_list(tmp_path / "frozen_labels.json", "2026-09-23")), never_run)
    failed = lists.Outcome(Family("OFAC SDN list", "import_ofac_addresses", ()), "failed",
                           "the importer exited with code 2\nand 100% of it")
    lists.announce([skipped, failed], "the summary\n")
    printed = capsys.readouterr().out.splitlines()
    assert "::warning title=List skipped::Tether USDT freezes: ETHERSCAN_API_KEY is not set" in printed
    # One line each: a newline or % in a detail cannot start a second workflow command.
    assert "::error title=List not refreshed::OFAC SDN list: the importer exited with code 2%0Aand 100%25 of it" in printed
    assert step_summary.read_text() == "the summary\n"


def test_outside_github_actions_nothing_is_announced(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    skipped = run_family(keyed(held_list(tmp_path / "frozen_labels.json", "2026-09-23")), never_run)
    lists.announce([skipped], "the summary\n")
    assert capsys.readouterr().out == ""
