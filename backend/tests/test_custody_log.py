"""The signing log of a custody wallet (app/custody_log.py, routes/custody.py): suite feature 9.

Every deposit into and release out of a custody wallet is a record: proposed,
approved by `threshold` distinct signers, broadcast with its transaction hash,
then confirmed or cancelled. A release needs the court's order. The same signer
never counts twice, and the proposer counts only if the scheme allows it. Each
step is entered by a signed-in officer; the signatures happen on the signers'
hardware wallets and never reach the server. Throwaway SQLite, no network.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm.exc import StaleDataError

from app import accounts, config, custody, custody_log, models, ownership, rate_limit
from app.auth import User
from app.custody import CustodyError
from app.main import app

ALICE, BOB = "a" * 32, "b" * 32
TX, TX2 = "ab" * 32, "cd" * 32
TX3, TX4, TX5 = "ef" * 32, "12" * 32, "34" * 32
CUSTODY = "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU"  # the custody address test_assets.py uses
OUT = "TA6SbszfFYC7NYt48viCM9LMD5F5E1Gbi8"  # from the recorded demo 12 fixture: any valid Tron address will do
SEED = "abandon ability able about above absent absorb abstract absurd abuse access accident"
SIGNERS = [{"name": "Insp. Rao"}, {"name": "SI Iyer"}, {"name": "SI Pal"}]


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'l.db'}", future=True))
    monkeypatch.setattr(custody, "_today", lambda: date(2026, 11, 14))
    models.init_db()
    models.save_case("case-1", "0xseed", {"address": "0xseed"})


def viewer(key=ALICE, unit=None, officer=1):
    return User(id=f"officer-{officer}" if officer else "demo", role="officer", unit="Cyber Cell",
                owner_hash=ownership.owner_hash(key), demo=officer is None, officer_id=officer, unit_id=unit)


def wallet(who=None, **over):
    fields = {"chain": "tron", "address": CUSTODY, "scheme": "Tron multi-sign permission", "threshold": 2,
              "signers": SIGNERS, "set_up_by": "Insp. Rao", "set_up_on": "2026-11-10", **over}
    who = who or viewer()
    return custody.create(who.owner_hash, "case-1", fields, who)["wallet_id"]


def release(wid, **over):
    fields = {"kind": "release", "asset": "USDT", "amount": "635.5", "destination": OUT,
              "order_ref": "Order of the court dated 2026-11-13", "proposed_by": "Insp. Rao", **over}
    return custody_log.propose(wid, fields, viewer())


def approve(mid, signer, who=None):
    return custody_log.step(mid, "approve", {"signer": signer}, who or viewer())


def deposited(wid, amount, tx, asset="USDT"):
    """A deposit into the wallet, proposed, broadcast and confirmed."""
    m = custody_log.propose(wid, {"kind": "deposit", "asset": asset, "amount": amount, "proposed_by": "SI Iyer"},
                            viewer())
    custody_log.step(m["movement_id"], "broadcast", {"tx_hash": tx}, viewer())
    return custody_log.step(m["movement_id"], "confirm", {}, viewer())


def released(wid, amount, tx, **over):
    """A release out of the wallet, approved by two officers' entries and broadcast, not yet confirmed."""
    m = release(wid, amount=amount, **over)
    approve(m["movement_id"], "SI Iyer", viewer(officer=1))
    approve(m["movement_id"], "SI Pal", viewer(officer=2))
    return custody_log.step(m["movement_id"], "broadcast", {"tx_hash": tx}, viewer())


# -- deposits and releases ---------------------------------------------------------------------
def test_a_deposit_goes_to_the_wallet_itself_and_needs_no_signatures():
    wid = wallet()
    m = custody_log.propose(wid, {"kind": "deposit", "asset": "USDT", "amount": "635", "proposed_by": "SI Iyer",
                                  "destination": OUT}, viewer())
    assert (m["destination"], m["status"], m["order_ref"]) == (CUSTODY, "proposed", "")
    m = custody_log.step(m["movement_id"], "broadcast", {"tx_hash": TX.upper()}, viewer())
    assert (m["status"], m["tx_hash"]) == ("broadcast", TX)
    assert custody_log.step(m["movement_id"], "confirm", {}, viewer())["status"] == "confirmed"


