"""CI runs the backend suite and the accessibility check in shards, and the
required checks still mean "everything passed".

test.yml runs "backend tests" as three shards (tests/shards.py picks each
one's files) and "accessibility (WCAG 2.2 AA)" as four Playwright shards.
A job with each required name passes only when every shard passed. These
tests read the files; nothing talks to GitHub.
"""
from __future__ import annotations

import random
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import shards
import yaml

import conftest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
TESTS = Path(__file__).resolve().parent


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def test_files() -> set[Path]:
    return set(TESTS.glob("test_*.py"))


# -- the split ---------------------------------------------------------------------------
@pytest.mark.parametrize(("value", "want"), [(None, None), ("", None), ("1/3", (1, 3)), ("3/3", (3, 3)), ("1/1", (1, 1))])
def test_the_shard_setting_is_read_as_k_of_n(value, want):
    assert shards.parse(value) == want


@pytest.mark.parametrize("value", ["0/3", "4/3", "3", "a/3", "1/", "/3", "1/3/5", "-1/3", " 1/3"])
def test_a_malformed_shard_setting_stops_the_run(value):
    """Never a silent full or empty run."""
    with pytest.raises(ValueError):
        shards.parse(value)


@pytest.mark.parametrize("n", [1, 2, 3, 5])
def test_every_file_lands_in_exactly_one_shard_whatever_the_order(n):
    rng = random.Random(n)
    sizes = {f"test_{i}.py": rng.randint(1, 50_000) for i in range(40)}
    parts = shards.split(sizes, n)
    assert len(parts) == n
    assert set().union(*parts) == set(sizes)
    assert sum(len(p) for p in parts) == len(sizes)
    shuffled = dict(sorted(sizes.items(), key=lambda _: rng.random()))
    assert shards.split(shuffled, n) == parts  # every runner works out the same split


def test_the_shards_are_about_the_same_size():
    sizes = {f.name: f.stat().st_size for f in test_files()}
    loads = [sum(sizes[f] for f in part) for part in shards.split(sizes, 3)]
    assert max(loads) - min(loads) <= max(sizes.values())


def test_the_three_ci_shards_together_keep_every_test_file_once():
    files = test_files()
    kept = [shards.keep(files, f"{k}/3") for k in (1, 2, 3)]
    assert all(kept)
    assert set().union(*kept) == files
    assert sum(len(k) for k in kept) == len(files)


def test_unset_keeps_everything(monkeypatch):
    monkeypatch.delenv(shards.ENV, raising=False)
    assert shards.keep(test_files()) is None


def _collect(monkeypatch, value):
    files = sorted(test_files())[:12]
    items = [SimpleNamespace(path=f, name=f"{f.stem}::{i}") for f in files for i in range(2)]
    dropped = []
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=lambda items: dropped.extend(items)))
    if value is None:
        monkeypatch.delenv(shards.ENV, raising=False)
    else:
        monkeypatch.setenv(shards.ENV, value)
    before = list(items)
    conftest.pytest_collection_modifyitems(config, items)
    return before, items, dropped


def test_the_collection_hook_keeps_this_shards_tests_and_reports_the_rest(monkeypatch):
    every = []
    for k in (1, 2, 3):
        before, kept, dropped = _collect(monkeypatch, f"{k}/3")
        assert {id(i) for i in kept} | {id(i) for i in dropped} == {id(i) for i in before}
        assert not {id(i) for i in kept} & {id(i) for i in dropped}
        every += [i.name for i in kept]
    assert sorted(every) == sorted(i.name for i in before)


def test_the_collection_hook_stays_silent_outside_ci(monkeypatch):
    before, kept, dropped = _collect(monkeypatch, None)
    assert kept == before and dropped == []


# -- the workflow ------------------------------------------------------------------------
@pytest.mark.parametrize(("shard_job", "required", "variable"), [
    ("backend", "backend tests", "EXCHEQUER_TEST_SHARD"),
    ("a11y", "accessibility (WCAG 2.2 AA)", "SHARD"),
])
def test_each_shard_runs_its_part_and_one_required_check_needs_them_all(shard_job, required, variable):
    jobs = workflow()["jobs"]
    job = jobs[shard_job]
    matrix = job["strategy"]["matrix"]["shard"]
    assert job["strategy"]["fail-fast"] is False
    assert matrix == list(range(1, len(matrix) + 1)) and len(matrix) >= 2
    assert job["name"] == f"{'backend' if shard_job == 'backend' else 'accessibility'} shard ${{{{ matrix.shard }}}} of {len(matrix)}"
    settings = [s["env"][variable] for s in job["steps"] if variable in (s.get("env") or {})]
    assert settings == [f"${{{{ matrix.shard }}}}/{len(matrix)}"]
    if shard_job == "a11y":
        (run,) = [s["run"] for s in job["steps"] if "npm run a11y" in str(s.get("run", ""))]
        assert run == 'npm run a11y -- --shard="$SHARD"'

    (agg_id,) = [i for i, j in jobs.items() if j.get("name") == required]
    agg = jobs[agg_id]
    assert agg["needs"] == shard_job and agg["if"] == "${{ !cancelled() }}"
    (step,) = agg["steps"]
    assert step["env"] == {"RESULT": f"${{{{ needs.{shard_job}.result }}}}"}
    assert step["run"] == 'test "$RESULT" = success'
    assert "uses" not in yaml.safe_dump(agg) and not agg.get("continue-on-error")


def test_the_backend_shards_lint_once_and_test_everywhere():
    steps = workflow()["jobs"]["backend"]["steps"]
    (pytest_step,) = [s for s in steps if "pytest" in str(s.get("run", ""))]
    assert "if" not in pytest_step and pytest_step["run"] == "python -m pytest -p no:warnings"
    for command in ("ruff check app scripts tests migrations", "python scripts/check_fiu_staleness.py"):
        (step,) = [s for s in steps if s.get("run") == command]
        assert step["if"] == "matrix.shard == 1"
    assert re.search(r"pytest_collection_modifyitems", (TESTS / "conftest.py").read_text())


def test_the_accessibility_tests_run_side_by_side_so_the_shards_are_even():
    config = (ROOT / "frontend" / "playwright.a11y.config.js").read_text()
    assert re.search(r"^\s*fullyParallel: true,$", config, re.M)
