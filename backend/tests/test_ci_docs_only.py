"""A docs-only pull request skips the heavy CI jobs, and nothing else does.

test.yml's `changes` job pipes the paths a pull request changes into
.github/scripts/docs_only.sh. The jobs it gates are required checks on main,
so they must still start and report, and every one of their steps must be
gated: a step left ungated would fail on a runner with no checkout. These
tests read the files and run the script locally; nothing talks to GitHub.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "docs_only.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
GATE = "needs.changes.outputs.docs_only != 'true'"
NOTE = "needs.changes.outputs.docs_only == 'true'"
# Required on main (branch protection, 16 Nov 2026); each must keep its name.
REQUIRED = {"backend tests", "migrations on Postgres", "frontend tests + build",
            "docker image builds and runs as non-root", "commit e-mails",
            "accessibility (WCAG 2.2 AA)", "citizen site tests + build"}

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")


def docs_only(*paths: str) -> str:
    stdin = "".join(f"{p}\n" for p in paths)
    return subprocess.run(["bash", str(SCRIPT)], input=stdin, capture_output=True, text=True, check=True).stdout.strip()


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


@needs_bash
@pytest.mark.parametrize("paths", [
    ("docs/operations.md",),
    ("docs/handoff/ci-skip-heavy-jobs.md", "README.md"),
    ("docs/legal/freeze-wording-review.md", "docs/launch-video/v6/notes.txt", "JUDGE_QA.md"),
])
def test_documentation_alone_is_docs_only(paths):
    assert docs_only(*paths) == "true"


@needs_bash
@pytest.mark.parametrize("paths", [
    ("backend/app/config.py",),
    ("docs/operations.md", "backend/data/risk_labels.json"),
    ("README.md", ".github/workflows/test.yml"),
    ("docs/x.md", ".github/scripts/docs_only.sh"),
    ("Dockerfile",), ("render.yaml",), ("frontend/package.json",),
    ("backend/migrations/versions/0099_x.py",),
    # Markdown outside docs/ and the root can ship in the image or a build.
    ("backend/migrations/README.md",), ("frontend/public/notes.md",), (".github/pull_request_template.md",),
    ("notes.txt",), ("docs",),
    ('"docs/caf\\303\\251.md"',),  # quoted by git: do not guess
    (),  # nothing changed: test everything
])
def test_anything_else_runs_everything(paths):
    assert docs_only(*paths) == "false"


def test_the_required_checks_keep_their_names_and_the_workflow_runs_on_every_pull_request():
    flow = workflow()
    assert REQUIRED <= {job.get("name") for job in flow["jobs"].values()}
    on = flow[True]
    assert on["push"] == {"branches": ["main"]}
    # A paths filter would leave a required check pending forever.
    assert on["pull_request"] is None
    assert "paths" not in str(on) and "paths-ignore" not in str(on)


def test_the_changes_job_says_true_only_for_a_pull_request_merge_commit():
    job = workflow()["jobs"]["changes"]
    assert job["outputs"] == {"docs_only": "${{ steps.diff.outputs.docs_only }}"}
    (checkout, diff) = job["steps"]
    assert checkout["if"] == "github.event_name == 'pull_request'"
    assert checkout["with"]["persist-credentials"] is False and checkout["with"]["fetch-depth"] == 2
    run = diff["run"]
    assert "docs_only=false" in run.split("if ")[0]  # the default before anything is looked at
    assert '"$EVENT" = pull_request' in run and "HEAD^2" in run and "--no-renames" in run
    assert "docs_only.sh) || docs_only=false" in run and "${{" not in run


@pytest.mark.parametrize("job_id", ["migrations", "frontend", "a11y", "image"])
def test_a_gated_job_still_reports_and_gates_every_step(job_id):
    job = workflow()["jobs"][job_id]
    assert job["needs"] == "changes" and job["if"] == "${{ !cancelled() }}"
    (note, *steps) = job["steps"]
    assert note["if"] == NOTE and "uses" not in note
    for step in steps:
        assert step.get("if") in (GATE, "failure()"), (job_id, step)


def test_the_citizen_api_tests_always_run_and_only_its_npm_steps_are_gated():
    """citizen/api/tests reads docs/citizen-deploy.md."""
    job = workflow()["jobs"]["citizen"]
    assert job["needs"] == "changes" and job["if"] == "${{ !cancelled() }}"
    steps = job["steps"]
    pytest_at = next(i for i, s in enumerate(steps) if "pytest" in str(s.get("run", "")))
    assert all("if" not in s for s in steps[:pytest_at + 1])
    assert steps[pytest_at + 1]["if"] == NOTE
    assert all(s["if"] == GATE for s in steps[pytest_at + 2:])
    assert {"npm ci --ignore-scripts", "npm test", "npm run build"} <= {s.get("run") for s in steps[pytest_at + 2:]}


def test_backend_tests_and_commit_emails_are_never_gated():
    """Backend tests read docs/operations.md, DEMO.md and SECURITY.md and scan
    every tracked file for keys, so a docs change can fail them."""
    jobs = workflow()["jobs"]
    for job_id in ("backend", "emails"):
        assert "needs" not in jobs[job_id]
        assert not any("docs_only" in str(step.get("if", "")) for step in jobs[job_id]["steps"])