def test_a_release_runs_proposed_approved_broadcast_confirmed():
    wid = wallet()
    deposited(wid, "635.5", TX3)
    m = release(wid)
    assert (m["status"], m["amount"], m["approvals_needed"]) == ("proposed", "635.5", 2)
    m = approve(m["movement_id"], "SI Iyer")
    assert (m["status"], m["approvals_needed"]) == ("proposed", 1)
    m = approve(m["movement_id"], "si pal", viewer(officer=2))
    assert m["status"] == "approved"
    assert [(a["signer"], a["recorded_by"]) for a in m["approvals"]] == [("SI Iyer", "officer-1"), ("SI Pal", "officer-2")]
    assert all(a["at"] for a in m["approvals"])
    m = custody_log.step(m["movement_id"], "broadcast", {"tx_hash": TX}, viewer())
    m = custody_log.step(m["movement_id"], "confirm", {}, viewer())
    assert [h["status"] for h in m["history"]] == ["proposed", "proposed", "approved", "broadcast", "confirmed"]


def test_a_release_without_the_courts_order_is_refused():
    with pytest.raises(CustodyError, match="court's order"):
        release(wallet(), order_ref="")


@pytest.mark.parametrize("over, why", [
    ({"destination": "TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBV"}, "T followed by 33"),
    ({"destination": CUSTODY}, "not back into it"),
    ({"kind": "transfer"}, "deposit or a release"),
    ({"amount": "-5"}, "more than zero"),
    ({"amount": "lots"}, "as a number"),
    ({"asset": ""}, "the asset"),
    ({"proposed_by": ""}, "who proposed it"),
])
def test_a_malformed_proposal_is_refused(over, why):
    with pytest.raises(CustodyError, match=why):
        release(wallet(), **over)


@pytest.mark.parametrize("field", ["proposed_by", "order_ref", "destination"])
def test_a_seed_phrase_or_key_in_a_proposal_is_refused(field):
    secret = "0x" + "4c" * 32 if field == "destination" else SEED
    with pytest.raises(CustodyError, match="private key or seed phrase"):
        release(wallet(), **{field: secret})


# -- signers ----------------------------------------------------------------------------------
def test_the_same_signer_never_counts_twice():
    m = release(wallet())
    approve(m["movement_id"], "SI Iyer")
    with pytest.raises(CustodyError, match="already approved"):
        approve(m["movement_id"], "  si   IYER ", viewer(officer=2))
    assert custody_log.by_wallet(viewer(), "case-1")[m["wallet_id"]][0]["status"] == "proposed"


def test_only_a_listed_signer_can_approve():
    m = release(wallet())
    with pytest.raises(CustodyError, match="listed signers"):
        approve(m["movement_id"], "Constable Das")


def test_the_proposer_signs_only_when_the_scheme_allows_it():
    m = release(wallet())
    with pytest.raises(CustodyError, match="does not let a proposer sign"):
        approve(m["movement_id"], "Insp. Rao")
    m = release(wallet(threshold=2, proposer_may_sign=True, address=OUT), destination=CUSTODY)
    assert approve(m["movement_id"], "Insp. Rao")["approvals"][0]["signer"] == "Insp. Rao"


def test_a_secret_typed_as_a_signer_is_refused():
    m = release(wallet())
    with pytest.raises(CustodyError, match="private key or seed phrase"):
        approve(m["movement_id"], SEED[:119])


# -- the order of steps -----------------------------------------------------------------------
def test_a_release_cannot_be_broadcast_before_enough_approvals():
    m = release(wallet())
    approve(m["movement_id"], "SI Iyer")
    with pytest.raises(CustodyError, match="needs 2 signers"):
        custody_log.step(m["movement_id"], "broadcast", {"tx_hash": TX}, viewer())


def test_steps_out_of_order_are_refused():
    m = release(wallet())
    with pytest.raises(CustodyError, match="cannot be confirmed"):
        custody_log.step(m["movement_id"], "confirm", {}, viewer())
    approve(m["movement_id"], "SI Iyer")
    approve(m["movement_id"], "SI Pal", viewer(officer=2))
    with pytest.raises(CustodyError, match="cannot be approved"):
        approve(m["movement_id"], "Insp. Rao")
    with pytest.raises(CustodyError, match="64 hexadecimal"):
        custody_log.step(m["movement_id"], "broadcast", {"tx_hash": "0x123"}, viewer())


