"""GET /api/my-case and POST /api/messages: a signed-in citizen sees only
their own complaint, its coarse status and the messages, and can reply.
Nothing officer-only is ever in a citizen response."""
from __future__ import annotations

import json
import sqlite3

from conftest import NCRP, call, pack, sign_in, submit

OFFICER_ONLY = ("wallet_match", "match", "flag", "label", "exchange", "watch", "letter", "hit", "case_id",
                "ncrp", "client", "salt", "code_hash", "session")


def sql(db, statement, *params):
    con = sqlite3.connect(db)
    with con:
        con.execute(statement, params)
    con.close()


def keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from keys(v)


def test_my_case_shows_the_status_what_was_sent_and_the_messages(db):
    sent = submit()
    cookie = sign_in(NCRP, sent["tracking_code"])
    res = call("my-case", method="GET", cookie=cookie)
    assert res.status == 200 and res.headers["Cache-Control"] == "no-store"
    body = res.body
    assert body["reference"] == sent["reference"]
    assert body["status"] == {"key": "received", "text": "Received"}
    assert body["sent"]["story"] == "They said my money would double."
    assert body["payments"] == [{"hash": "ab" * 32, "amount": "9890.50", "token": "USDT",
                                 "network": "Tron (TRC20)", "paidAt": "2026-11-02 14:05",
                                 "wallet": "TJ" + "a" * 32}]
    assert body["messages"] == []


def test_the_status_is_one_of_four_coarse_words(db):
    cookie = sign_in(NCRP, submit()["tracking_code"])
    for stored, text in [("with_cell", "With a cyber cell"), ("investigating", "Under investigation"),
                         ("closed", "Closed"), ("spam-check", "Received")]:
        sql(db, "UPDATE complaints SET status = ?", stored)
        assert call("my-case", method="GET", cookie=cookie).body["status"]["text"] == text


def test_nothing_officer_only_reaches_the_citizen(db):
    first = submit()
    call("complaints", body=pack(ncrp="39999999999999", story="someone else"), client="198.51.100.9")
    sql(db, "UPDATE complaints SET wallet_match = 'case,complaint'")
    cookie = sign_in(NCRP, first["tracking_code"])
    body = call("my-case", method="GET", cookie=cookie).body
    found = {k.lower() for k in keys(body)}
    assert not {k for k in found for bad in OFFICER_ONLY if bad in k}, found
    text = json.dumps(body)
    assert "someone else" not in text and "complaint" not in text and "39999999999999" not in text


def test_officer_messages_and_replies_come_back_in_order(db):
    cookie = sign_in(NCRP, submit()["tracking_code"])
    [cid] = [r[0] for r in sqlite3.connect(db).execute("SELECT id FROM complaints")]
    sql(db, "INSERT INTO complaint_messages (id, complaint_id, sender, body, created_at) "
            "VALUES ('m1', ?, 'officer', 'Please bring your bank statement.', '2026-11-03T10:00:00+00:00')", cid)
    res = call("messages", body={"body": "  I will bring it on Monday.  "}, cookie=cookie)
    assert res.status == 201 and set(res.body) == {"sent"}
    messages = call("my-case", method="GET", cookie=cookie).body["messages"]
    assert [(m["from"], m["body"]) for m in messages] == [
        ("Cyber cell", "Please bring your bank statement."), ("You", "I will bring it on Monday.")]
    assert set(messages[0]) == {"from", "body", "at"}


def test_a_reply_needs_a_session_and_is_capped(db):
    cookie = sign_in(NCRP, submit()["tracking_code"])
    assert call("messages", body={"body": "hello"}).status == 401
    assert call("messages", body={"body": "x" * 2001}, cookie=cookie).status == 400
    assert call("messages", body={"body": "   "}, cookie=cookie).status == 400
    assert call("messages", body={"body": "hi", "to": "officer"}, cookie=cookie).status == 400
    assert call("messages", raw=b'{"body": "' + b"x" * 9000 + b'"}', cookie=cookie).status == 413


def test_replies_are_rate_limited(db):
    cookie = sign_in(NCRP, submit()["tracking_code"])
    statuses = [call("messages", body={"body": f"note {i}"}, cookie=cookie).status for i in range(12)]
    assert statuses[:10] == [201] * 10 and statuses[10] == 429


def test_my_case_needs_a_valid_session(db):
    submit()
    assert call("my-case", method="GET").status == 401
    assert call("my-case", method="GET", cookie="__Host-citizen=forged").status == 401
    assert call("my-case", method="POST", body={}).status == 405
