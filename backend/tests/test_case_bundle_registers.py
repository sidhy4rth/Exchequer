"""The registers merged after the case bundle, in the bundle (app/case_bundle.py): suite feature 6, #186.

The task list, the custody wallets and their signing log (EXCHEQUER_CUSTODY_WALLETS),
the statement rows (EXCHEQUER_STATEMENT_IMPORT) and the CDR summaries
(EXCHEQUER_CDR_IMPORT), each as its own route lists it for the caller: their
browser's and unit's rows only, withdrawn imports left out, every cell through
the formula guard, MANIFEST.txt hashing each file. A register whose flag is off
is not in the bundle, its file list or MANIFEST.txt. Letters of request abroad
are requests, in requests.csv. Throwaway SQLite, no network; every number and
address below is the synthetic one the registers' own tests use.
"""
from __future__ import annotations

import csv
import hashlib
import io

import pytest

from app import case_bundle, cdr_imports, config, custody, custody_log, freeze_requests, statement_imports, tasks
import test_case_bundle
from test_case_bundle import BOB, HEAD, bundle, manifest_entries, viewer
from test_cdr_imports import NUMBER_ROW
from test_custody_log import CUSTODY, OUT, SIGNERS
from test_statement_imports import ACCOUNT, UTR_ROW

FLAGGED = {"CUSTODY_WALLETS": ["custody-wallets.csv", "custody-wallets-history.csv", "custody-signing-log.csv",
                               "custody-signing-log-history.csv"],
           "STATEMENT_IMPORT": ["statements.csv"], "CDR_IMPORT": ["cdr-summaries.csv"]}
WITHDRAWN = "entered against the wrong case"
client, engine = test_case_bundle.client, test_case_bundle.engine  # the bundle tests' fixtures


@pytest.fixture
def flags_on(monkeypatch):
    for name in FLAGGED:
        monkeypatch.setattr(config, name, True)


def rows(zf, name):
    return list(csv.DictReader(io.StringIO(zf.read(name).decode("utf-8-sig"))))


def other_unit():
    return viewer(BOB, unit=8, officer=4)


def a_wallet(who, address=CUSTODY):
    return custody.create(who.owner_hash, "case-1", {
        "chain": "tron", "address": address, "scheme": "Tron multi-sign permission", "threshold": 2,
        "signers": SIGNERS, "set_up_by": "Insp. Rao", "set_up_on": "2026-11-10"}, who)["wallet_id"]


def a_deposit(wallet_id, who):
    return custody_log.propose(wallet_id, {"kind": "deposit", "asset": "USDT", "amount": "100",
                                           "proposed_by": "SI Iyer"}, who)["movement_id"]


def save_statement(who, row=UTR_ROW):
    return statement_imports.create(who.owner_hash, "case-1", {"source": "bank", "currency": "INR", "rows": [row]},
                                    who)["import_id"]


def save_cdr(who, row=NUMBER_ROW):
    return cdr_imports.create(who.owner_hash, "case-1", {"rows": [row]}, who)["import_id"]


def test_a_register_whose_flag_is_off_is_not_in_the_bundle_its_file_list_or_its_manifest(client):
    zf = bundle(client)
    body = zf.read("MANIFEST.txt").decode()
    for files in FLAGGED.values():
        for name in files:
            assert name not in zf.namelist() and name not in case_bundle.names() and name not in body
    assert "custody" not in body.replace("exhibits-custody.csv", "") and "statement" not in body
    assert ["tasks.csv", "tasks-history.csv"] == [n for n in zf.namelist() if n.startswith("tasks")]  # no flag


@pytest.mark.parametrize("flag", sorted(FLAGGED))
def test_each_register_comes_in_with_its_own_flag_only(client, monkeypatch, flag):
    monkeypatch.setattr(config, flag, True)
    names = bundle(client).namelist()
    for other, files in FLAGGED.items():
        assert all((n in names) is (other == flag) for n in files), (flag, other)


def test_with_every_flag_on_the_files_come_in_a_fixed_order_and_the_manifest_hashes_match(client, flags_on):
    zf = bundle(client)
    expected = ["report.txt", "report.pdf", "exhibits.csv", "exhibits-custody.csv", "assets.csv",
                "assets-history.csv", "requests.csv", "requests-history.csv", "identifiers.csv",
                "identifiers-history.csv", "tasks.csv", "tasks-history.csv", *FLAGGED["CUSTODY_WALLETS"],
                "statements.csv", "cdr-summaries.csv", "audit-trail.csv", "MANIFEST.txt"]
    assert zf.namelist() == expected == case_bundle.names() == client.get("/case-bundle", headers=HEAD).json()["files"]
    entries, body = manifest_entries(zf)
    assert [name for name, _, _ in entries] == expected[:-1]
    for name, size, digest in entries:
        data = zf.read(name)
        assert (len(data), hashlib.sha256(data).hexdigest()) == (int(size), digest)
    assert "GET /trace/{id}/custody" in body and "GET /trace/{id}/statements" in body and "GET /trace/{id}/cdr" in body


