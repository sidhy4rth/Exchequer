"""The nightly off-site backup (.github/workflows/backup.yml) copies the store
that exists, and is red when it cannot.

It pulled a SQLite snapshot from /admin/backup, which answers 404 whenever the
store is Postgres (production is Neon), and with no BACKUP_TOKEN it printed a
notice and ended green: every night "success" with nothing copied. Now it
pg_dumps the Postgres store, encrypted to a pinned recipient, and fails when
it is not set up."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "backup.yml"
RECIPIENT = (ROOT / ".github" / "backup-recipient.txt").read_text().strip()


def job() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["backup"]


def step(name: str) -> dict:
    (found,) = [s for s in job()["steps"] if s.get("name") == name]
    return found


def run_text() -> str:
    return "\n".join(s.get("run", "") for s in job()["steps"])


def test_backup_dumps_the_postgres_store():
    assert job()["environment"] == "backup"  # secrets only for the protected environment
    text = run_text()
    assert "pg_dump --format=custom --no-owner" in text
    for gone in ("/admin/backup", "BACKUP_TOKEN", "sqlite3", "count(", "SELECT"):
        assert gone not in WORKFLOW.read_text(), gone


def test_the_dump_is_checked_and_only_ciphertext_is_kept():
    text = step("Dump, check and encrypt the store")["run"]
    assert "pg_restore --list" in text and "TABLE DATA public cases" in text
    assert 'age -r "$BACKUP_AGE_RECIPIENT"' in text and "rm -f store.pgdump" in text
    upload = step("Keep the encrypted dump")["with"]
    assert upload["if-no-files-found"] == "error" and upload["retention-days"] == 14


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("env, ok", [
    ({}, False),
    ({"NEON_BACKUP_URL": "postgresql://reader@host/db"}, False),
    ({"BACKUP_AGE_RECIPIENT": RECIPIENT}, False),
    ({"NEON_BACKUP_URL": "postgresql://reader@host/db", "BACKUP_AGE_RECIPIENT": "age1someoneelse"}, False),
    ({"NEON_BACKUP_URL": "postgresql://reader@host/db", "BACKUP_AGE_RECIPIENT": RECIPIENT}, True),
])
def test_a_backup_that_is_not_set_up_is_red(env, ok):
    script = step("Check the job is set up")["run"]
    done = subprocess.run(["bash", "-e", "-c", script], cwd=ROOT, capture_output=True, text=True,
                          env={"PATH": os.environ.get("PATH", ""), **env})
    assert (done.returncode == 0) is ok, done.stdout + done.stderr
    if not ok:
        assert "::error::" in done.stdout
