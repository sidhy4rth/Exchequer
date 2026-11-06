"""What never goes into the image or the repository (R33c).

The Docker build sends its whole context to the builder; docs/ (PDFs and
README images) is never copied into the image, so it only slows every build.
SQLite's -shm/-wal files once slipped into a commit beside a local store.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def entries(name: str) -> set[str]:
    lines = (ROOT / name).read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_the_docker_build_leaves_out_docs_and_secrets():
    ignored = entries(".dockerignore")
    assert "docs" in ignored or "docs/" in ignored
    assert "**/.env" in ignored and "**/*.pem" in ignored


def test_git_ignores_sqlite_side_files():
    assert {"*.db", "*.db-shm", "*.db-wal"} <= entries(".gitignore")


def test_the_image_requires_the_label_store_unless_ci_opts_out():
    """r1-scripts-12: a deploy whose build secret is missing fails rather than
    shipping without the label store; CI's image job, which has no secret, says so."""
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert 'ARG LABEL_STORE_REQUIRED="1"' in dockerfile
    assert 'LABEL_STORE_REQUIRED="$LABEL_STORE_REQUIRED"' in dockerfile
    assert "EXCHEQUER_LABEL_STORE_REQUIRED=${LABEL_STORE_REQUIRED}" in dockerfile
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text()
    builds = [line for line in workflow.splitlines() if "docker build" in line]
    assert builds and all("--build-arg LABEL_STORE_REQUIRED=0" in line for line in builds)


def test_the_private_label_store_and_its_temp_files_are_never_committed_or_copied():
    """r1-scripts-13: an interrupted build or download leaves label_store.building or
    label_store.partial beside the store; neither may reach git or the build context."""
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    paths = ["backend/data/label_store.building", "backend/data/label_store.partial",
             "backend/data/label_store.db", "backend/data/label_store_2026-11-05b.db.gz"]
    for path in paths:
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
        if result.returncode == 128:
            pytest.skip("not a git checkout")
        assert result.returncode == 0, f"{path} is not ignored by git"
    # The modules named for the store stay tracked.
    for path in ("backend/app/label_store.py", "backend/scripts/build_label_store.py"):
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 1
    docker = entries(".dockerignore")
    assert {"**/*.building", "**/*.partial", "backend/data/label_store*"} <= docker
