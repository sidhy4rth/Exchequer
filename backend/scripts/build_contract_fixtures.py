"""Builds the case-contract fixtures from the recorded demos.

    python -m scripts.build_contract_fixtures            # from backend/

Lanes B and C build against these files instead of waiting for Lane A's code:
each is a real recorded trace, upgraded to contract v2 (app/contracts). They are
generated, never edited by hand. The rule that picks them: for every
(attribution kind, source) the demos contain, the first outgoing demo that has
it, plus the first outgoing demo that reaches no exchange.

The demos are data/recorded_demos.json, except that demo 3 is read from
tests/fixtures/recorded_demo3_2026-10-14_usdt_follow_on.json: the old demo 3
as recorded on 14 Oct 2026, kept when the shipped demo 3 moved to another
wallet (#284), so the fixtures and their readers' tests stay as they were.
index.json names it under "pinned_recordings".

A kind no recorded demo reaches has no fixture, and the index says so; a
made-up case would let a reader's tests pass against data the tool never
produced. `tests/test_contract.py` fails if these files drift from what this
script would write.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

from app.contracts import read_case, upgrade
from app.contracts.case_v2 import AttributionKind

BACKEND = Path(__file__).resolve().parent.parent
DEMOS = BACKEND / "data" / "recorded_demos.json"
OUT = BACKEND / "tests" / "fixtures" / "contract"
SWAP_RECORDING = BACKEND / "tests" / "fixtures" / "recorded_demo3_2026-10-14_usdt_follow_on.json"
PINNED = {3: SWAP_RECORDING}


def load_demos() -> list[dict[str, Any]]:
    """The demos the fixtures are built from: recorded_demos.json, with each
    pinned demo's row read from its own recording instead."""
    pinned = {row["demo"]: row for path in PINNED.values()
              for row in json.loads(path.read_text(encoding="utf-8"))}
    return [pinned.get(entry["demo"], entry) for entry in json.loads(DEMOS.read_text())]


def build(demos: list[dict[str, Any]]) -> dict[str, Any]:
    """{file name: content}, including index.json. Pure, for the drift test."""
    files: dict[str, Any] = {}
    index: dict[str, Any] = {"generated_from": "backend/data/recorded_demos.json",
                             "pinned_recordings": {str(n): f"backend/{path.relative_to(BACKEND).as_posix()}"
                                                   for n, path in sorted(PINNED.items())},
                             "fixtures": {}, "kinds_without_a_recorded_example": []}
    seen_kinds: set[str] = set()
    for entry in demos:
        result = entry["result"]
        if result.get("direction", "outgoing") != "outgoing":
            continue
        case = read_case(result)
        attr = case.attribution
        if attr is None:
            name = "no_attribution.json"
        else:
            seen_kinds.add(attr.kind)
            name = f"{attr.kind}.json" if attr.source in ("label_file", "inference") \
                else f"{attr.kind}.{attr.source}.json"
        if name in files:
            continue
        files[name] = upgrade(result)
        index["fixtures"][name] = {
            "demo": entry["demo"],
            "recorded_at": entry.get("recorded_at"),
            "kind": attr.kind if attr else None,
            "source": attr.source if attr else None,
            "exchange": attr.exchange if attr else None,
            "label": attr.label if attr else None,
        }
    index["kinds_without_a_recorded_example"] = sorted(
        set(get_args(AttributionKind)) - seen_kinds)
    files["index.json"] = index
    return files


def dumps(content: Any) -> str:
    return json.dumps(content, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    files = build(load_demos())
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.json"):
        if stale.name not in files:
            stale.unlink()
    for name, content in files.items():
        (OUT / name).write_text(dumps(content))
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
