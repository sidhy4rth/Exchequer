"""The CFCFRMS SOP steps beside a case's records (app/sop_steps.py, the
/sop-steps routes in routes/sop_summary.py, flag EXCHEQUER_SOP_STEPS).

What must hold: with the flag off nothing answers; every step cites a section
and page and quotes the SOP; the quotes reused from the reviewed modules are
the same words; the case column says only what the case's own records show;
and no NCRP number or case reference is ever returned, logged or audited."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app import config, models, ownership, sop_reminders, sop_steps, sop_summary
from app.main import app

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contract"
ALICE = "a" * 32
OWNER = {ownership.OWNER_HEADER: ALICE}
NCRP = "31234567890123"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def by_id(out: dict) -> dict:
    return {s["id"]: s for s in out["steps"]}


def test_every_step_quotes_the_sop_with_a_section_and_a_page():
    out = sop_steps.steps(fixture("no_attribution"), [])
    assert [s["id"] for s in out["steps"]] == ["acknowledgement", "submit", "bank-notices", "fir", "vasp", "grievance"]
    for s in out["steps"]:
        assert s["cites"] and s["case"]
        for c in s["cites"]:
            assert c["section"].startswith(("§", "Annexure")) and isinstance(c["page"], int) and c["quote"]
    assert sop_reminders.SOP_URL in out["source"] and "Not applied to this case" in out["note"]


def test_the_reused_quotes_are_the_reviewed_words():
    steps = by_id(sop_steps.steps({}, []))
    reminders = {r["section"]: r["quote"] for r in sop_reminders.BANK_HOLD}
    for s in ("bank-notices", "grievance"):
        for c in steps[s]["cites"]:
            if c["section"] in reminders:
                assert c["quote"] == reminders[c["section"]]
    vasp = steps["vasp"]["cites"]
    assert f'SOP 9.4(ii): "{vasp[0]["quote"]}"' == sop_summary.ONBOARDED
    assert f'SOP 9.4(iv): "{vasp[1]["quote"]}"' == sop_summary.NOT_ONBOARDED


def test_the_acknowledgement_step_says_whether_a_usual_number_is_recorded_never_which():
    case = fixture("exchange_wallet")
    case["intake"]["ncrp_ack"] = NCRP
    out = sop_steps.steps(case, [])
    assert "records a number of the usual shape" in by_id(out)["acknowledgement"]["case"]
    assert NCRP not in json.dumps(out)
    case["intake"].update(ncrp_ack=None, case_ref="FIR 123/2026")  # an FIR number is not an NCRP number
    assert "records no number of that shape" in by_id(sop_steps.steps(case, []))["acknowledgement"]["case"]


def test_bank_holds_are_counted_from_the_register_and_other_rows_are_not():
    rows = [{"holder": "bank", "status": "held"}, {"holder": "bank", "status": "held"},
            {"holder": "bank", "status": "released"}, {"holder": "exchange", "status": "held"}]
    assert "records 2 bank holds still held" in by_id(sop_steps.steps({}, rows))["bank-notices"]["case"]
    assert "records no bank hold" in by_id(sop_steps.steps({}, rows[2:]))["bank-notices"]["case"]


def test_the_vasp_step_names_the_exchange_reached_and_stays_silent_when_none_was():
    case = fixture("exchange_wallet")
    shown = by_id(sop_steps.steps(case, []))["vasp"]["case"]
    assert f"attributed to {case['attribution']['exchange']}" in shown and "not a person" in shown
    assert "reached no exchange" in by_id(sop_steps.steps(fixture("no_attribution"), []))["vasp"]["case"]
    case["direction"] = "incoming"
    assert "names no exchange reached" in by_id(sop_steps.steps(case, []))["vasp"]["case"]


def test_steps_on_the_portal_say_exchequer_cannot_see_it():
    steps = by_id(sop_steps.steps(fixture("exchange_wallet"), []))
    assert steps["submit"]["case"] == steps["fir"]["case"] == steps["grievance"]["case"] == sop_steps.OFFICER


# -- the routes ----------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True))
    models.init_db()
    case = fixture("exchange_wallet")
    case["intake"]["ncrp_ack"] = NCRP
    models.save_case("case-1", case["address"], case, owner_hash=ownership.owner_hash(ALICE))
    return TestClient(app)


def audited(s) -> list:
    return s.scalars(select(models.AuditEvent).where(models.AuditEvent.action == "case.sop_steps_view")).all()


def test_with_the_flag_off_nothing_answers(client, monkeypatch):
    monkeypatch.setattr(config, "SOP_STEPS", False)
    assert client.get("/sop-steps").status_code == 404
    assert client.get("/trace/case-1/sop-steps", headers=OWNER).status_code == 404
    with models.session() as s:
        assert not audited(s)


def test_the_flag_is_off_by_default():
    assert config.FLAGS["EXCHEQUER_SOP_STEPS"]["on"] is False
    assert config.FLAGS["EXCHEQUER_SOP_STEPS"]["about"].startswith("Feature 8")


def test_with_the_flag_on_the_owner_gets_the_steps_audited_without_detail(client, monkeypatch, caplog):
    monkeypatch.setattr(config, "SOP_STEPS", True)
    caplog.set_level(logging.DEBUG)
    assert client.get("/sop-steps").json() == {"enabled": True}
    r = client.get("/trace/case-1/sop-steps", headers=OWNER)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert "records a number of the usual shape" in by_id(r.json())["acknowledgement"]["case"]
    assert NCRP not in r.text and NCRP not in caplog.text
    with models.session() as s:
        rows = audited(s)
        assert [(row.case_id, json.loads(row.detail or "{}")) for row in rows] == [("case-1", {})]


def test_another_reader_is_not_told_the_withheld_number_fits_and_an_unknown_case_is_404(client, monkeypatch):
    monkeypatch.setattr(config, "SOP_STEPS", True)
    other = client.get("/trace/case-1/sop-steps", headers={ownership.OWNER_HEADER: "b" * 32})
    assert other.status_code == 200 and "records no number of that shape" in other.text
    assert client.get("/trace/nope/sop-steps", headers=OWNER).status_code == 404