def test_a_cancel_needs_a_reason_and_ends_the_movement():
    m = release(wallet())
    with pytest.raises(CustodyError, match="why it is cancelled"):
        custody_log.step(m["movement_id"], "cancel", {}, viewer())
    m = custody_log.step(m["movement_id"], "cancel", {"reason": "Order stayed on appeal"}, viewer())
    assert (m["status"], m["history"][-1]["reason"]) == ("cancelled", "Order stayed on appeal")
    for name, fields in (("approve", {"signer": "SI Iyer"}), ("broadcast", {"tx_hash": TX}), ("confirm", {})):
        with pytest.raises(CustodyError, match="is cancelled"):
            custody_log.step(m["movement_id"], name, fields, viewer())


def test_one_transaction_is_recorded_once_per_wallet():
    wid = wallet()
    first = custody_log.propose(wid, {"kind": "deposit", "asset": "USDT", "amount": "1", "proposed_by": "SI Iyer"},
                                viewer())
    second = custody_log.propose(wid, {"kind": "deposit", "asset": "USDT", "amount": "634", "proposed_by": "SI Iyer"},
                                 viewer())
    custody_log.step(first["movement_id"], "broadcast", {"tx_hash": TX}, viewer())
    with pytest.raises(CustodyError, match="already recorded"):
        custody_log.step(second["movement_id"], "broadcast", {"tx_hash": TX}, viewer())
    assert custody_log.step(second["movement_id"], "broadcast", {"tx_hash": TX2}, viewer())["status"] == "broadcast"


# -- who may write ----------------------------------------------------------------------------
def test_every_step_needs_a_signed_in_officer():
    wid = wallet()
    with pytest.raises(CustodyError, match="Sign in"):
        custody_log.propose(wid, {"kind": "deposit", "asset": "USDT", "amount": "1", "proposed_by": "x"},
                            viewer(officer=None))
    m = release(wid)
    with pytest.raises(CustodyError, match="Sign in"):
        approve(m["movement_id"], "SI Iyer", viewer(officer=None))


def test_strangers_see_nothing_and_change_nothing():
    m = release(wallet(who=viewer(unit=7)))
    stranger = viewer(BOB, officer=9)
    assert custody_log.by_wallet(stranger, "case-1") == {}
    assert approve(m["movement_id"], "SI Iyer", stranger) is None
    assert custody_log.propose(m["wallet_id"], {"kind": "deposit", "asset": "USDT", "amount": "1",
                                                "proposed_by": "x"}, stranger) is None
    assert approve(m["movement_id"], "SI Iyer", viewer(BOB, unit=7, officer=3))["approvals_needed"] == 1


def test_a_step_that_keeps_clashing_is_a_conflict_not_a_crash(monkeypatch):
    m = release(wallet())

    def clash(*args):
        raise StaleDataError("always")

    monkeypatch.setattr(custody_log, "_step_once", clash)
    with pytest.raises(custody.CustodyConflict):
        approve(m["movement_id"], "SI Iyer")


# -- routes ---------------------------------------------------------------------------------------
H = {ownership.OWNER_HEADER: ALICE, accounts.CSRF_HEADER: "1"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "CUSTODY_WALLETS", True)
    monkeypatch.setattr(accounts, "SCRYPT_N", 2**4)
    for limiter in rate_limit.LOGIN_LIMITS:
        limiter.reset()
    with TestClient(app, base_url="https://testserver") as c:
        unit = accounts.create_unit("Cyber Cell North")
        accounts.create_officer("officer@example.org", "Om Officer", unit.id, "officer", password="officer-password-long-2")
        accounts.create_officer("second@example.org", "Sita Second", unit.id, "officer", password="officer-password-long-2")
        assert c.post("/auth/login", json={"email": "officer@example.org", "password": "officer-password-long-2"},
                      headers=H).status_code == 200
        yield c


def made_wallet(c):
    body = {"chain": "tron", "address": CUSTODY, "scheme": "Tron multi-sign permission", "threshold": 2,
            "signers": SIGNERS, "set_up_by": "Insp. Rao", "set_up_on": "2026-11-10"}
    made = c.post("/trace/case-1/custody", json=body, headers=H)
    assert made.status_code == 201
    return made.json()["wallet_id"]


