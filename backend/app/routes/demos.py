"""Recorded demos: each DEMO.md trace as it came out on the day it was recorded.

A live demo traces live data, and live data moves -- DEMO.md trace 3 changed
attribution six times. A recording is the answer the demo was written about,
frozen, so it can be shown beside the live trace and the two compared.

Recordings come from data/recorded_demos.json, written by
scripts/record_demos.py. They are deliberately not cases: a case is a
complaint, and twelve permanent demo rows would show up in every correlation
as repeat complaints that nobody made."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException

from .. import config

router = APIRouter()

RECORDED_DEMOS_PATH = config.DATA_DIR / "recorded_demos.json"


@lru_cache(maxsize=1)
def _recordings() -> dict[int, dict[str, Any]]:
    try:
        rows = json.loads(RECORDED_DEMOS_PATH.read_text())
    except (OSError, ValueError):
        return {}
    return {int(row["demo"]): row for row in rows}


@router.get("/demos/recorded")
def list_recorded() -> dict[str, Any]:
    """Which demos have a recording, and what each one found."""
    return {"demos": [
        {
            "demo": n,
            "recorded_at": row["recorded_at"],
            "address": row["result"].get("address"),
            "exchange": row["result"].get("exchange"),
            "confidence": row["result"].get("confidence"),
        }
        for n, row in sorted(_recordings().items())
    ]}


@router.get("/demos/recorded/{demo}")
def get_recorded(demo: int) -> dict[str, Any]:
    """One recorded demo, in the shape of a stored case but with no case id:
    nothing that writes to a case (watches, request logs, letters) applies."""
    row = _recordings().get(demo)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No recording for demo {demo}")
    return {**row["result"], "case_id": None, "created_at": row["recorded_at"],
            "recorded_demo": demo}
