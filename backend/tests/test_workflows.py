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


# -- secrets (r1-ci-github-7) and the backup (r1-ci-github-5) ---------------------------
# Each environment is set to deploy from main only (Settings -> Environments), so
# a pushed branch or a dispatch from one never receives its secrets.
LOCKED = {"backup", "live-checks", "lists", "list-publish"}
SECRET = re.compile(r"secrets\.(\w+)")


def jobs():
    for path in WORKFLOWS:
        for job_id, job in load(path)["jobs"].items():
            yield path.name, job_id, job


def test_secrets_reach_only_branch_locked_jobs_and_only_the_steps_that_use_them():
    for name, job_id, job in jobs():
        used = {s for s in SECRET.findall(yaml.safe_dump(job)) if s != "GITHUB_TOKEN"}
        if not used:
            continue
        assert job.get("environment") in LOCKED, f"{name} {job_id} reads {sorted(used)} outside an environment"
        assert not SECRET.findall(yaml.safe_dump(job.get("env") or {})), f"{name} {job_id}: a secret in job-level env"


def backup_steps() -> list[dict]:
    return load(ROOT / ".github" / "workflows" / "backup.yml")["jobs"]["backup"]["steps"]


def test_the_backup_log_never_prints_what_the_store_holds():
    """A public repository's logs are world-readable: no counts, no rows."""
    text = "\n".join(s.get("run", "") for s in backup_steps())
    for leak in ("count(", "SELECT", "wc ", "sqlite3", "echo \"cases"):
        assert leak not in text, leak


def test_the_backup_encrypts_to_the_recipient_pinned_outside_the_repo():
    """The committed recipient file can be changed by any merged PR; the environment's variable cannot."""
    runs = {s.get("name"): s.get("run", "") for s in backup_steps()}
    assert 'age -r "$BACKUP_AGE_RECIPIENT"' in runs["Dump, check and encrypt the store"]
    assert "-R .github/backup-recipient.txt" not in "\n".join(runs.values())
    check = runs["Check the job is set up"]
    assert ".github/backup-recipient.txt" in check and "BACKUP_AGE_RECIPIENT" in check and "exit 1" in check


def test_the_public_ciphertext_is_kept_two_weeks():
    (upload,) = [s for s in backup_steps() if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert upload["with"]["retention-days"] == 14 and upload["with"]["if-no-files-found"] == "error"
