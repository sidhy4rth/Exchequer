"""What a running trace is doing, for the live progress view.

The pipeline and the graph builder call `report(...)` at the points a person
watching would care about -- which hop, how many addresses read, which
stage after the walk. Outside a background job nobody is listening and the
calls cost a context-variable lookup.

A context variable rather than a callback threaded through every function:
the walk is several calls deep, and progress is a side channel the trace's
own logic must never depend on.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable

Listener = Callable[[dict[str, Any]], None]

_listener: ContextVar[Listener | None] = ContextVar("trace_progress", default=None)


def listen(listener: Listener | None):
    """Route this context's reports to `listener`; returns a reset token."""
    return _listener.set(listener)


def stop(token) -> None:
    _listener.reset(token)


def report(**fields: Any) -> None:
    listener = _listener.get()
    if listener is not None:
        try:
            listener(fields)
        except Exception:  # noqa: BLE001 -- progress must never break a trace
            pass