def test_the_routes_propose_approve_broadcast_and_list(client):
    wid = made_wallet(client)
    body = {"kind": "release", "asset": "USDT", "amount": "635", "destination": OUT, "order_ref": "Order 13 Nov",
            "proposed_by": "Insp. Rao"}
    m = client.post(f"/custody/{wid}/movements", json=body, headers=H)
    assert m.status_code == 201
    mid = m.json()["movement_id"]
    assert client.post(f"/custody/movements/{mid}/approve", json={"signer": "SI Iyer"}, headers=H).status_code == 200
    assert client.post(f"/custody/movements/{mid}/approve", json={"signer": "SI Iyer"}, headers=H).status_code == 400
    # One officer account enters one approval: the second signer's comes from another officer's account.
    same_officer = client.post(f"/custody/movements/{mid}/approve", json={"signer": "SI Pal"}, headers=H)
    assert same_officer.status_code == 400 and "their own approval" in same_officer.json()["detail"]
    with TestClient(app, base_url="https://testserver") as other:
        assert other.post("/auth/login", json={"email": "second@example.org", "password": "officer-password-long-2"},
                          headers=H).status_code == 200
        approved = other.post(f"/custody/movements/{mid}/approve", json={"signer": "SI Pal"}, headers=H).json()
    assert approved["status"] == "approved"
    assert client.post(f"/custody/movements/{mid}/broadcast", json={"tx_hash": TX}, headers=H).status_code == 200
    assert client.post(f"/custody/movements/{mid}/sign", json={}, headers=H).status_code == 404
    listed = client.get("/trace/case-1/custody", headers=H).json()
    assert [mv["status"] for mv in listed["wallets"][0]["movements"]] == ["broadcast"]


def test_the_routes_refuse_a_release_without_an_order_and_strangers(client):
    wid = made_wallet(client)
    body = {"kind": "release", "asset": "USDT", "amount": "635", "destination": OUT, "proposed_by": "Insp. Rao"}
    assert client.post(f"/custody/{wid}/movements", json=body, headers=H).status_code == 400
    assert client.post("/custody/nope/movements", json={**body, "order_ref": "x"}, headers=H).status_code == 404
    assert client.post("/custody/movements/nope/confirm", json={}, headers=H).status_code == 404


def test_switched_off_the_signing_log_refuses_every_write(client, monkeypatch):
    wid = made_wallet(client)
    monkeypatch.setattr(config, "CUSTODY_WALLETS", False)
    body = {"kind": "deposit", "asset": "USDT", "amount": "1", "proposed_by": "SI Iyer"}
    assert client.post(f"/custody/{wid}/movements", json=body, headers=H).status_code == 403
    assert client.post("/custody/movements/any/approve", json={"signer": "SI Iyer"}, headers=H).status_code == 403


def test_the_audit_log_records_steps_and_counts_never_names(client):
    wid = made_wallet(client)
    body = {"kind": "deposit", "asset": "USDT", "amount": "1", "proposed_by": "SI Iyer"}
    mid = client.post(f"/custody/{wid}/movements", json=body, headers=H).json()["movement_id"]
    client.post(f"/custody/movements/{mid}/approve", json={"signer": "Insp. Rao"}, headers=H)
    with models.session() as s:
        rows = s.scalars(select(models.AuditEvent).where(models.AuditEvent.action.like("custody.movement.%"))).all()
    assert [(r.action, json.loads(r.detail)) for r in rows] == [
        ("custody.movement.propose", {"wallet_id": wid, "movement_id": mid, "kind": "deposit"}),
        ("custody.movement.approve", {"movement_id": mid, "status": "proposed", "approvals": 1}),
    ]
    assert not any("Rao" in r.detail or "Iyer" in r.detail for r in rows)


def test_g7_custody_2_goes_down_and_up_again_keeping_the_wallets():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    release(wallet())
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with models._engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.downgrade(settings, "g7_custody_1")
    assert "custody_movements" not in set(inspect(models._engine).get_table_names())
    assert len(custody.list_for(viewer(), "case-1")) == 1
    models.init_db()
    assert "custody_movements" in set(inspect(models._engine).get_table_names())
    unique = [i for i in inspect(models._engine).get_indexes("custody_movements") if i["unique"]]
    assert [i["column_names"] for i in unique] == [["wallet_id", "tx_hash"]]


