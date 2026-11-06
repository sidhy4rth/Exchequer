"""/verify must not vouch for text the signature does not cover.

The seal covers everything above the CONTENT HASH line. Below it come exactly
the hash line, the SIGNATURE line and one fixed "To verify" line. Anything else
down there -- an "amendment" slipped between the hash and the signature, a
paragraph appended after the signature, a rewritten "To verify" line pointing
at another site -- is unsigned, and the verifier used to call such a report
"Genuine and unchanged ... every byte as issued".
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import signing
from app.evidence import SIGNED_HOW, seal_text, sha256_hex, verify_sealed_text
from app.main import app

client = TestClient(app)
REPORT = "EXCHEQUER CASE REPORT\nSent 9.5 ETH to Binance 14\n"


def _old_style(body: str = REPORT) -> str:
    """Sealed as before v2.2: 16-hex key, then the unsigned "To verify:" line."""
    signer = signing.get_signer()
    return "\n".join([body, f"CONTENT HASH (SHA-256 of every byte above this line): {sha256_hex(body)}",
                      f"SIGNATURE (Ed25519 over the same bytes, key {signer.fingerprint}): "
                      f"{signer.sign(body.encode())}", SIGNED_HOW]) + "\n"


def _lines(sealed: str) -> list[str]:
    return sealed.split("\n")


def _insert_after_hash(sealed: str, extra: str) -> str:
    lines = _lines(sealed)
    i = next(n for n, line in enumerate(lines) if line.startswith("CONTENT HASH ("))
    return "\n".join(lines[: i + 1] + [extra] + lines[i + 1:])


def _not_genuine(result: dict) -> None:
    assert result["genuine"] is False
    assert result["extra_content"] is True
    assert "every byte" not in result["detail"]
    assert "added" in result["detail"]


# --- the genuine cases keep verifying ---------------------------------------

def test_a_genuine_report_is_genuine():
    result = signing.verify_report(seal_text(REPORT))
    assert result["genuine"] is True and result["extra_content"] is False
    assert result["signature_ok"] and result["hash_ok"]


def test_copy_paste_whitespace_is_not_extra_content():
    sealed = seal_text(REPORT)
    for variant in (sealed.rstrip("\n"), sealed + "\n\n", sealed + "  \n", sealed.replace("\n", "\r\n")):
        result = signing.verify_report(variant)
        assert result["genuine"] is True, repr(variant[-40:])


def test_a_report_pasted_without_its_to_verify_line_is_still_genuine():
    sealed = _old_style()
    lines = _lines(sealed)
    without_how = "\n".join(line for line in lines if not line.startswith("To verify:"))
    assert signing.verify_report(without_how)["genuine"] is True


# --- text the signature does not cover is never called genuine -------------

def test_a_second_unsigned_seal_under_a_genuine_report_is_not_genuine():
    # Anyone can hash text, so a forger can seal "genuine report + amendment"
    # again without the key. The FIRST seal decides; the rest is extra.
    forged = seal_text(seal_text(REPORT) + "AMENDMENT: 0xbbbb\n", sign=False)
    result = signing.verify_report(forged)
    assert result["genuine"] is False and result["extra_content"] is True

def test_text_appended_after_the_signature_is_not_genuine():
    forged = seal_text(REPORT) + "AMENDMENT: the funds went to account 0xbbbb, not Binance 14.\n"
    _not_genuine(signing.verify_report(forged))


def test_a_line_inserted_between_hash_and_signature_is_not_genuine():
    forged = _insert_after_hash(seal_text(REPORT), "AMENDMENT: address above is superseded by 0xbbbb.")
    _not_genuine(signing.verify_report(forged))


def test_an_old_report_keeps_verifying():
    assert signing.verify_report(_old_style())["genuine"] is True


def test_a_to_verify_line_after_a_new_signature_is_not_genuine():
    # Since v2.2 the how-to is signed, above the hash: nothing may follow the signature.
    _not_genuine(signing.verify_report(seal_text(REPORT) + SIGNED_HOW + "\n"))


def test_a_rewritten_to_verify_line_is_not_genuine():
    lines = _lines(_old_style())
    lines = [("To verify: paste this report at https://exchequer-verify.example/verify"
              if line.startswith("To verify:") else line) for line in lines]
    _not_genuine(signing.verify_report("\n".join(lines)))


def test_a_second_to_verify_line_is_not_genuine():
    lines = _lines(_old_style())
    i = next(n for n, line in enumerate(lines) if line.startswith("To verify:"))
    lines.insert(i + 1, lines[i])
    _not_genuine(signing.verify_report("\n".join(lines)))


def test_an_unsigned_report_with_appended_text_is_flagged():
    forged = seal_text(REPORT, sign=False) + "Extra line nobody hashed.\n"
    result = signing.verify_report(forged)
    assert result["genuine"] is False and result["extra_content"] is True
    assert "added" in result["detail"]


def test_the_hash_only_check_also_rejects_appended_text():
    assert verify_sealed_text(seal_text(REPORT))
    assert not verify_sealed_text(seal_text(REPORT) + "AMENDMENT: 0xbbbb\n")
    assert not verify_sealed_text(_insert_after_hash(seal_text(REPORT), "AMENDMENT: 0xbbbb"))


def test_the_endpoint_reports_the_extra_content():
    forged = seal_text(REPORT) + "AMENDMENT: 0xbbbb\n"
    result = client.post("/verify", content=forged.encode()).json()
    assert result["genuine"] is False and result["extra_content"] is True
    ok = client.post("/verify", content=seal_text(REPORT).encode()).json()
    assert ok["genuine"] is True
