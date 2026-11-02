"""The audit trail: what was done to which case.

Every action that reads, exports or changes a case records it:

    from .. import audit

    audit.record("case.export", case_id=case_id, detail={"format": "pdf"})

For now this writes one log line. R24 makes it an append-only, hash-chained
log; the call stays the same, so nothing that calls it changes then. Who did
it is not a parameter: R24 takes the caller from the request, so a route never
passes it and can never pass the wrong one.

The checks below are the ones R24's log will need, enforced already, so a
call it could not store fails in your tests today rather than in a pilot:
the event is dotted lower case (`case.export`, `watch.create`), and `detail`
is a JSON object.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("exchequer.audit")

_EVENT_RE = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")


def record(event: str, *, case_id: str | None = None, detail: dict[str, Any] | None = None) -> None:
    """Record that `event` happened, to `case_id` if it concerns one."""
    if not isinstance(event, str) or not _EVENT_RE.match(event):
        raise ValueError(f"Audit event {event!r} must be dotted lower case, like 'case.export'")
    if detail is not None and not isinstance(detail, dict):
        raise TypeError(f"Audit detail must be a dict, not {type(detail).__name__}")
    # Raises on anything JSON cannot hold (a datetime, NaN): R24 hashes this text.
    body = json.dumps(detail or {}, sort_keys=True, allow_nan=False)
    logger.info("audit %s case=%s detail=%s", event, case_id or "-", body)