def test_an_amount_too_long_for_its_column_is_refused_not_a_server_error():
    # amount is String(48): Postgres refuses a longer value, so it must be refused here first.
    with pytest.raises(CustodyError, match="digits"):
        release(wallet(), amount="0." + "0" * 60 + "1")
    assert release(wallet(address=OUT), destination=CUSTODY, amount="1." + "0" * 40)["amount"]


def test_a_proposer_who_is_a_signer_cannot_leave_too_few_signers_to_approve():
    two_of_two = wallet(signers=SIGNERS[:2])
    with pytest.raises(CustodyError, match="never reach"):
        release(two_of_two, proposed_by="insp.  rao")
    assert release(two_of_two, proposed_by="SI Pal")["status"] == "proposed"  # not a signer: both may approve
    assert release(wallet(address=OUT), destination=CUSTODY, proposed_by="Insp. Rao")["status"] == "proposed"  # 2 of 3


# -- who proposes ----------------------------------------------------------------------------
def test_a_signer_proposing_is_stored_by_the_name_the_wallet_lists_so_the_no_self_approval_rule_holds():
    m = release(wallet(), proposed_by="  insp.   RAO ")
    assert m["proposed_by"] == "Insp. Rao"
    with pytest.raises(CustodyError, match="does not let a proposer sign"):
        approve(m["movement_id"], "Insp. Rao")


def test_where_a_proposer_may_sign_the_proposer_is_one_of_the_signers():
    wid = wallet(proposer_may_sign=True)
    with pytest.raises(CustodyError, match="choose the proposer from its signers"):
        release(wid, proposed_by="Constable Das")
    assert release(wid, proposed_by="si pal")["proposed_by"] == "SI Pal"


def test_where_a_proposer_may_not_sign_someone_who_is_not_a_signer_may_propose():
    assert release(wallet(), proposed_by="Constable Das")["proposed_by"] == "Constable Das"


# -- what goes out is no more than what came in ----------------------------------------------
def test_a_release_is_never_confirmed_beyond_the_confirmed_deposits_of_its_asset():
    wid = wallet()
    deposited(wid, "100", TX)
    deposited(wid, "1000", TX2, asset="TRX")  # another asset: never counts towards USDT
    first = released(wid, "60.5", TX3)
    assert custody_log.step(first["movement_id"], "confirm", {}, viewer())["status"] == "confirmed"
    second = released(wid, "39.6", TX4)
    with pytest.raises(CustodyError, match="more USDT than"):
        custody_log.step(second["movement_id"], "confirm", {}, viewer())
    assert custody_log.by_wallet(viewer(), "case-1")[wid][-1]["status"] == "broadcast"
    third = released(wid, "39.5", TX5, asset="usdt")  # the same asset however it is typed
    assert custody_log.step(third["movement_id"], "confirm", {}, viewer())["status"] == "confirmed"


def test_a_release_with_nothing_deposited_is_never_confirmed():
    m = released(wallet(), "1", TX)
    with pytest.raises(CustodyError, match="more USDT than"):
        custody_log.step(m["movement_id"], "confirm", {}, viewer())


def test_a_release_proposed_beyond_the_deposits_is_recorded_with_a_warning():
    wid = wallet()
    deposited(wid, "100", TX)
    assert release(wid, amount="100")["warnings"] == []
    m = release(wid, amount="100.01")
    assert m["status"] == "proposed"
    assert any("more USDT than" in w for w in m["warnings"])


def test_amounts_that_cannot_be_compared_warn_and_never_refuse():
    wid = wallet()
    deposited(wid, "100", TX, asset="USDT-TRC20")  # a different spelling: not the same asset to compare
    m = released(wid, "50", TX2)
    confirmed = custody_log.step(m["movement_id"], "confirm", {}, viewer())
    assert confirmed["status"] == "confirmed"
    assert any("could not be compared" in w for w in confirmed["warnings"])
    with models.session() as s:  # a stored amount that is not a decimal: compared nowhere, warned about
        row = s.scalars(select(models.CustodyMovement).where(models.CustodyMovement.tx_hash == TX)).one()
        row.amount, row.asset = "about 100", "USDT"
        s.commit()
    m = released(wid, "50", TX3)
    confirmed = custody_log.step(m["movement_id"], "confirm", {}, viewer())
    assert confirmed["status"] == "confirmed"
    assert any("could not be compared" in w for w in confirmed["warnings"])


