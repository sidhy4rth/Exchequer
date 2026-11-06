"""The background jobs and proxy trust are opt-in per host (config.host_flag,
Dockerfile).

The image used to turn the watcher, daily snapshots, the demo warm-up and
proxy-header trust on for every host, and relied on render.yaml to turn them
off on Render's free plan. The live service drifted from render.yaml (values
added after it was created never reached it), so the watcher ran on a host
that sleeps and forgets. Now the image turns nothing on, a job asked for on a
temporary disk stays off unless forced, and /health/detail shows what is on."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
JOBS = ("EXCHEQUER_WATCHER", "EXCHEQUER_BACKUPS", "EXCHEQUER_WARM_CACHE")


@pytest.mark.parametrize("name", JOBS)
def test_a_job_stays_off_on_a_temporary_disk(name):
    assert config.host_flag({"RENDER": "true", name: "1"}, name) is False


@pytest.mark.parametrize("name", JOBS)
def test_force_turns_a_job_on_anywhere(name):
    assert config.host_flag({"RENDER": "true", name: "force"}, name) is True


def test_on_a_host_with_a_lasting_disk_the_flag_reads_as_before():
    flag = config.host_flag
    assert flag({"EXCHEQUER_WATCHER": "1"}, "EXCHEQUER_WATCHER") is True
    assert flag({"EXCHEQUER_WATCHER": "on"}, "EXCHEQUER_WATCHER") is True
    assert flag({"EXCHEQUER_WATCHER": "0"}, "EXCHEQUER_WATCHER") is False
    assert flag({}, "EXCHEQUER_WATCHER") is False
    assert flag({"RENDER": "true", "EXCHEQUER_TEMPORARY_DISK": "0", "EXCHEQUER_WATCHER": "1"},
                "EXCHEQUER_WATCHER") is True


def settings_under(env: dict[str, str]) -> str:
    keep = {k: v for k, v in os.environ.items() if not k.startswith(("EXCHEQUER_", "RENDER"))}
    out = subprocess.run(
        [sys.executable, "-c", "from app import config as c; "
         "print(c.WATCHER_ENABLED, c.BACKUPS_ENABLED, c.WARM_CACHE_AT_STARTUP)"],
        cwd=config.BACKEND_DIR, env={**keep, "DATABASE_URL": "", **env}, capture_output=True, text=True,
        check=True)
    return out.stdout.strip()


def test_the_settings_use_it():
    on = {name: "1" for name in JOBS}
    assert settings_under({**on, "RENDER": "true"}) == "False False False"
    assert settings_under({**{name: "force" for name in JOBS}, "RENDER": "true"}) == "True True True"
    assert settings_under(on) == "True True True"


def test_the_image_turns_on_no_background_job_and_trusts_no_proxy_header():
    env_lines = {line.split()[1].split("=")[0] for line in (ROOT / "Dockerfile").read_text().splitlines()
                 if line.startswith("ENV ") and "=" in line}
    for name in (*JOBS, "EXCHEQUER_TRUST_PROXY"):
        assert name not in env_lines, name


def test_health_detail_shows_the_effective_runtime_flags(monkeypatch):
    monkeypatch.setattr(config, "HEALTH_TOKEN", "t" * 40)
    with TestClient(app) as client:
        body = client.get("/health/detail", headers={"authorization": "Bearer " + "t" * 40}).json()
    assert body["runtime"] == {
        "watcher": config.WATCHER_ENABLED, "backups": config.BACKUPS_ENABLED,
        "warm_cache": config.WARM_CACHE_AT_STARTUP, "trust_proxy": config._proxy_raw or "off",
        "temporary_disk": config.TEMPORARY_DISK,
    }
