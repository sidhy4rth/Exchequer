"""The platform interfaces every lane builds on: auth.current_user,
audit.record and config.flag. Stubs until R23 and R24, but their shape is
the contract, so it is tested now."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import audit, auth, config, ownership

KEY = "k" * 32


@pytest.fixture
def whoami():
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: auth.CurrentUser):
        return user.__dict__

    return lambda headers=None: TestClient(app).get("/whoami", headers=headers or {}).json()


# -- current_user --------------------------------------------------------------
def test_current_user_is_the_browser_that_owns_its_cases(whoami):
    user = whoami({ownership.OWNER_HEADER: KEY})
    # The same hash a case traced from this browser is stored under.
    assert user["owner_hash"] == ownership.owner_hash(KEY)
    assert user["id"].startswith("demo-") and KEY not in user["id"]
    assert user["role"] == "officer" and user["role"] in auth.ROLES
    assert user["unit"] == auth.DEMO_UNIT and user["demo"] is True


def test_two_browsers_are_two_users(whoami):
    assert whoami({ownership.OWNER_HEADER: KEY})["id"] != whoami({ownership.OWNER_HEADER: "j" * 32})["id"]


def test_no_key_or_a_malformed_one_is_anonymous(whoami):
    for headers in (None, {ownership.OWNER_HEADER: "short"}):
        user = whoami(headers)
        assert user["id"] == "anonymous" and user["owner_hash"] is None


# -- audit.record ----------------------------------------------------------------
def test_record_writes_one_line_with_event_case_and_detail(caplog):
    with caplog.at_level(logging.INFO, logger="exchequer.audit"):
        audit.record("case.export", case_id="c1", detail={"format": "pdf"})
    [line] = caplog.messages
    assert "case.export" in line and "c1" in line and '"format": "pdf"' in line


def test_record_needs_no_case_or_detail(caplog):
    with caplog.at_level(logging.INFO, logger="exchequer.audit"):
        audit.record("watch.create")
    assert len(caplog.messages) == 1


@pytest.mark.parametrize("bad", [
    {"event": "export"},                                    # not dotted
    {"event": "Case.Export"},                               # not lower case
    {"event": "case.export", "detail": "pdf"},              # detail is not an object
    {"event": "case.export", "detail": {"at": datetime.now(timezone.utc)}},  # not JSON
    {"event": "case.export", "detail": {"amount": float("nan")}},            # not JSON
])
def test_a_call_the_real_audit_log_could_not_store_fails_and_writes_nothing(caplog, bad):
    with caplog.at_level(logging.INFO, logger="exchequer.audit"):
        with pytest.raises((ValueError, TypeError)):
            audit.record(bad["event"], detail=bad.get("detail"))
    assert caplog.messages == []


def test_case_id_is_keyword_only():
    with pytest.raises(TypeError):
        audit.record("case.read", "c1")


# -- config.flag -----------------------------------------------------------------
@pytest.fixture
def scratch_flag():
    name = "EXCHEQUER_TEST_ONLY_FLAG"
    yield name
    config.FLAGS.pop(name, None)


def test_a_flag_is_off_unless_set(monkeypatch, scratch_flag):
    monkeypatch.delenv(scratch_flag, raising=False)
    assert config.flag(scratch_flag, "test") is False
    assert config.FLAGS[scratch_flag] == {"on": False, "about": "test"}


@pytest.mark.parametrize("value, on", [("1", True), ("true", True), ("ON", True), ("0", False), ("", False), ("nope", False)])
def test_a_flag_reads_its_environment_variable(monkeypatch, scratch_flag, value, on):
    monkeypatch.setenv(scratch_flag, value)
    assert config.flag(scratch_flag, "test") is on


def test_two_flags_cannot_share_a_name(scratch_flag):
    config.flag(scratch_flag, "first")
    with pytest.raises(ValueError):
        config.flag(scratch_flag, "second")
