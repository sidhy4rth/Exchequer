"""The draft s.63(4) certificate (app/certificates.py): suite feature 6, issue #112.

An electronic record goes to court with the certificate in the Schedule of the
Bharatiya Sakshya Adhiniyam, 2023. Part A is the party's, Part B the expert's.
The draft takes its wording from the Act (data/bsa_schedule_certificate.txt,
written by scripts/fetch_bsa_schedule.py from India Code), fills Part A from
the exhibit register and what the officer typed, leaves Part B for the expert,
and encloses the hash report. It is a draft for signature, never more.
"""
from __future__ import annotations

import io
import re
from datetime import date

import pytest
from pypdf import PdfReader
from sqlalchemy import create_engine

from app import certificates, exhibits, models, ownership
from app.auth import User
from app.certificates import CertificateError

ALICE, BOB = "a" * 32, "b" * 32
SHA256 = "9f" * 32
SHA1 = "1a" * 20
MD5 = "5d" * 16
SEED = "abandon ability able about above absent absorb abstract absurd abuse access accident"


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True))
    monkeypatch.setattr(exhibits, "_today", lambda: date(2026, 11, 13))
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})
    models.save_case("case-2", "0xother", {"address": "0xother"})


def viewer(key=ALICE, unit=None):
    return User(id="demo", role="officer", unit=None, owner_hash=ownership.owner_hash(key), demo=True,
                officer_id=None, unit_id=unit)


def add(case="case-1", who=None, **over):
    who = who or viewer()
    fields = {"kind": "phone_extraction", "label": "Accused's phone", "tool": "Cellebrite UFED 7.69",
              "file_name": "A54_full.ufdr", "size_bytes": 64_000_000_000, "sha256": SHA256, "made_by": "SI Iyer",
              "made_on": "2026-11-12", "stored_at": "Evidence room, shelf 3", "holder": "SI Iyer"}
    fields.update(over)
    return exhibits.create(who.owner_hash, case, fields, who)["exhibit_id"]


DEVICE = {"device": "Mobile", "make_model": "Samsung Galaxy A54", "color": "Black", "serial": "R58T12ABC",
          "device_id": "IMEI 356789104567890"}


def text(ids, details=None, who=None, case="case-1"):
    return certificates.as_text(certificates.draft(case, ids, DEVICE if details is None else details, who or viewer()))


def part(out, name):
    a, b = out.index("PART A"), out.index("PART B")
    return out[a:b] if name == "A" else out[b:out.index("HASH REPORT")]


# -- the wording ------------------------------------------------------------------------------------
def test_the_wording_is_the_schedule_from_india_code_with_its_source():
    meta, lines = certificates.schedule()
    assert meta["source"].startswith("https://www.indiacode.nic.in/")
    assert re.fullmatch(r"[0-9a-f]{64}", meta["source_pdf_sha-256"])
    assert meta["text_as_on"]
    for must in ("THE SCHEDULE", "[See section 63(4)(c)]", "CERTIFICATE", "(To be filled by the Party)",
                 "(To be filled by the Expert)", "(Hash report to be enclosed with the certificate)"):
        assert must in lines


def test_every_line_keeps_the_schedules_own_words_and_only_its_blanks_are_filled():
    _, lines = certificates.schedule()
    dr = certificates.draft("case-1", [add(sha1=SHA1)], {**DEVICE, "other_info": "screen cracked"}, viewer())
    assert len(dr["lines"]) == len(lines)
    letters = lambda s: re.sub(r"[^A-Za-z0-9]", "", s)  # noqa: E731
    for (_, segments), line in zip(dr["lines"], lines, strict=True):
        schedule_words = "".join(s[1] for s in segments if s[0] == "t")
        assert letters(schedule_words) == letters(line), line


# -- Part A -------------------------------------------------------------------------------------------
def test_part_a_ticks_the_device_and_writes_what_the_officer_typed():
    a = part(text([add()]), "A")
    assert "Mobile [x]" in a  # the Schedule puts each box after its label
    assert "Computer / Storage Media [ ]" in a and "Cloud [ ]" in a
    assert "Samsung Galaxy A54" in a and "Black" in a and "R58T12ABC" in a and "IMEI 356789104567890" in a


def test_part_a_ticks_only_the_algorithms_on_record_with_their_values():
    a = part(text([add()]), "A")
    assert f"[x] SHA256: {SHA256}" in a
    assert "[ ] SHA1:" in a and "[ ] MD5:" in a and "[ ] Other" in a


