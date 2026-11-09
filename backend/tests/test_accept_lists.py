"""The list-refresh publish job commits lists and nothing else.

The job that downloads and parses the lists holds no write token any more;
it hands its files to a publish job that does (audit r1-ci-github-1). Before
committing, .github/scripts/accept_lists.py takes only files named as the
refreshed lists that read as lists. These run it on files written here.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from conftest import addr

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("accept_lists", ROOT / ".github" / "scripts" / "accept_lists.py")
accept_lists = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(accept_lists)

TRON = "TNPeeaaFB7K9cmo4uQpcU32zGK8G1NYqeL"


def entry(category: str = "sanctioned") -> dict:
    return {"category": category, "entity": "Someone", "label": "x", "source": "a list"}


def write(folder: Path, name: str, labels, meta: dict | None = None) -> Path:
    path = folder / name
    path.write_text(json.dumps({"_meta": meta or {"last_reviewed": "2026-11-06"}, "labels": labels}))
    return path


@pytest.fixture
def run(tmp_path):
    downloaded, data = tmp_path / "in", tmp_path / "data"
    downloaded.mkdir()
    data.mkdir()
    (downloaded / "lists.md").write_text("From the nightly list refresh.\n")
    body = tmp_path / "body.md"

    def go():
        return accept_lists.main([str(downloaded), str(data), str(body)]), data, body
    return downloaded, go


def test_refreshed_lists_are_taken_with_their_body(run):
    downloaded, go = run
    write(downloaded, "risk_labels.json", {addr("a"): entry(), "_note": "kept"})
    write(downloaded, "risk_labels_tron.json", {TRON: entry("seized")})
    write(downloaded, "frozen_labels_tron.json", {TRON: entry("frozen")})
    code, data, body = go()
    assert code == 0
    assert sorted(p.name for p in data.iterdir()) == ["frozen_labels_tron.json", "risk_labels.json",
                                                      "risk_labels_tron.json"]
    assert body.read_text() == "From the nightly list refresh.\n"


@pytest.mark.parametrize("name", ["exchange_labels.json", "main.py", "risk_labels.json.bak",
                                  "risk_labels_solana.json", "never_flag_tokens.json"])
def test_any_other_file_refuses_the_set(run, name, capsys):
    downloaded, go = run
    write(downloaded, "risk_labels.json", {addr("a"): entry()})
    write(downloaded, name, {addr("b"): entry()})
    code, data, _body = go()
    assert code == 1 and not list(data.iterdir())
    assert "::error::" in capsys.readouterr().out


def test_a_symlink_or_a_folder_refuses_the_set(run, tmp_path):
    downloaded, go = run
    target = write(tmp_path, "elsewhere.json", {addr("a"): entry()})
    os.symlink(target, downloaded / "risk_labels.json")
    (downloaded / "intl_sanctions.json").mkdir()
    code, data, _body = go()
    assert code == 1 and not list(data.iterdir())


@pytest.mark.parametrize("name, labels, why", [
    ("risk_labels.json", [addr("a")], "labels given as a list"),
    ("risk_labels.json", {"0x" + "Z" * 40: entry()}, "not hex"),
    ("risk_labels.json", {"0x" + "A" * 40: entry()}, "an address the matcher would never meet"),
    ("risk_labels.json", {TRON: entry()}, "a Tron wallet in an EVM file"),
    ("risk_labels_tron.json", {addr("a"): entry()}, "an EVM wallet in the Tron file"),
    ("risk_labels.json", {addr("a"): entry("exchange")}, "a category no list sets"),
    ("risk_labels.json", {addr("a"): {"category": "sanctioned"}}, "no entity"),
    ("risk_labels.json", {addr("a"): "sanctioned"}, "an entry that is not an object"),
])
def test_a_file_that_does_not_read_as_a_list_refuses_the_set(run, name, labels, why):
    downloaded, go = run
    write(downloaded, name, labels)
    code, data, _body = go()
    assert code == 1 and not list(data.iterdir()), why


def test_not_json_and_too_large_are_refused(run, monkeypatch):
    downloaded, go = run
    (downloaded / "risk_labels.json").write_text("<xml/>")
    assert go()[0] == 1
    write(downloaded, "risk_labels.json", {addr("a"): entry()})
    monkeypatch.setattr(accept_lists, "MAX_BYTES", 10)
    assert go()[0] == 1


def test_a_missing_body_or_no_list_refuses(run):
    downloaded, go = run
    assert go()[0] == 1  # the body alone: nothing to take
    write(downloaded, "risk_labels.json", {addr("a"): entry()})
    (downloaded / "lists.md").unlink()
    assert go()[0] == 1


def test_a_long_body_is_cut_to_what_a_pull_request_holds(run, monkeypatch):
    downloaded, go = run
    write(downloaded, "risk_labels.json", {addr("a"): entry()})
    (downloaded / "lists.md").write_text("x" * 70_000)
    code, _data, body = go()
    assert code == 0 and len(body.read_text()) < 61_000


def test_every_list_the_repository_ships_would_be_taken():
    """So the publish job never refuses today's lists, whatever category they use."""
    data = ROOT / "backend" / "data"
    shipped = sorted(p for p in data.iterdir() if accept_lists.NAME.fullmatch(p.name))
    assert len(shipped) >= 10
    for path in shipped:
        assert accept_lists.problem_with(path) is None, path.name
