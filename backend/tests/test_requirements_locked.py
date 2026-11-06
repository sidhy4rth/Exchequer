"""Every Python package the image and CI install is pinned and hashed.

requirements.txt used to pin the 13 packages the code names and nothing
under them, so each build took whatever PyPI served that minute for the other
two dozen (anyio, idna, certifi, pillow, ...), and CI and the image could get
different trees (audit r1-deps-supplychain-0). The hand-edited lists are now
requirements*.in; requirements*.txt are compiled from them with every package
pinned and hashed, and every install refuses anything else. Offline: these
read the files only.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
COMPILE = "uv pip compile {src} --universal --python-version 3.12 --generate-hashes -o {out}"


def _name(raw: str) -> str:
    return re.sub(r"[-_.]+", "-", raw).lower()


def _entries(path: Path) -> list[str]:
    """Requirement lines with their continuations joined, comments dropped."""
    text = re.sub(r"\\\n\s*", " ", path.read_text())
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "-r ", "-c "))]


def _pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in _entries(path):
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==([^\s;]+)", line)
        assert match, f"{path.name}: not an exact pin: {line[:80]}"
        pins[_name(match.group(1))] = match.group(3)
    return pins


def _via(path: Path) -> dict[str, set[str]]:
    """package -> what the compiler says needs it (its `# via` lines)."""
    via: dict[str, set[str]] = {}
    current = None
    for line in path.read_text().splitlines():
        if re.match(r"[A-Za-z0-9]", line):
            current = _name(re.match(r"[A-Za-z0-9._-]+", line).group(0))
            via[current] = set()
        elif current and (found := re.match(r"\s+#\s+(?:via\s+)?(\S.*)$", line)) and found.group(1) != "via":
            via[current].add(found.group(1).strip())
    return via


def test_every_locked_requirement_is_an_exact_pin_with_hashes():
    for lock in ("requirements.txt", "requirements-dev.txt"):
        entries = _entries(BACKEND / lock)
        assert len(entries) >= 30, lock  # the whole tree, not just the direct pins
        for line in entries:
            assert "==" in line and "--hash=sha256:" in line, f"{lock}: {line[:80]}"


def test_every_direct_pin_is_locked_at_the_same_version():
    for source, lock in (("requirements.in", "requirements.txt"), ("requirements-dev.in", "requirements-dev.txt")):
        locked = _pins(BACKEND / lock)
        for name, version in _pins(BACKEND / source).items():
            assert locked.get(name) == version, f"{source} pins {name}=={version}; {lock} has {locked.get(name)}"


def test_the_lock_holds_nothing_the_in_file_no_longer_asks_for():
    """A package dropped from requirements.in must leave the lock too: recompile."""
    for source, lock in (("requirements.in", "requirements.txt"), ("requirements-dev.in", "requirements-dev.txt")):
        direct = set(_pins(BACKEND / source))
        if source == "requirements-dev.in":
            direct |= set(_pins(BACKEND / "requirements.in"))
        locked = _pins(BACKEND / lock)
        for name, reasons in _via(BACKEND / lock).items():
            needed_by = {_name(r) for r in reasons if not r.startswith("-")}
            assert name in direct or needed_by & set(locked), f"{lock}: nothing needs {name} ({reasons})"


def test_the_dev_lock_installs_the_runtime_lock_unchanged():
    runtime, dev = _pins(BACKEND / "requirements.txt"), _pins(BACKEND / "requirements-dev.txt")
    assert {name: dev.get(name) for name in runtime} == runtime
    assert {"pytest", "ruff", "pyyaml"} <= set(dev) - set(runtime)


def test_each_lock_says_how_to_rebuild_it():
    """Dependabot (the uv ecosystem) recompiles a lock with the options its header names."""
    for source, out in (("requirements.in", "requirements.txt"), ("requirements-dev.in", "requirements-dev.txt")):
        assert COMPILE.format(src=source, out=out) in (BACKEND / out).read_text().splitlines()[1]
    assert "-c requirements.txt" in (BACKEND / "requirements-dev.in").read_text().splitlines()


def _pip_installs() -> list[tuple[str, str]]:
    found = []
    for path in (ROOT / "Dockerfile", *sorted((ROOT / ".github" / "workflows").glob("*.yml"))):
        text = re.sub(r"\\\n\s*", " ", path.read_text())
        found += [(path.name, line.strip()) for line in text.splitlines() if re.search(r"\bpip install\b", line)]
    return found


def test_every_install_refuses_an_unhashed_package():
    installs = _pip_installs()
    assert {name for name, _ in installs} >= {"Dockerfile", "test.yml", "refresh-lists.yml"}
    for name, line in installs:
        assert "--require-hashes" in line and re.search(r"-r requirements(-dev)?\.txt\b|backend/requirements\.txt", line), (
            f"{name}: {line}")
    (image,) = [line for name, line in installs if name == "Dockerfile"]
    assert "--only-binary=:all:" in image  # no package's setup.py runs in the build


def test_the_image_installs_the_runtime_lock_only():
    (image,) = [line for name, line in _pip_installs() if name == "Dockerfile"]
    assert image.endswith("-r backend/requirements.txt")
    assert "requirements-dev" not in (ROOT / "Dockerfile").read_text()
