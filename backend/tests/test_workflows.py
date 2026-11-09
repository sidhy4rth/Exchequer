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


# -- the list refresh (r1-ci-github-1, r1-ci-github-2) -----------------------------------
def refresh_jobs() -> dict:
    return load(ROOT / ".github" / "workflows" / "refresh-lists.yml")["jobs"]


def test_the_job_that_parses_downloads_holds_no_write_token():
    workflow = load(ROOT / ".github" / "workflows" / "refresh-lists.yml")
    assert workflow["permissions"] == {}
    refresh = workflow["jobs"]["refresh"]
    assert refresh["permissions"] == {"contents": "read"}
    assert "write" not in yaml.safe_dump(refresh["permissions"])
    # No cache another workflow could have written is restored beside the provider keys.
    assert not any("cache" in (step.get("with") or {}) for step in refresh["steps"])
    assert not any(str(step.get("uses", "")).startswith("actions/cache") for step in refresh["steps"])


def test_only_the_importer_step_and_the_bot_token_step_see_a_secret():
    for job_id, job in refresh_jobs().items():
        for step in job["steps"]:
            secrets = SECRET.findall(yaml.safe_dump(step))
            if not secrets:
                continue
            assert (job_id, step.get("name")) in {("refresh", "Run the importers"), ("publish", "The list bot's token")}, (
                job_id, step.get("name"), secrets)


def test_publishing_takes_only_checked_lists_from_the_refresh_job():
    jobs = refresh_jobs()
    publish = jobs["publish"]
    assert publish["needs"] == "refresh" and "tested == 'true'" in publish["if"]
    assert publish["environment"] == "list-publish"
    runs = [step.get("run", "") for step in publish["steps"]]
    # Stdlib only: nothing is installed in the job that holds the token.
    assert not any("pip install" in run for run in runs)
    accept = runs.index(next(r for r in runs if "accept_lists.py" in r))
    commit = runs.index(next(r for r in runs if "git commit" in r))
    assert accept < commit
    upload = [s for s in jobs["refresh"]["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert upload and upload[0]["if"] == "steps.tests.outputs.tested == 'true'"


def test_the_pull_request_prefers_the_list_bot_token():
    """An App's pull request runs test.yml; one opened with GITHUB_TOKEN does not."""
    steps = {s.get("name"): s for s in refresh_jobs()["publish"]["steps"]}
    assert steps["The list bot's token"]["uses"].startswith("actions/create-github-app-token@")
    assert steps["Open or update the pull request"]["env"]["GH_TOKEN"] == "${{ steps.bot.outputs.token || github.token }}"


def test_the_nightly_job_runs_strict():
    """r1-ci-github-2: a list skipped for want of its key turns the nightly run red."""
    steps = {s.get("name"): s for s in refresh_jobs()["refresh"]["steps"]}
    assert "python -m scripts.import_all_lists --strict " in steps["Run the importers"]["run"]


# -- the site canary (r1-ci-github-9) -------------------------------------------------------
def test_a_push_canary_checks_the_pushed_commit_not_a_fixed_sleep():
    steps = load(ROOT / ".github" / "workflows" / "site-canary.yml")["jobs"]["canary"]["steps"]
    runs = [str(s.get("run", "")) for s in steps]
    assert not any(run.strip().startswith("sleep 240") for run in runs)
    (wait,) = [s for s in steps if s.get("name") == "Wait for the pushed commit to go live"]
    assert wait["if"] == "github.event_name == 'push'" and wait["env"]["WANT"] == "${{ github.sha }}"
    assert '"build"' in wait["run"] and "exit 1" in wait["run"]
    names = [s.get("name") for s in steps]
    assert names.index("Wake the site") < names.index("Wait for the pushed commit to go live")


# -- commit e-mails (r1-secrets-history-4) ---------------------------------------------------
def test_new_commits_must_carry_a_noreply_address():
    job = load(ROOT / ".github" / "workflows" / "test.yml")["jobs"]["emails"]
    (checkout, check) = job["steps"]
    assert checkout["with"] == {"persist-credentials": False, "fetch-depth": 0}
    assert "check_commit_emails.sh" in check["run"] and "${{" not in check["run"]
    script = (ROOT / ".github" / "scripts" / "check_commit_emails.sh").read_text()
    assert "@users.noreply.github.com" in script and "%ae" in script and "%ce" in script


def test_render_deploys_each_merge_and_the_canary_can_see_it():
    """r1-deps-supplychain-4: a Dependabot merge deployed before CI had finished.
    Branch protection on main now takes only pull requests whose CI checks
    passed (admins included), so a commit on main has passed CI. checksPass
    would also wait for the push canary, which itself waits for that commit
    to go live: each waits for the other, and nothing would deploy again."""
    service = load(ROOT / "render.yaml")["services"][0]
    assert service["autoDeployTrigger"] == "commit"
    on = load(ROOT / ".github" / "workflows" / "site-canary.yml")[True]
    assert "push" in on


def test_render_names_the_measured_proxy_hops():
    """Measured on the live site 9 Nov 2026 (/health/detail client_ip): the
    X-Forwarded-For chain is client, Cloudflare edge, Render's proxy, so the
    client is the third entry from the right. Used only when CF-Connecting-IP
    is missing; set, the leftmost (client-chosen) entry is never the key."""
    env = {e["key"]: e for e in load(ROOT / "render.yaml")["services"][0]["envVars"]}
    assert env["EXCHEQUER_TRUST_PROXY"]["value"] == "render"
    assert env["EXCHEQUER_PROXY_HOPS"]["value"] == "3"


def test_the_nightly_list_refresh_waits_for_the_owner_to_switch_it_on():
    """9 Nov: with no keys in the `lists` environment every night was red and
    e-mailed the owner. Scheduled runs need the repository variable
    REFRESH_LISTS=on; a run started by hand always runs, and once on, a
    missing key is still red (--strict)."""
    jobs = refresh_jobs()
    assert jobs["refresh"]["if"] == "github.event_name == 'workflow_dispatch' || vars.REFRESH_LISTS == 'on'"
    assert "needs.refresh.outputs.tested == 'true'" in jobs["publish"]["if"]


# -- the accessibility check (before the Glass restyle) ------------------------------------
def test_the_a11y_job_checks_a_build_served_on_the_runner_with_no_keys():
    """The axe check opens pages and a recorded demo, which need no provider
    key, so it runs with no secret and no environment, against the backend
    serving the fresh build on the runner itself: never the live site."""
    job = load(ROOT / ".github" / "workflows" / "test.yml")["jobs"]["a11y"]
    text = yaml.safe_dump(job)
    assert "environment" not in job and not SECRET.findall(text) and "onrender.com" not in text
    assert not job.get("continue-on-error")
    runs = [str(step.get("run", "")) for step in job["steps"]]

    def at(command: str) -> int:
        return next(i for i, run in enumerate(runs) if command in run)

    assert at("npm ci --ignore-scripts") < at("npm run build") < at("uvicorn app.main:app --host 127.0.0.1")
    assert at("uvicorn app.main:app --host 127.0.0.1") < at("npm run a11y")
    assert at("npx playwright install --with-deps chromium") < at("npm run a11y")
    assert job["env"]["EXCHEQUER_URL"].startswith("http://127.0.0.1:")
