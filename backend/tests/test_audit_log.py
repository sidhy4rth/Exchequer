"""R24: the audit log is a hash-chained, append-only table.

Each row's hash covers the row before it, so editing, deleting or reordering
any row breaks the chain from that row on, and /audit/verify names where.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import audit, config, models, ownership
from app.main import app

KEY = "a" * 32
OWNER = ownership.owner_hash(KEY)
HEADERS = {ownership.OWNER_HEADER: KEY}


@pytest.fixture
def engine(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    models.init_db()
    return engine


def rows(engine) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text("SELECT * FROM audit_events ORDER BY seq"))]


def fill(n: int) -> None:
    for i in range(n):
        audit.record("case.report_export", case_id=f"case-{i % 3}", detail={"format": "pdf", "i": i})


# -- the chain ---------------------------------------------------------------

def test_every_row_hashes_the_one_before_it(engine):
    fill(120)
    stored = rows(engine)
    assert [r["seq"] for r in stored] == list(range(1, 121))
    assert stored[0]["prev_hash"] == "0" * 64
    prev = "0" * 64
    for row in stored:
        body = {k: row[k] for k in ("seq", "at", "actor", "unit_id", "action", "case_id", "prev_hash")}
        body["detail"] = json.loads(row["detail"])
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        assert row["prev_hash"] == prev
        assert row["row_hash"] == hashlib.sha256((prev + canonical).encode()).hexdigest()
        prev = row["row_hash"]
    assert audit.verify() == {"ok": True, "rows": 120, "first_bad_seq": None}


def test_an_empty_log_verifies(engine):
    assert audit.verify() == {"ok": True, "rows": 0, "first_bad_seq": None}


def short_hash(stored_detail: str) -> str:
    return "sha256:" + hashlib.sha256(stored_detail.encode()).hexdigest()[:12]


def test_the_log_line_is_still_written(engine, caplog):
    with caplog.at_level("INFO", logger="exchequer.audit"):
        audit.record("case.letter_draft", case_id="c1", detail={"to": "exchange"})
    [line] = caplog.messages
    # The event and the case, and a short hash that matches the stored row's detail: never the detail itself.
    assert line == f"audit case.letter_draft case=c1 detail={short_hash(rows(engine)[0]['detail'])}"
    assert "exchange" not in line


@pytest.mark.parametrize("tamper, bad", [
    ("UPDATE audit_events SET detail = '{\"format\": \"csv\", \"i\": 36}' WHERE seq = 37", 37),
    ("UPDATE audit_events SET actor = 'demo:someone-else' WHERE seq = 5", 5),
    ("UPDATE audit_events SET at = '2020-01-01T00:00:00+00:00' WHERE seq = 59", 59),
    ("DELETE FROM audit_events WHERE seq = 20", 20),
    ("DELETE FROM audit_events WHERE seq = 1", 1),
    # Reorder: rows 10 and 11 swap places.
    (("UPDATE audit_events SET seq = -10 WHERE seq = 10", "UPDATE audit_events SET seq = 10 WHERE seq = 11",
      "UPDATE audit_events SET seq = 11 WHERE seq = -10"), 10),
])
def test_tampering_is_found_at_the_first_bad_row(engine, tamper, bad):
    fill(60)
    with engine.begin() as conn:
        for statement in (tamper,) if isinstance(tamper, str) else tamper:
            conn.execute(text(statement))
    report = audit.verify()
    assert report["ok"] is False and report["first_bad_seq"] == bad


def test_a_row_edited_and_rehashed_breaks_the_next_link(engine):
    fill(10)
    row = rows(engine)[3]
    body = {k: row[k] for k in ("seq", "at", "actor", "unit_id", "action", "case_id", "prev_hash")}
    body["detail"] = {"format": "text"}
    forged = hashlib.sha256((row["prev_hash"] + json.dumps(body, sort_keys=True, separators=(",", ":")))
                            .encode()).hexdigest()
    with engine.begin() as conn:
        conn.execute(text("UPDATE audit_events SET detail = :d, row_hash = :h WHERE seq = 4"),
                     {"d": json.dumps(body["detail"]), "h": forged})
    assert audit.verify() == {"ok": False, "rows": 10, "first_bad_seq": 5}


@pytest.mark.parametrize("process_lock", [True, False], ids=["one-process", "store-lock-only"])
def test_appends_from_many_threads_leave_no_gap_and_no_fork(engine, monkeypatch, process_lock):
    if not process_lock:  # as if each thread were its own worker process
        monkeypatch.setattr(audit, "_lock", contextlib.nullcontext())
    start = threading.Barrier(8)

    def worker(n: int) -> None:
        start.wait()
        for i in range(15):
            audit.record("watch.create", detail={"thread": n, "i": i})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stored = rows(engine)
    assert [r["seq"] for r in stored] == list(range(1, 121))
    assert len({r["prev_hash"] for r in stored}) == 120  # no two rows claim the same parent
    assert audit.verify() == {"ok": True, "rows": 120, "first_bad_seq": None}


def test_a_store_that_cannot_take_the_row_does_not_fail_the_action(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'none.db'}", future=True))
    audit.record("case.report_export", case_id="c1", detail={"format": "pdf"})  # no table: logged, not raised
    assert "could not be stored" in caplog.text


# -- what a row may hold -------------------------------------------------------

def test_secrets_and_particulars_never_reach_a_row(engine, monkeypatch):
    monkeypatch.setattr(config, "HEALTH_TOKEN", "health-token-value-123456")
    secrets = {
        "note": "health-token-value-123456",
        "token": "tok_live_9f8e7d6c5b4a",
        "password": "hunter22hunter22",
        "webhook_url": "https://hooks.slack.com/services/T000/B000/XXXX",
        "ncrp_ack": "31234567890123",
        "case_reference": "FIR 214/2026 Cyber PS",
        "said": "Authorization: Bearer abcdefghijklmnop.qrstuv",
        "link": "see https://discord.com/api/webhooks/1/abc",
        "number": "complaint 31234567890123 was filed",
        "wallet": "0x" + "ab" * 20,
        "nested": {"api_key": "k" * 30, "list": ["https://example.org/x?apikey=zzz"]},
        "format": "pdf",
    }
    audit.record("case.report_export", case_id="c1", detail=secrets)
    stored = rows(engine)[0]
    blob = json.dumps(stored)
    for leaked in ("health-token-value-123456", "tok_live_9f8e7d6c5b4a", "hunter22", "hooks.slack.com",
                   "31234567890123", "FIR 214", "abcdefghijklmnop", "discord.com", "ab" * 20, "k" * 30,
                   "example.org", "zzz"):
        assert leaked not in blob, leaked
    detail = json.loads(stored["detail"])
    assert detail["format"] == "pdf"  # ordinary detail is kept as it was
    assert audit.verify()["ok"] is True  # and the redacted row still verifies


def test_no_detail_value_reaches_the_log(engine, monkeypatch, caplog):
    """The log line names the event, the case and a hash of the stored
    detail; tokens, passwords, NCRP numbers and case references stay out of
    it, and so does every ordinary value. The table keeps the cleaned detail."""
    monkeypatch.setattr(config, "HEALTH_TOKEN", "health-token-value-123456")
    values = {
        "token": "tok_live_9f8e7d6c5b4a",
        "password": "hunter22hunter22",
        "new_password": "Correct-Horse-9",
        "api_key": "k" * 30,
        "session": "sess-5f3a",
        "note": "health-token-value-123456",
        "said": "Authorization: Bearer abcdefghijklmnop.qrstuv",
        "ncrp_ack": "31234567890123",
        "complaint_no": 31234567890124,
        "case_reference": "FIR 214/2026 Cyber PS",
        "reference": "CMP-7Q4X",
        "nested": {"secret": "s3cr3t-v4lue", "list": ["https://example.org/x?apikey=zzz"]},
        "format": "pdf-a",
    }
    with caplog.at_level("DEBUG"):
        audit.record("case.report_export", case_id="c1", detail=values)
    stored = rows(engine)[0]
    [line] = [r.getMessage() for r in caplog.records if r.name == "exchequer.audit"]
    assert line == f"audit case.report_export case=c1 detail={short_hash(stored['detail'])}"
    for leaked in ("tok_live", "hunter22", "Correct-Horse", "k" * 30, "sess-5f3a", "health-token-value",
                   "abcdefghijklmnop", "31234567890123", "31234567890124", "FIR 214", "CMP-7Q4X", "s3cr3t",
                   "example.org", "zzz", "pdf-a"):
        assert leaked not in caplog.text, leaked
        if leaked != "pdf-a":  # an ordinary value is kept in the row, and only there
            assert leaked not in stored["detail"], leaked
    assert json.loads(stored["detail"])["format"] == "pdf-a"


def test_a_row_that_cannot_be_stored_logs_no_detail(engine, monkeypatch, caplog):
    """A store error can quote the statement's parameters (the detail): the
    error line names the event and the kind of error, not the message."""
    def refuse(action, case_id, detail):
        raise RuntimeError(f"insert failed [parameters: {detail}]")
    monkeypatch.setattr(audit, "_append", refuse)
    with caplog.at_level("DEBUG"):
        audit.record("case.report_export", case_id="c1", detail={"format": "pdf-a", "token": "tok_live_9f8e7d6c5b4a"})
    assert "could not be stored" in caplog.text and "RuntimeError" in caplog.text
    assert "pdf-a" not in caplog.text and "tok_live" not in caplog.text and "<redacted>" not in caplog.text


def test_a_flag_under_a_secret_sounding_key_is_kept(engine):
    """A boolean cannot carry a secret: whether a watch posts to a webhook is kept."""
    audit.record("watch.create", detail={"webhook": False, "token": True, "webhook_url": "https://x.example/h"})
    assert json.loads(rows(engine)[0]["detail"]) == {"webhook": False, "token": True, "webhook_url": "<redacted>"}


def test_an_id_with_an_all_digit_last_group_is_kept_whole(engine):
    wid = "5b0c7f2e-1111-2222-3333-444455556666"
    audit.record("watch.delete", detail={"watch_id": wid, "said": "complaint 31234567890123"})
    detail = json.loads(rows(engine)[0]["detail"])
    assert detail == {"watch_id": wid, "said": "complaint <number>"}


@pytest.mark.parametrize("case_id", ["ncrp-31234567890123", "31234567890123", "x" * 37, "1234567890123" + "x" * 5000,
                                     "FIR 214/2026", "https://example.org/x"],
                         ids=["ncrp-in-id", "ncrp", "too-long", "5013-chars", "fir", "url"])
def test_a_case_id_that_is_not_an_id_is_never_stored(engine, case_id):
    audit.record("case.report_export", case_id=case_id, detail={"format": "pdf"})
    row = rows(engine)[0]
    assert row["case_id"] is None
    assert case_id not in json.dumps(row)
    assert audit.verify()["ok"] is True


@pytest.mark.parametrize("case_id", ["5b0c7f2e-1111-2222-3333-444455556666", "demo-11", "case-1"])
def test_a_real_case_id_is_stored(engine, case_id):
    audit.record("case.report_export", case_id=case_id, detail={"format": "pdf"})
    assert rows(engine)[0]["case_id"] == case_id


def test_reads_that_change_nothing_are_log_lines_not_rows(engine, caplog):
    """Anyone can send these without a code or a limit: a row each would let a
    loop grow the permanent table, and its oldest rows can never be pruned."""
    models.save_case("case-1", "0xseed", {"chain": "ethereum"}, owner_hash=OWNER)
    client = TestClient(app)
    with caplog.at_level("INFO", logger="exchequer.audit"):
        for _ in range(20):
            assert client.get("/requests").status_code == 200
        assert client.get("/trace/" + "1234567890123" + "x" * 500 + "/requests").status_code == 200
        assert client.get("/trace/case-1/letters", headers=HEADERS).status_code == 200
        assert client.get("/trace/case-1/recheck", headers=HEADERS).status_code == 200
    assert rows(engine) == []
    assert "audit request.list" in caplog.text and "audit case.letters_list" in caplog.text


# -- who did it ----------------------------------------------------------------

def test_a_request_is_recorded_as_its_browser(engine):
    models.save_case("case-1", "0xseed", {"chain": "ethereum"}, owner_hash=OWNER)
    client = TestClient(app)
    assert client.get("/trace/case-1/graph", headers=HEADERS).status_code == 200
    assert client.get("/trace/case-1/graph").status_code == 200
    first, second = rows(engine)
    assert (first["actor"], first["unit_id"], first["action"], first["case_id"]) == \
        (f"demo:{OWNER}", "demo", "case.graph_export", "case-1")
    assert second["actor"] == "demo:anonymous"


def test_work_outside_a_request_is_the_systems(engine):
    audit.record("watch.check", detail={})
    assert (rows(engine)[0]["actor"], rows(engine)[0]["unit_id"]) == ("system", None)
    with audit.acting_as(OWNER):
        audit.record("case.trace", case_id="c1", detail={})
    assert rows(engine)[1]["actor"] == f"demo:{OWNER}"


# -- the endpoints ---------------------------------------------------------------

def test_verify_answers_only_the_health_token(engine, monkeypatch):
    client = TestClient(app)
    fill(3)
    monkeypatch.setattr(config, "HEALTH_TOKEN", "")
    assert client.get("/audit/verify").status_code == 404
    monkeypatch.setattr(config, "HEALTH_TOKEN", "operator-token-0123456789")
    assert client.get("/audit/verify").status_code == 401
    assert client.get("/audit/verify", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/audit/verify", headers=HEADERS).status_code == 401  # an owner key is not enough
    ok = client.get("/audit/verify", headers={"Authorization": "Bearer operator-token-0123456789"})
    assert ok.status_code == 200
    assert ok.json() == {"ok": True, "rows": 3, "first_bad_seq": None}


def test_a_cases_events_go_to_its_owner_only(engine):
    models.save_case("case-1", "0xseed", {"chain": "ethereum"}, owner_hash=OWNER)
    models.save_case("case-2", "0xseed", {"chain": "ethereum"}, owner_hash=OWNER)
    audit.record("case.report_export", case_id="case-1", detail={"format": "pdf"})
    audit.record("case.report_export", case_id="case-2", detail={"format": "text"})
    audit.record("case.letter_draft", case_id="case-1", detail={"to": "exchange"})
    client = TestClient(app)

    mine = client.get("/audit?case_id=case-1", headers=HEADERS)
    assert mine.status_code == 200
    body = mine.json()
    assert body["case_id"] == "case-1" and body["count"] == 2
    assert [(e["seq"], e["action"], e["detail"]) for e in body["events"]] == [
        (1, "case.report_export", {"format": "pdf"}), (3, "case.letter_draft", {"to": "exchange"})]
    assert {"at", "actor", "prev_hash", "row_hash"} <= set(body["events"][0])

    assert client.get("/audit?case_id=case-1", headers={ownership.OWNER_HEADER: "b" * 32}).status_code == 403
    assert client.get("/audit?case_id=case-1").status_code == 403
    assert client.get("/audit?case_id=nope", headers=HEADERS).status_code == 404
    assert client.get("/audit", headers=HEADERS).status_code == 422


def test_a_cases_owner_never_learns_who_else_opened_it(engine):
    models.save_case("case-1", "0xseed", {"chain": "ethereum"}, owner_hash=OWNER)
    client = TestClient(app)
    assert client.get("/trace/case-1/graph", headers=HEADERS).status_code == 200
    assert client.get("/trace/case-1/graph", headers={ownership.OWNER_HEADER: "b" * 32}).status_code == 200
    assert client.get("/trace/case-1/graph").status_code == 200
    audit.record("case.recheck", case_id="case-1", detail={})  # outside a request: the system's
    events = client.get("/audit?case_id=case-1", headers=HEADERS).json()["events"]
    assert [e["actor"] for e in events] == [f"demo:{OWNER}", "another browser", "another browser", "system"]
    assert ownership.owner_hash("b" * 32) not in json.dumps(events)
    assert audit.verify()["ok"] is True  # the stored rows keep their real actor
