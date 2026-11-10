"""The app user has no home directory (Dockerfile: --no-create-home), and
setpriv keeps root's HOME=/root. libpq then looks for an optional client
certificate in /root/.postgresql, which uid 10001 may not read, and refuses to
connect ("could not open certificate file …: Permission denied"): the first
Neon deploy ran without its case store. The entrypoint sets HOME to /data,
which it has just handed to the app user, before it drops privileges."""
from pathlib import Path

ENTRYPOINT = (Path(__file__).resolve().parents[2] / "docker-entrypoint.sh").read_text()


def test_home_points_at_the_app_users_volume_before_dropping_privileges():
    drop = ENTRYPOINT.index("exec setpriv")
    assert "export HOME=/data" in ENTRYPOINT[:drop]
    assert ENTRYPOINT.index("export HOME=/data") > ENTRYPOINT.index('test -w /data')


def test_the_ci_image_job_checks_the_running_servers_home():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/test.yml").read_text()
    assert "HOME=/data" in workflow
