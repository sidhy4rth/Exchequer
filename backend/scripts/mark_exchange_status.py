"""Mark the labels of closed and closing exchanges, from data/exchange_status.json.

Every label of an exchange listed there ends in "(defunct)" or "(winding
down)" in every exchange label file, so a trace, a report and a letter all
show it where they show the label (app/exchange_status.py says why). A label
of an exchange no longer listed loses the mark. Changing nothing else, it can
be re-run after any import; each file's _meta says how many labels it marks.

    cd backend && .venv/bin/python -m scripts.mark_exchange_status --dry-run
    cd backend && .venv/bin/python -m scripts.mark_exchange_status
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, exchange_status  # noqa: E402
from scripts.clean_exchange_labels import _indent, _write  # noqa: E402

META_KEY = "exchange_status"


def mark(document: dict[str, Any]) -> Counter:
    """Mark one label document in place; returns {exchange: labels changed}."""
    changed: Counter = Counter()
    for address, entry in document["labels"].items():
        if address.startswith("_") or not isinstance(entry, dict) or not isinstance(entry.get("label"), str):
            continue
        new = exchange_status.marked(entry["label"], entry.get("exchange"))
        if new != entry["label"]:
            entry["label"] = new
            changed[entry.get("exchange")] += 1
    return changed


def _summary(document: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(e.get("exchange") for e in document["labels"].values()
                     if isinstance(e, dict) and exchange_status.status(e.get("exchange")))
    return {"source": "data/exchange_status.json, applied by scripts/mark_exchange_status.py",
            "labels": {name: counts[name] for name in sorted(counts)}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    for chain in config.CHAINS.values():
        text = chain.labels_path.read_text(encoding="utf-8")
        document = json.loads(text)
        changed = mark(document)
        summary = _summary(document)
        print(f"{chain.key:9} {sum(changed.values()):3} labels changed; marked now: {summary['labels']}")
        if args.dry_run or (not changed and document["_meta"].get(META_KEY) == summary):
            continue
        if summary["labels"]:
            document["_meta"][META_KEY] = summary
        else:
            document["_meta"].pop(META_KEY, None)
        _write(chain.labels_path, document, _indent(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
