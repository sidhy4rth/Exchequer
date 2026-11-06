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

    def interrupted(reader, skipped):
        yield from real(reader, skipped)
        raise KeyboardInterrupt

    monkeypatch.setattr(build_label_store, "iter_rows", interrupted)
    with pytest.raises(KeyboardInterrupt):
        build(src, out)
    assert not out.with_suffix(".building").exists() and not out.exists()
