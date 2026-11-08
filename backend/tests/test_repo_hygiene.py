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


# -- private files at any depth (r1-secrets-history-2) ------------------------------------
# The repository is public and its history cannot be taken back. Twice a commit
# swept in case-store files (bede0c3's -shm/-wal, and two 16 MB backups GitHub
# refused). .gitignore and .dockerignore stop such files at any depth, and the
# last test fails CI if one is tracked anyway: a SQLite file, a provider key, a
# private key, or anything bigger than the largest file kept on purpose.
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
MAX_BYTES = 20 * 1024 * 1024  # the launch films are ~15 MB
PRIVATE = [
    "backend/backups/exchequer-2026-11-05.db.gz",
    "backend/data/report_signing_key.pem",
    "report_signing_key.pem",
    "backend/.env",
    "backend/.env.local",
    ".env.production",
    "backend/hunt-keys.env",
    "hunt-keys-2.env",
    "exchequer.db.bak-20261105T000000Z",
    "backend/exchequer.db-wal",
    "backend/sub/cases.db",
    "snapshot.db.gz",
    "exchequer-20261105T000000Z.pgdump.age",
    "store.pgdump",
    "backend/scripts/import_check.jsonl",
]
# Keys as they appear in use: a NodeReal endpoint, a TronGrid header, an Etherscan query.
KEY_PATTERNS = [
    re.compile(rb"nodereal\.io/v1/[0-9a-f]{32}"),
    re.compile(rb"TRON-PRO-API-KEY[\"']?\s*[:=]\s*[\"']?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I),
    re.compile(rb"apikey=[A-Z0-9]{34}\b"),
    re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----\s*[A-Za-z0-9+/]{64}"),
]

needs_git = pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(),
                               reason="needs a git checkout")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout


def _tracked() -> list[Path]:
    return [ROOT / name for name in _git("ls-files", "-z").split("\0") if name]


@needs_git
@pytest.mark.parametrize("path", PRIVATE)
def test_private_files_are_ignored_at_any_depth(path):
    assert _git("check-ignore", "--no-index", path).strip(), f"{path} would be committed"


@needs_git
def test_the_example_env_file_stays_tracked():
    assert not _git("check-ignore", "--no-index", "backend/.env.example").strip()
    assert not _git("ls-files", "-ci", "--exclude-standard").strip(), "a tracked file is now ignored"


@pytest.mark.parametrize("path", PRIVATE)
def test_the_image_never_copies_them_either(path):
    """.dockerignore uses the same patterns (Docker matches like filepath.Match, plus **)."""
    lines = [ln.strip() for ln in (ROOT / ".dockerignore").read_text().splitlines()]
    patterns = [ln for ln in lines if ln and not ln.startswith(("#", "!"))]

    def match(pattern: str) -> bool:
        rx = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
        return re.fullmatch(rx + "(?:/.*)?", path) is not None

    assert any(match(p) for p in patterns), f"{path} would be copied into the image"


@needs_git
def test_no_tracked_file_is_a_database_a_key_or_oversized():
    problems = []
    for path in _tracked():
        if not path.is_file() or path.is_symlink():
            continue
        size = path.stat().st_size
        if size > MAX_BYTES:
            problems.append(f"{path.relative_to(ROOT)}: {size} bytes")
            continue
        with path.open("rb") as handle:
            head = handle.read(16)
            if head.startswith(b"SQLite format 3"):
                problems.append(f"{path.relative_to(ROOT)}: a SQLite database")
                continue
            if size > 2 * 1024 * 1024:  # label files and media: no key lives there
                continue
            body = head + handle.read()
        problems += [f"{path.relative_to(ROOT)}: looks like a key ({p.pattern[:30]!r})"
                     for p in KEY_PATTERNS if p.search(body)]
    assert not problems, problems
