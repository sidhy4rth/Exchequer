"""The offline build of the label store (scripts/build_label_store.py).

The store is private hunt data kept out of the public repository, so a build
that fails or is interrupted must leave nothing behind for a `git add` to pick up.
"""
from __future__ import annotations

import csv

import pytest

from scripts import build_label_store
from scripts.build_label_store import build

from conftest import addr

FIELDS = ["address", "chain", "category", "entity_or_incident", "sources", "source_refs", "date"]


def write_csv(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({**dict.fromkeys(FIELDS, ""), **r})
    return path


SCAM = {"address": addr("5ca33e"), "chain": "ethereum", "category": "phishing/scam",
        "entity_or_incident": "Inferno Drainer receiver", "sources": "Threat-intel report: Check Point"}


def test_an_interrupted_build_leaves_no_building_file(tmp_path, monkeypatch):
    src = write_csv(tmp_path / "flagged.csv", [SCAM])
    out = tmp_path / "data" / "label_store.db"
    out.parent.mkdir()
    real = build_label_store.iter_rows

    def interrupted(*args, **kwargs):
        yield from real(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(build_label_store, "iter_rows", interrupted)
    with pytest.raises(KeyboardInterrupt):
        build(src, out)
    assert not out.with_suffix(".building").exists() and not out.exists()


def test_a_source_the_rules_do_not_place_fails_the_build(tmp_path, capsys):
    """r1-labels-data-2: a row's tier comes from an allow-list of sources, so a new
    list must be placed there before its rows can ship."""
    blog = {**SCAM, "address": addr("b10c"), "sources": "Some blog post"}
    src = write_csv(tmp_path / "flagged.csv", [SCAM, blog])
    out = tmp_path / "label_store.db"
    assert build_label_store.main([str(src), "--out", str(out)]) == 1
    printed = capsys.readouterr().out
    assert "Some blog post" in printed
    assert not out.exists()  # nothing to release by mistake
    assert build_label_store.main([str(src), "--out", str(out), "--allow-unknown-sources"]) == 0
    assert out.exists()