def test_the_task_list_and_its_history_are_the_callers_own_and_their_cells_are_guarded(client):
    mine = tasks.create(viewer().owner_hash, "case-1", {"title": "=HYPERLINK(1)", "assignee": "SI Iyer"}, viewer())
    tasks.update(mine["task_id"], {"status": "done", "note": "notice sent"}, viewer())
    tasks.create(other_unit().owner_hash, "case-1", {"title": "Another unit's task"}, other_unit())
    zf = bundle(client)
    got = rows(zf, "tasks.csv")
    assert [(t["task_id"], t["title"], t["status"]) for t in got] == [(mine["task_id"], "'=HYPERLINK(1)", "done")]
    history = rows(zf, "tasks-history.csv")
    assert {h["task_id"] for h in history} == {mine["task_id"]} and history[0]["action"] == "added"
    assert len(history) == len(tasks.list_for(viewer(), "case-1")[0]["history"])
    assert "Another unit" not in zf.read("tasks-history.csv").decode("utf-8-sig")


def test_the_custody_wallets_and_signing_log_are_the_callers_own_wallet_by_wallet(client, flags_on):
    officer = viewer(officer=1)  # the browser that traced the case, signed in
    wid = a_wallet(officer)
    mid = a_deposit(wid, officer)
    theirs = a_wallet(other_unit(), OUT)
    a_deposit(theirs, other_unit())
    zf = bundle(client)
    wallets = rows(zf, "custody-wallets.csv")
    assert [(w["wallet_id"], w["address"], w["threshold"]) for w in wallets] == [(wid, CUSTODY, "2")]
    assert [h["action"] for h in rows(zf, "custody-wallets-history.csv")] == ["recorded"]
    log = rows(zf, "custody-signing-log.csv")
    assert [(m["movement_id"], m["wallet_id"], m["kind"], m["status"]) for m in log] == [(mid, wid, "deposit", "proposed")]
    assert [h["movement_id"] for h in rows(zf, "custody-signing-log-history.csv")] == [mid]
    assert theirs not in b"".join(zf.read(n) for n in zf.namelist()).decode("utf-8", "replace")


def test_statement_rows_are_one_line_each_as_the_register_shows_them_withdrawn_imports_left_out(client, flags_on):
    kept = save_statement(viewer())
    gone = save_statement(viewer())
    statement_imports.withdraw(viewer(), "case-1", gone, WITHDRAWN)
    save_statement(other_unit())
    zf = bundle(client)
    got = rows(zf, "statements.csv")
    shown = statement_imports.list_for(viewer(), "case-1")[0]["rows"][0]
    assert [(r["import_id"], r["row"], r["reference"], r["narration"]) for r in got] == [
        (kept, "1", shown["reference"], shown["narration"])]
    everything = b"".join(zf.read(n) for n in zf.namelist()).decode("utf-8", "replace")
    assert gone not in everything and WITHDRAWN not in everything
    assert everything.count(ACCOUNT) == 1  # only where the register itself shows it, in the kept row's narration


def test_cdr_summaries_are_the_callers_own_with_numbers_guarded_and_withdrawn_ones_left_out(client, flags_on):
    kept = save_cdr(viewer())
    gone = save_cdr(viewer())
    # One table: a CDR summary is withdrawn as a statement is (routes/cdr.py).
    statement_imports.withdraw(viewer(), "case-1", gone, WITHDRAWN, sources=(cdr_imports.SOURCE,),
                               summarise=cdr_imports.summary)
    save_cdr(other_unit())
    zf = bundle(client)
    got = rows(zf, "cdr-summaries.csv")
    assert [(r["import_id"], r["kind"], r["value"], r["calls"]) for r in got] == [
        (kept, "number", "'+447700900002", "12")]  # a + number reads '+ in the file, as MANIFEST.txt says
    everything = b"".join(zf.read(n) for n in zf.namelist()).decode("utf-8", "replace")
    assert gone not in everything and WITHDRAWN not in everything
    assert "statements.csv" in zf.namelist() and len(rows(zf, "statements.csv")) == 0  # a CDR is not a statement


def test_a_letter_of_request_abroad_is_in_the_requests_log(client):
    made = freeze_requests.create(viewer().owner_hash, "case-1", "Test Central Authority", "letter-rogatory",
                                  viewer=viewer())
    got = rows(bundle(client), "requests.csv")
    assert [(r["request_id"], r["kind"]) for r in got] == [(made["request_id"], "letter-rogatory")]
