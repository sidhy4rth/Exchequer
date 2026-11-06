"""What the GitHub workflows may run, and with what.

A workflow that names an action by a movable tag (actions/checkout@v7) runs
whatever that tag points to on the day; a re-pointed tag would run beside the
backup, demo and list-refresh secrets. A checkout that keeps its token in
.git/config hands it to every later step. These tests read the workflow files
only; nothing here talks to GitHub.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

PINNED = re.compile(r"^actions/[\w.-]+(/[\w.-]+)*@[0-9a-f]{40}$")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def all_steps():
    for path in WORKFLOWS:
        for job_id, job in load(path)["jobs"].items():
            for step in job.get("steps", []):
                yield path.name, job_id, step


def test_there_are_workflows_to_check():
    assert {"test.yml", "backup.yml", "demo-health.yml", "refresh-lists.yml", "site-canary.yml"} <= {
        p.name for p in WORKFLOWS}


def test_every_action_is_github_owned_and_pinned_to_a_commit():
    """r1-ci-github-8: a full commit SHA cannot be moved; only actions/* (GitHub's own) are used."""
    for name, job_id, step in all_steps():
        uses = step.get("uses")
        if uses:
            assert PINNED.match(uses), f"{name} {job_id}: {uses} is not an actions/* action pinned to a commit"


def test_every_pin_says_which_release_it_is():
    """Dependabot keeps SHA pins current and rewrites the version comment beside them."""
    for path in WORKFLOWS:
        for line in path.read_text().splitlines():
            if re.search(r"uses:\s*actions/", line):
                assert re.search(r"@[0-9a-f]{40} # v\d+(\.\d+)*$", line), f"{path.name}: {line.strip()}"


def test_checkouts_do_not_persist_the_token():
    """r1-ci-github-1/8: actions/checkout writes the job token into .git/config unless told not to."""
    for name, job_id, step in all_steps():
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert (step.get("with") or {}).get("persist-credentials") is False, f"{name} {job_id}"
