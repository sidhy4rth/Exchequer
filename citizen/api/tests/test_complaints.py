"""POST /api/complaints: the pack's text fields and payments go into the
officers' queue; the reference and tracking code come back once."""
from __future__ import annotations

import json
import sqlite3

from conftest import CLIENT, NCRP, call, pack, submit

from _lib import codes


def rows(db, sql, *params):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()


def test_a_complaint_is_stored_and_its_code_shown_once(db):
    res = call("complaints", body=pack())
    assert res.status == 201
    assert set(res.body) == {"reference", "tracking_code"}
    code = res.body["tracking_code"]
    [row] = rows(db, "SELECT * FROM complaints")
    assert row["reference"] == res.body["reference"] and row["ncrp"] == NCRP
    assert row["status"] == "received" and row["wallet_match"] is None
    details = json.loads(row["details_json"])
    assert details["story"] == "They said my money would double." and "ncrp" not in details
    [pay] = rows(db, "SELECT * FROM complaint_payments")
    assert pay["tx_hash"] == "ab" * 32 and pay["amount"] == "9890.50" and pay["wallet"] == "TJ" + "a" * 32
    [kept] = rows(db, "SELECT * FROM tracking_codes")
    assert kept["ncrp"] == NCRP and codes.normalise(code) not in json.dumps(kept)
    assert codes.verify(code, kept["salt"], kept["code_hash"])
    assert code not in json.dumps(rows(db, "SELECT * FROM complaints"))


def test_a_0x_wallet_and_hash_are_kept_lowercased(db):
    submit(payments=[{"hash": "0x" + "AB" * 32, "network": "Ethereum (ERC20)", "wallet": "0x" + "CD" * 20}])
    [pay] = rows(db, "SELECT tx_hash, wallet FROM complaint_payments")
    assert pay == {"tx_hash": "0x" + "ab" * 32, "wallet": "0x" + "cd" * 20}


def test_the_ncrp_number_is_needed_and_checked(db):
    for bad in ("", "12 34", "x" * 40, None, 123):
        res = call("complaints", body=pack(ncrp=bad))
        assert res.status == 400 and "NCRP" in res.body["error"]
    assert call("complaints", body=pack(ncrp="3123-4567 890123")).status == 201


def test_screenshots_and_unknown_fields_are_refused(db):
    res = call("complaints", body=pack(files=["scam.png"]))
    assert res.status == 400 and "files" in res.body["error"]
    bad_pay = pack(payments=[{"hash": "ab" * 32, "screenshot": "data:image/png;base64,AAAA"}])
    assert call("complaints", body=bad_pay).status == 400
    assert not rows(db, "SELECT * FROM complaints")


def test_each_field_is_checked_and_capped(db):
    cases = [
        pack(story="x" * 5000), pack(name=["list"]), pack(mobile="12345"),
        pack(payments=[{"amount": "-5"}]), pack(payments=[{"hash": "zz" * 32, "network": "Tron (TRC20)"}]),
        pack(payments=[{"wallet": "ab" * 32, "network": "Tron (TRC20)"}]),
        pack(payments=[{"network": "Dogecoin"}]), pack(payments=[{}] * 21), pack(payments="nope"),
        pack(payments=[{"hash": "TxID " + "ab" * 32 + " then " + "cd" * 32, "network": "Tron (TRC20)"}]),
        pack(payments=[{"hash": "T" + "a" * 33, "network": "Another network"}]),
        pack(payments=[{"wallet": "TJ" + "a" * 32 + " extra", "network": "Tron (TRC20)"}]),
    ]
    for body in cases:
        res = call("complaints", body=body)
        assert res.status == 400, body
        assert isinstance(res.body["error"], str) and "Traceback" not in res.body["error"]
    assert not rows(db, "SELECT * FROM complaints")


def test_another_network_takes_a_hash_and_wallet_as_typed(db):
    submit(payments=[{"hash": "abcDEF123", "network": "Another network", "wallet": "bc1qxyz"}])
    [pay] = rows(db, "SELECT tx_hash, wallet FROM complaint_payments")
    assert pay == {"tx_hash": "abcDEF123", "wallet": "bc1qxyz"}


def test_control_characters_are_taken_out_of_text(db):
    submit(name="A\x00B‮C", story="line one\nline two\x07")
    details = json.loads(rows(db, "SELECT details_json FROM complaints")[0]["details_json"])
    assert details["name"] == "ABC" and details["story"] == "line one\nline two"


def test_empty_payments_are_left_off(db):
    submit(payments=[{"hash": "", "amount": " ", "wallet": ""}])
    assert rows(db, "SELECT * FROM complaint_payments") == []


