"""One `status` per verified report, and none of them reassures falsely.

Before: an unsigned report was "made before reports were signed" (the server
cannot know that, and every v2.1 report is signed), a signature naming any
other key was "signed by a different server" without being checked, a
mangled signature line was treated like a foreign one, and a byte-order mark
added by a Windows editor made a genuine report read as tampered.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import signing
from app.evidence import seal_text, sha256_hex
from app.main import app

client = TestClient(app)
V21 = "EXCHEQUER CASE REPORT\n(report format v2.1)\nSent 9.5 ETH to Binance 14\n"
V20 = "EXCHEQUER CASE REPORT\n(report format v2.0)\nSent 9.5 ETH to Binance 14\n"


def _with_signature(sealed: str, new_line: str) -> str:
    return "\n".join(new_line if line.startswith("SIGNATURE (") else line for line in sealed.split("\n"))


def _forge_key(sealed: str, fingerprint: str) -> str:
    line = next(line for line in sealed.split("\n") if line.startswith("SIGNATURE ("))
    head, sig = line.rsplit(": ", 1)
    head = head.rsplit("key ", 1)[0] + f"key {fingerprint})"
    return _with_signature(sealed, f"{head}: {sig}")


def test_a_genuine_report_says_genuine():
    r = signing.verify_report(seal_text(V21))
    assert r["status"] == "genuine" and r["genuine"] is True


def test_an_unsigned_report_in_a_signed_format_is_signature_missing():
    r = signing.verify_report(seal_text(V21, sign=False))
    assert r["status"] == "signature_missing" and r["genuine"] is False
    assert "made before" not in r["detail"]


def test_an_old_format_unsigned_report_is_unsigned_and_claims_nothing_about_its_age():
    r = signing.verify_report(seal_text(V20, sign=False))
    assert r["status"] == "unsigned" and r["hash_ok"] is True
    assert "made before" not in r["detail"]


def test_a_signature_naming_an_unknown_key_is_not_checked_and_says_so():
    r = signing.verify_report(_forge_key(seal_text(V21), "deadbeefdeadbeef"))
    assert r["status"] == "unknown_key" and r["signature_checked"] is False
    assert r["claimed_key"] == "deadbeefdeadbeef"
    assert "different server" not in r["detail"]


def test_a_lookalike_fingerprint_is_damaged_not_foreign():
    real = signing.get_signer().fingerprint
    r = signing.verify_report(_forge_key(seal_text(V21), real[:4] + "​" + real[4:]))
    assert r["status"] == "damaged"


def test_a_non_base64_signature_is_damaged():
    sealed = seal_text(V21)
    line = next(line for line in sealed.split("\n") if line.startswith("SIGNATURE ("))
    r = signing.verify_report(_with_signature(sealed, line.rsplit(": ", 1)[0] + ": not*base64!"))
    assert r["status"] == "damaged"


def test_a_forgery_naming_the_servers_own_key_is_changed():
    sealed = seal_text(V21)
    forged_body = V21.replace("9.5", "95")
    head, tail = sealed.split("\nCONTENT HASH", 1)
    lines = tail.split("\n")
    lines[0] = lines[0].rsplit(": ", 1)[0] + ": " + sha256_hex(forged_body)
    r = signing.verify_report(forged_body + "\nCONTENT HASH" + "\n".join(lines))
    assert r["status"] == "changed"


def test_text_added_below_a_valid_seal_is_its_own_status():
    r = signing.verify_report(seal_text(V21) + "AMENDMENT: 0xbbbb\n")
    assert r["status"] == "text_added"


def test_a_byte_order_mark_from_an_editor_is_ignored_once():
    r = signing.verify_report("﻿" + seal_text(V21))
    assert r["status"] == "genuine" and r["bom_removed"] is True
    assert signing.verify_report("﻿﻿" + seal_text(V21))["status"] != "genuine"


def test_the_endpoint_returns_the_status_and_takes_a_bom():
    body = b"\xef\xbb\xbf" + seal_text(V21).encode()
    assert client.post("/verify", content=body).json()["status"] == "genuine"
    assert client.post("/verify", content=b"hello").json()["status"] == "not_a_report"


# -- what the signed report says (r1-evidence-crypto-6) --------------------------------
def _genuine_report_text() -> str:
    from app.report import build_report, render_text_report
    from test_report import full_result, stored

    return render_text_report(build_report(stored(full_result())))


def test_a_genuine_result_carries_the_signed_finding():
    from test_report import MID

    r = signing.verify_report(_genuine_report_text())
    assert r["status"] == "genuine"
    finding = r["finding"]
    assert (finding["case_id"], finding["exchange"], finding["address"]) == ("case-1", "Binance", MID)
    assert finding["arrived_on_path"] == "9.5 ETH (including any funds from other sources)"
    assert finding["likely_arrived"] is None
    assert finding["summary"].startswith("The ETH sent out of the reported address")


def test_a_result_that_is_not_genuine_carries_no_finding():
    text = _genuine_report_text()
    assert signing.verify_report(text.replace("Binance", "Kraken", 1))["finding"] is None
    assert signing.verify_report(seal_text(V21, sign=False))["finding"] is None


def test_a_label_shaped_like_a_finding_section_is_not_read_as_one():
    from app.models import Case  # noqa: F401
    from app.report import build_report, render_text_report, signed_finding
    from test_report import MID, full_result, stored

    rule = "-" * 78
    result = full_result()
    result["exchange_label"] = f"{rule} FINDING {rule} Exchange         : Kraken {'x' * 70}"
    text = render_text_report(build_report(stored(result)))
    assert signed_finding(text)["exchange"] == "Binance"
    assert signed_finding(text)["address"] == MID