def test_all_three_hashes_are_ticked_when_the_tool_gave_them():
    a = part(text([add(sha1=SHA1, md5=MD5)]), "A")
    assert f"[x] SHA1: {SHA1}" in a and f"[x] SHA256: {SHA256}" in a and f"[x] MD5: {MD5}" in a


def test_what_was_not_typed_stays_blank_for_a_pen():
    a = part(text([add()], {"device": "Mobile"}), "A")
    assert re.search(r"Make & Model: _{5,}", a) and re.search(r"Serial Number: _{5,}", a)
    assert re.search(r"I, _{5,} \(Name\)", a)  # the person's name is always written by hand
    assert "Owned [ ] Maintained [ ] Managed [ ] Operated [ ]" in a  # nothing chosen, nothing ticked


def test_who_controls_the_device_is_ticked_only_as_chosen():
    a = part(text([add()], {**DEVICE, "control": ["Maintained"]}), "A")
    assert "Owned [ ] Maintained [x] Managed [ ] Operated [ ]" in a


def test_several_records_point_to_the_enclosed_hash_report():
    first, second = add(), add(label="Laptop SSD", kind="disk_image", sha256="ab" * 32, md5=MD5)
    out = text([first, second])
    assert "listed in the enclosed hash report (2 records)" in part(out, "A")
    report = out[out.index("HASH REPORT"):]
    assert SHA256 in report and "ab" * 32 in report and MD5 in report
    assert report.index("Accused's phone") < report.index("Laptop SSD")


def test_the_hash_report_carries_the_tool_the_maker_and_the_chain_of_custody():
    eid = add()
    exhibits.update(eid, {"holder": "Insp. Rao", "note": "for the s.63 certificate"}, viewer())
    exhibits.check(eid, SHA256, viewer())
    report = text([eid])[text([eid]).index("HASH REPORT"):]
    for want in ("Cellebrite UFED 7.69", "SI Iyer", "2026-11-12", "64,000,000,000 bytes", "holder changed",
                 "for the s.63 certificate", "file checked: match"):
        assert want in report


# -- Part B and what the draft never says ----------------------------------------------------------------
def test_part_b_is_left_exactly_as_the_schedule_has_it():
    _, lines = certificates.schedule()
    expected = "\n".join(lines[lines.index("PART B"):]).replace("□", "[ ]").replace("Operated[ ]", "Operated [ ]")
    assert part(text([add(sha1=SHA1)]), "B").strip() == expected.strip()


def test_the_draft_says_it_is_a_draft_and_never_certified_or_admissible():
    out = text([add()])
    assert "DRAFT" in out and "not valid until" in out
    assert not re.search(r"certified|admissib|court-ready|guarantee", out, re.I)


# -- what is refused ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("ids, details, why", [
    ([], DEVICE, "at least one exhibit"),
    (["nope"], DEVICE, "No exhibit"),
    (None, {**DEVICE, "device": "Phone booth"}, "kind of device"),
    (None, {**DEVICE, "control": ["Stolen"]}, "Owned, Maintained"),
    (None, {**DEVICE, "make_model": "x" * 121}, "longer than"),
    (None, {**DEVICE, "other_info": SEED}, "seed phrase"),
])
def test_bad_requests_are_refused_with_a_reason(ids, details, why):
    with pytest.raises(CertificateError, match=why):
        certificates.draft("case-1", [add()] if ids is None else ids, details, viewer())


def test_another_browsers_or_cases_exhibit_is_not_found():
    theirs = add(who=viewer(BOB))
    other_case = add(case="case-2")
    for eid, case in ((theirs, "case-1"), (other_case, "case-1")):
        with pytest.raises(CertificateError, match="No exhibit"):
            certificates.draft(case, [eid], DEVICE, viewer())


def test_a_unit_colleague_can_draft_for_the_units_exhibits():
    eid = add(who=viewer(ALICE, unit=7))
    assert SHA256 in text([eid], who=viewer(BOB, unit=7))


# -- the PDF -------------------------------------------------------------------------------------------------
def test_the_pdf_holds_the_wording_the_values_and_the_draft_mark():
    pdf = certificates.render_pdf(certificates.draft("case-1", [add()], DEVICE, viewer()))
    assert pdf.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(pdf))
    got = re.sub(r"\s+", "", "".join(page.extract_text() for page in reader.pages))
    for want in ("PARTA", "(TobefilledbytheParty)", "PARTB", "(TobefilledbytheExpert)", SHA256, "SamsungGalaxyA54",
                 "DRAFT", "HASHREPORT"):
        assert want in got
    assert reader.metadata.title.startswith("Draft certificate")
