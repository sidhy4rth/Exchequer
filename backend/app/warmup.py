"""Trace the demo addresses in the background at startup, so they are warm.

On the free tiers a first trace of an address is as slow as the provider
allows -- twenty to forty seconds for the flagship demo -- and every later
trace of the same address is instant because its responses are cached. On a
hosted instance that means whoever opens a demo first after a redeploy pays
the cold cost, and if that is a judge the tool looks slow for a reason that
has nothing to do with the tool.

So, when EXCHEQUER_WARM_CACHE is on, a daemon thread runs each entry of
data/demo_traces.json through the same code path as POST /trace, stores
nothing, and lets the response cache (which persists to disk) fill. It then
sleeps for most of the cache TTL and does it again, so a long-running
instance never lets the demos go cold. A request that arrives while the
warm-up is running shares the credential's rate with it -- the pacer makes
sure neither trips the limit -- so a trace during those first minutes is
slower than usual; /health shows whether the warm-up is still in progress.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from . import config
from .models import utc_now_iso

logger = logging.getLogger(__name__)

DEMO_TRACES_PATH = config.DATA_DIR / "demo_traces.json"

_state: dict[str, Any] = {
    "enabled": False,
    "in_progress": False,
    "runs_completed": 0,
    "last_started_at": None,
    "last_completed_at": None,
    "last_run": [],  # one line per demo: address, seconds, outcome
}
_lock = threading.Lock()


def status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def load_demo_requests() -> list[dict[str, Any]]:
    try:
        return json.loads(DEMO_TRACES_PATH.read_text())
    except (OSError, ValueError) as exc:
        logger.warning("No demo traces to warm (%s): %s", DEMO_TRACES_PATH, exc)
        return []


def warm_once() -> list[dict[str, Any]]:
    """Run every demo trace once, storing nothing. Returns one record each."""
    # Imported here: main imports this module, and the warm-up needs main's
    # run_trace, so the import has to wait until both modules exist.
    from .main import TraceRequest, run_trace

    records: list[dict[str, Any]] = []
    for seed in load_demo_requests():
        started = time.monotonic()
        record = {"address": seed.get("address"), "chain": seed.get("chain"),
                  "direction": seed.get("direction"), "max_depth": seed.get("max_depth")}
        try:
            result = run_trace(TraceRequest(**seed))
            record.update(
                ok=True, seconds=round(time.monotonic() - started, 1),
                exchange=result.get("exchange"),
                from_cache=(result.get("evidence") or {}).get("from_cache"),
                retrieved=(result.get("evidence") or {}).get("retrieved"),
            )
        except Exception as exc:  # noqa: BLE001 -- one cold demo must not stop the rest
            record.update(ok=False, seconds=round(time.monotonic() - started, 1), error=str(exc)[:200])
            logger.warning("Warm-up trace of %s failed: %s", seed.get("address"), exc)
        records.append(record)
        logger.info(
            "Warm-up: %s %s d%s in %ss (%s)", record["address"], record["direction"],
            record["max_depth"], record["seconds"],
            "ok" if record.get("ok") else "failed",
        )
    return records


def _loop(interval: float) -> None:
    while True:
        with _lock:
            _state["in_progress"] = True
            _state["last_started_at"] = utc_now_iso()
        try:
            records = warm_once()
        finally:
            with _lock:
                _state["in_progress"] = False
                _state["runs_completed"] += 1
                _state["last_completed_at"] = utc_now_iso()
                _state["last_run"] = records
        logger.info("Warm-up complete: %d demo traces; next in %.0f minutes",
                    len(records), interval / 60)
        time.sleep(interval)


def start_in_background() -> bool:
    """Start the warm-up thread if it is configured on. Returns whether it did."""
    if not config.WARM_CACHE_AT_STARTUP:
        return False
    if not load_demo_requests():
        return False
    with _lock:
        _state["enabled"] = True
    # Re-warm at three quarters of the TTL so nothing expires between runs.
    interval = max(config.API_CACHE_TTL_SECONDS * 0.75, 300.0)
    thread = threading.Thread(target=_loop, args=(interval,), name="warmup", daemon=True)
    thread.start()
    logger.info("Warming the response cache from %s in the background", DEMO_TRACES_PATH)
    return True
