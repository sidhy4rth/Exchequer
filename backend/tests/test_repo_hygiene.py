"""What never goes into the image or the repository (R33c).

The Docker build sends its whole context to the builder; docs/ (PDFs and
README images) is never copied into the image, so it only slows every build.
SQLite's -shm/-wal files once slipped into a commit beside a local store.
"""
from __future__ import annotations

from pathlib import Path

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