def test_long_amounts_add_up_exactly():
    wid = wallet()
    deposited(wid, "0." + "0" * 30 + "3", TX)
    m = released(wid, "0." + "0" * 30 + "2", TX2)
    assert custody_log.step(m["movement_id"], "confirm", {}, viewer())["status"] == "confirmed"
    m = released(wid, "0." + "0" * 30 + "2", TX3)
    with pytest.raises(CustodyError, match="more USDT than"):
        custody_log.step(m["movement_id"], "confirm", {}, viewer())


# -- one transaction, one live movement ---------------------------------------------------------
def test_a_cancelled_movements_hash_can_be_recorded_again():
    wid = wallet()
    first = custody_log.propose(wid, {"kind": "deposit", "asset": "USDT", "amount": "1", "proposed_by": "SI Iyer"},
                                viewer())
    custody_log.step(first["movement_id"], "broadcast", {"tx_hash": TX}, viewer())
    custody_log.step(first["movement_id"], "cancel", {"reason": "Wrong amount entered"}, viewer())
    second = custody_log.propose(wid, {"kind": "deposit", "asset": "USDT", "amount": "2", "proposed_by": "SI Iyer"},
                                 viewer())
    assert custody_log.step(second["movement_id"], "broadcast", {"tx_hash": TX}, viewer())["tx_hash"] == TX


def test_two_broadcasts_racing_with_one_hash_cannot_both_land(monkeypatch):
    wid = wallet()
    one, two = (custody_log.propose(wid, {"kind": "deposit", "asset": "USDT", "amount": "1", "proposed_by": "SI Iyer"},
                                    viewer()) for _ in range(2))
    custody_log.step(one["movement_id"], "broadcast", {"tx_hash": TX}, viewer())
    monkeypatch.setattr(custody_log, "_twin", lambda *args: None)  # the other write has not committed yet
    with pytest.raises(CustodyError, match="already recorded"):
        custody_log.step(two["movement_id"], "broadcast", {"tx_hash": TX}, viewer())
    assert custody_log.by_wallet(viewer(), "case-1")[wid][1]["status"] == "proposed"


def test_the_store_itself_refuses_one_hash_twice_in_a_wallet_but_not_after_a_cancel():
    from sqlalchemy.exc import IntegrityError

    wid = wallet()
    ids = [custody_log.propose(wid, {"kind": "deposit", "asset": "USDT", "amount": "1", "proposed_by": "SI Iyer"},
                               viewer())["movement_id"] for _ in range(3)]
    with models.session() as s:
        rows = {r.id: r for r in s.scalars(select(models.CustodyMovement)).all()}
        rows[ids[0]].tx_hash, rows[ids[0]].status = TX, "cancelled"
        rows[ids[1]].tx_hash, rows[ids[1]].status = TX, "broadcast"
        s.commit()
        rows[ids[2]].tx_hash, rows[ids[2]].status = TX, "confirmed"
        with pytest.raises(IntegrityError):
            s.commit()


# -- one officer account, one approval ----------------------------------------------------------
def test_one_officer_account_records_at_most_one_approval_per_movement():
    m = release(wallet())
    approve(m["movement_id"], "SI Iyer", viewer(officer=1))
    with pytest.raises(CustodyError, match="their own approval"):
        approve(m["movement_id"], "SI Pal", viewer(officer=1))
    m = approve(m["movement_id"], "SI Pal", viewer(officer=2))
    assert (m["status"], [a["recorded_by"] for a in m["approvals"]]) == ("approved", ["officer-1", "officer-2"])


def test_confirming_a_release_writes_the_wallet_so_two_confirms_at_once_cannot_both_pass_the_check():
    wid = wallet()
    deposited(wid, "100", TX)

    def version():
        with models.session() as s:
            return s.scalars(select(models.CustodyWallet.row_version).where(models.CustodyWallet.id == wid)).one()

    m, before = released(wid, "60", TX2), version()
    custody_log.step(m["movement_id"], "confirm", {}, viewer())
    assert version() == before + 1  # a second confirm that read the old version is stale and checks again
