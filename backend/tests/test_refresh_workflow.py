"""The list-refresh bot's pull request may change the refreshed lists and nothing else.

refresh-lists.yml rebuilds one branch each night and stages only the list
files. test.yml's "bot branch touches only list files" job refuses that
branch's pull request if it changes anything else, so a push to the bot
branch cannot slip code past a reviewer who expects list data (audit
r1-ci-github-3). Read as text: no YAML dependency.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
BOT_BRANCH = "b/r11-refresh-lists-bot"


def _job(text: str, name: str) -> str:
    """The text of the job whose `name:` is `name`, up to the next job."""
    start = text.index(f"name: {name}")
    following = re.search(r"\n  [A-Za-z0-9_-]+:\n", text[start:])
    return text[start:start + following.start()] if following else text[start:]


def _allowed() -> re.Pattern[str]:
    job = _job((WORKFLOWS / "test.yml").read_text(), "bot branch touches only list files")
    (pattern,) = re.findall(r"grep -Ev '([^']+)'", job)
    return re.compile(pattern)


def test_the_bot_scope_job_runs_only_on_the_bot_branchs_pull_request():
    job = _job((WORKFLOWS / "test.yml").read_text(), "bot branch touches only list files")
    assert "github.event_name == 'pull_request'" in job
    assert f"github.head_ref == '{BOT_BRANCH}'" in job
    # It reads the pull request's own file list, renames' old names included.
    assert "pulls/$PR/files" in job and "previous_filename" in job
    assert "exit 1" in job


def test_the_bot_branch_name_matches_the_refresh_workflow():
    assert f"BRANCH: {BOT_BRANCH}" in (WORKFLOWS / "refresh-lists.yml").read_text()


def test_every_list_the_bot_stages_is_allowed_and_nothing_else_is():
    allowed = _allowed()
    staged = re.search(r"git add -- (.+)", (WORKFLOWS / "refresh-lists.yml").read_text()).group(1).split()
    shipped = [f"backend/{p.relative_to(ROOT / 'backend')}" for glob in staged
               for p in (ROOT / "backend").glob(glob)]
    assert len(shipped) >= 10  # OFAC, intl and Tether files on every chain that has them
    assert all(allowed.fullmatch(path) for path in shipped), shipped
    for other in ("backend/app/risk_matcher.py", "backend/data/exchange_labels.json",
                  "backend/data/never_flag_tokens.json", "backend/data/risk_labels.json.bak",
                  "backend/data/sub/risk_labels.json", ".github/workflows/test.yml",
                  "backend/tests/test_risk_matcher.py", "Dockerfile"):
        assert not allowed.search(other), other
