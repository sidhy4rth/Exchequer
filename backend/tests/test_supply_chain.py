"""What the image and CI build from, and when they take something new.

Images were pulled by movable tag (node:24-slim, python:3.12-slim, postgres:17),
so a build ran on whatever the tag pointed to that day (audit
r1-deps-supplychain-1). Every npm install ran dependency install hooks, which
nothing here needs (r1-deps-supplychain-3). Dependabot proposed releases hours
old and mixed major jumps with patches in one PR (r1-deps-supplychain-4).
Offline: these read the files only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def _image_refs() -> list[tuple[str, str]]:
    refs = []
    for line in (ROOT / "Dockerfile").read_text().splitlines():
        if line.startswith("# syntax="):
            refs.append(("Dockerfile", line.split("=", 1)[1].strip()))
        elif line.startswith("FROM "):
            refs.append(("Dockerfile", line.split()[1]))
    for path in WORKFLOWS:
        text = path.read_text()
        refs += [(path.name, ref) for ref in re.findall(r"^\s*image:[ \t]*(\S+)", text, re.M)]
        refs += [(path.name, ref) for ref in re.findall(r"=((?:postgres|python|node):\S+?)\s", text)]
    return refs


def test_every_image_is_pinned_by_digest():
    refs = _image_refs()
    assert {name for name, _ in refs} >= {"Dockerfile", "test.yml", "backup.yml"}
    assert sum(name == "Dockerfile" for name, _ in refs) == 3  # the syntax frontend and both stages
    for name, ref in refs:
        if ref.startswith("${{"):
            continue
        # A tag that names the version, then the digest it pointed to.
        assert re.match(r"[\w./-]+:\d[\w.-]*@sha256:", ref) and DIGEST.search(ref), f"{name}: {ref}"


def test_the_python_and_node_stages_stay_on_their_lines():
    stages = dict(re.findall(r"^FROM (\S+) AS (\w+)$", (ROOT / "Dockerfile").read_text(), re.M))
    by_stage = {stage: ref for ref, stage in stages.items()}
    assert by_stage["app"].startswith("python:3.12.")
    assert by_stage["frontend"].startswith("node:24.")


def _npm_installs() -> list[tuple[str, str]]:
    found = []
    for path in (ROOT / "Dockerfile", *WORKFLOWS):
        found += [(path.name, line.strip()) for line in path.read_text().splitlines()
                  if re.search(r"\bnpm (ci|install|i)\b", line)]
    return found


def test_npm_installs_skip_install_scripts():
    installs = _npm_installs()
    assert {name for name, _ in installs} >= {"Dockerfile", "test.yml", "site-canary.yml"}
    for name, line in installs:
        assert "npm ci --ignore-scripts" in line, f"{name}: {line}"


def test_the_frontend_npmrc_turns_install_scripts_off():
    """For an `npm ci` or `npm install` a person runs in frontend/ too."""
    settings = dict(line.split("=", 1) for line in (ROOT / "frontend" / ".npmrc").read_text().splitlines()
                    if "=" in line and not line.startswith(("#", ";")))
    assert settings.get("ignore-scripts", "").strip() == "true"


def test_only_fsevents_has_an_install_script():
    """A new dependency with an install hook shows up here, in review, not on a laptop."""
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text())
    hooks = {path for path, entry in lock["packages"].items() if entry.get("hasInstallScript")}
    assert hooks <= {"node_modules/fsevents"}, sorted(hooks)


def _updates() -> list[dict]:
    return yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())["updates"]


def test_dependabot_waits_before_proposing_a_release():
    """Security updates skip the cooldown; a version update waits a week (a package major, a month)."""
    for update in _updates():
        cooldown = update.get("cooldown") or {}
        assert cooldown.get("default-days", 0) >= 7, update["package-ecosystem"]
        if update["package-ecosystem"] in ("uv", "npm"):  # the only two with semver cooldowns
            assert cooldown.get("semver-major-days", 0) >= 30, update["package-ecosystem"]


def test_dependabot_never_mixes_a_major_with_patches():
    for update in _updates():
        ecosystem = update["package-ecosystem"]
        groups = update.get("groups") or {}
        assert groups, ecosystem
        for name, group in groups.items():
            assert group.get("update-types") and "major" not in group["update-types"], f"{ecosystem} {name}"
        if ecosystem != "github-actions":  # an action's major comes alone, ungrouped
            ignored = [rule for rule in update.get("ignore", []) if rule.get("dependency-name") == "*"]
            assert any("version-update:semver-major" in rule.get("update-types", []) for rule in ignored), ecosystem


def test_dependabot_keeps_python_on_312_and_node_on_24():
    (docker,) = [u for u in _updates() if u["package-ecosystem"] == "docker"]
    rules = {rule["dependency-name"]: rule.get("update-types", []) for rule in docker.get("ignore", [])}
    assert "version-update:semver-minor" in rules.get("python", [])
    assert "version-update:semver-major" in rules.get("*", [])
    assert {u["package-ecosystem"] for u in _updates()} == {"uv", "npm", "github-actions", "docker"}