def test_body_cap_header_and_content_type(db):
    assert call("complaints", raw=b"{" + b" " * 40_000 + b"}").status == 413
    assert call("complaints", body=pack(), headers={"x-citizen": None}).status == 403
    assert call("complaints", body=pack(), headers={"origin": "https://elsewhere.example"}).status == 403
    assert call("complaints", body=pack(), headers={"origin": "https://citizen.example"}).status == 201
    assert call("complaints", body=pack(), headers={"content-type": "text/plain"}).status == 415
    assert call("complaints", raw=b"not json").status == 400
    assert call("complaints", raw=b"[1, 2]").status == 400
    res = call("complaints", method="GET")
    assert res.status == 405 and res.headers["Allow"] == "POST"


def test_one_connection_can_send_only_a_few_complaints_a_day(db):
    for i in range(5):
        submit(ncrp=f"3{i:013d}")
    res = call("complaints", body=pack(ncrp="39999999999999"))
    assert res.status == 429 and int(res.headers["Retry-After"]) > 0
    assert call("complaints", body=pack(ncrp="39999999999999"), client="198.51.100.9").status == 201
    assert len(rows(db, "SELECT * FROM complaints")) == 6


def test_one_ncrp_number_takes_only_a_few_complaints_a_day_and_a_bounded_number_in_all(db, monkeypatch):
    from _lib import limits, web
    now = [1_800_000_000]
    monkeypatch.setattr(web, "now", lambda: now[0])
    per_day = limits.RATES["complaint-ncrp"][0]
    for i in range(per_day):
        assert call("complaints", body=pack(), client=f"198.51.100.{i}").status == 201
    res = call("complaints", body=pack(), client="198.51.100.200")  # a fresh connection: the number is what counts
    assert res.status == 429 and int(res.headers["Retry-After"]) > 0
    assert call("complaints", body=pack(ncrp="39999999999999"), client="198.51.100.200").status == 201
    sent, day = per_day, 0
    while sent < limits.CODES_PER_NCRP:
        now[0] += limits.WINDOW + 1
        day += 1
        for i in range(per_day):
            if sent < limits.CODES_PER_NCRP:
                assert call("complaints", body=pack(), client=f"198.51.{day}.{i}").status == 201
                sent += 1
    now[0] += limits.WINDOW + 1
    res = call("complaints", body=pack(), client="192.0.2.99")
    assert res.status == 409 and "1930" in res.body["error"]
    assert len(rows(db, "SELECT * FROM tracking_codes WHERE ncrp = ?", NCRP)) == limits.CODES_PER_NCRP


def test_a_hash_with_words_or_a_link_around_it_is_read_the_way_the_form_reads_it(db):
    tx = "ab" * 32
    link = "https://tronscan.org/#/transaction/" + tx.upper() + "?from=share&utm_source=wallet_app_" + "x" * 40
    sent = [{"hash": f"TxID: {tx}", "network": "Tron (TRC20)"},
            {"hash": link, "network": "Tron (TRC20)"},
            {"hash": f"{tx[:30]}\n{tx[30:]}", "network": "Tron (TRC20)"},
            {"hash": "Hash: 0x" + "CD" * 32, "network": "Ethereum (ERC20)",
             "wallet": "0x" + "ab" * 10 + " " + "ab" * 10},
            {"hash": "\u200b" + "ef" * 32, "network": "Tron (TRC20)", "wallet": " TJ" + "a" * 16 + " " + "a" * 16},
            {"hash": "abc DEF 123", "network": "Another network", "wallet": "bc1q xyz"}]
    submit(payments=sent)
    got = rows(db, "SELECT tx_hash, wallet FROM complaint_payments ORDER BY id")
    assert [g["tx_hash"] for g in got] == [tx, tx, tx, "0x" + "cd" * 32, "ef" * 32, "abcDEF123"]
    assert [g["wallet"] for g in got][3:] == ["0x" + "ab" * 20, "TJ" + "a" * 32, "bc1qxyz"]


def test_a_wallet_paid_in_another_complaint_is_flagged_for_officers_only(db):
    wallet = "TJ" + "a" * 32
    first = submit()
    second = call("complaints", body=pack(ncrp="39999999999999"), client="198.51.100.9")
    assert second.status == 201 and set(second.body) == {"reference", "tracking_code"}
    assert "match" not in json.dumps(second.body).lower()
    flags = {r["reference"]: r["wallet_match"] for r in rows(db, "SELECT reference, wallet_match FROM complaints")}
    assert flags == {first["reference"]: "complaint", second.body["reference"]: "complaint"}
    third = submit(payments=[{"wallet": "T" + "b" * 33, "network": "Tron (TRC20)"}])
    assert rows(db, "SELECT wallet_match FROM complaints WHERE reference = ?", third["reference"]) == [
        {"wallet_match": None}]
    assert wallet  # the shared wallet is never echoed back


def test_without_its_settings_the_site_says_it_cannot_take_complaints(db, monkeypatch):
    monkeypatch.delenv("CITIZEN_SECRET")
    res = call("complaints", body=pack())
    assert res.status == 503 and "right now" in res.body["error"]
    assert CLIENT not in json.dumps(res.body)
