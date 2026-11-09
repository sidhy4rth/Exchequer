"""Rendered reports, kept: a stored case never changes, so its first render is its report.

A PDF is the most expensive thing an anonymous visitor can ask this server for:
the report is rebuilt, signed, typeset by reportlab and rewritten by pypdf, about
a hundred times the cost of a plain page, on an instance with a tenth of a CPU.
Every request for one used to do all of that again, for any case id, public demo
ids included.

So the text report, the PDF and the graph exports of a case are rendered once
and kept (in memory, bounded in bytes), and every format carries the same `generated_at`:
later downloads are the same bytes, and the text, the JSON and the PDF's
attachment are one report. Only a PDF that is not kept yet costs a render, and
those are limited per client and site-wide and done one at a time; a text render
is cheap and is not limited. The key holds what changes the bytes: the case's
content, the report format, the signing key and the issuing URL.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Hashable

from . import config, rate_limit
from .models import Case

MAX_BYTES = 24 * 1024 * 1024
MAX_ITEM_BYTES = 4 * 1024 * 1024
GENERATED_AT_KEPT = 4096

# PDF renders a client, and the whole site, may cause per hour (cache misses only).
pdf_renders = rate_limit.SlidingWindowLimiter(20, 3600)
pdf_renders_total = rate_limit.SlidingWindowLimiter(120, 3600)
# One PDF typeset at a time; a second waiting would only queue behind it on the CPU.
render_slot = threading.BoundedSemaphore(1)


class RenderCache:
    """Least recently used first out, bounded in bytes; an item over max_item is never kept."""

    def __init__(self, max_bytes: int = MAX_BYTES, max_item: int = MAX_ITEM_BYTES) -> None:
        self.max_bytes = max_bytes
        self.max_item = max_item
        self.size = 0
        self._items: OrderedDict[Hashable, bytes | str] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _cost(value: bytes | str) -> int:
        return len(value) if isinstance(value, bytes) else len(value.encode("utf-8"))

    def pop(self, key: Hashable) -> None:
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self.size -= self._cost(old)

    def get(self, key: Hashable) -> bytes | str | None:
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key: Hashable, value: bytes | str) -> None:
        cost = self._cost(value)
        if cost > self.max_item:
            return
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self.size -= self._cost(old)
            self._items[key] = value
            self.size += cost
            while self.size > self.max_bytes and self._items:
                _, evicted = self._items.popitem(last=False)
                self.size -= self._cost(evicted)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self.size = 0


_cache = RenderCache()
_generated: OrderedDict[Hashable, str] = OrderedDict()
_generated_lock = threading.Lock()


def _case_key(case: Case) -> tuple[str, str, str]:
    """The case, by its content: an id alone could name a different case in another store."""
    digest = hashlib.blake2b((case.result_json or "").encode("utf-8"), digest_size=16).hexdigest()
    return case.id, str(case.created_at), digest


def _key(case: Case, kind: str) -> tuple[Any, ...]:
    return _key_for(_case_key(case), kind)


def _key_for(case_key: tuple[str, str, str], kind: str) -> tuple[Any, ...]:
    from .report import REPORT_VERSION
    from .signing import get_signer

    return (case_key, REPORT_VERSION, get_signer().fingerprint_sha256, config.PUBLIC_URL, kind)


# The renders that print generated_at; graph exports do not.
_DATED = ("text", "pdf")


def generated_at(case: Case) -> str:
    """When this case's report was first rendered here; every format reuses it."""
    key = _case_key(case)
    with _generated_lock:
        when = _generated.get(key)
        if when is None:
            when = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
            _generated[key] = when
            while len(_generated) > GENERATED_AT_KEPT:
                forgotten, _ = _generated.popitem(last=False)
                # Its kept text and PDF carry the time just forgotten: drop
                # them, so the next render of every format shares a new one.
                for kind in _DATED:
                    _cache.pop(_key_for(forgotten, kind))
        else:
            _generated.move_to_end(key)
        return when


def report(case: Case) -> dict[str, Any]:
    from .report import build_report

    return build_report(case, generated_at=generated_at(case))


def text(case: Case) -> str:
    """The signed text report, rendered once."""
    from .report import render_text_report

    key = _key(case, "text")
    cached = _cache.get(key)
    if isinstance(cached, str):
        return cached
    built = report(case)
    rendered = render_text_report(built)
    _keep_dated(case, "text", built["generated_at"], rendered)
    return rendered


def _keep_dated(case: Case, kind: str, when: str, value: bytes | str) -> None:
    """Keep a render only while its case's first-render time is still `when`:
    a time forgotten during the render must not come back with it."""
    case_key = _case_key(case)
    with _generated_lock:
        if _generated.get(case_key) == when:
            _cache.put(_key_for(case_key, kind), value)


def cached_pdf(case: Case) -> bytes | None:
    cached = _cache.get(_key(case, "pdf"))
    return cached if isinstance(cached, bytes) else None


def store_pdf(case: Case, pdf: bytes, generated: str) -> None:
    """Keep a PDF rendered from the report generated at `generated`."""
    _keep_dated(case, "pdf", generated, pdf)


def graph(case: Case, fmt: str) -> str:
    """The case's graph as GraphML or CSV, rendered once."""
    from . import graph_export

    key = _key(case, f"graph-{fmt}")
    cached = _cache.get(key)
    if isinstance(cached, str):
        return cached
    result = case.result
    rendered = graph_export.to_csv(case.id, result) if fmt == "csv" else graph_export.to_graphml(case.id, result)
    _cache.put(key, rendered)
    return rendered


def reset() -> None:
    """Forget every render and every limit (tests)."""
    _cache.clear()
    with _generated_lock:
        _generated.clear()
    pdf_renders.reset()
    pdf_renders_total.reset()
