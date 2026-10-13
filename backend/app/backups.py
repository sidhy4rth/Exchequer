"""Copies of the case store, so a lost volume or a bad migration is not the end.

Two kinds:

* A daily snapshot beside the store (``backups/exchequer-YYYY-MM-DD.db.gz``,
  the last ``EXCHEQUER_BACKUP_KEEP`` kept). It survives a bad deploy or a
  mistaken delete, but not the volume itself going.
* ``GET /admin/backup`` hands a fresh snapshot to whoever holds
  ``EXCHEQUER_BACKUP_TOKEN``; the nightly GitHub Action pulls it, encrypts it
  to a public key and keeps it off the server. Without the token set the
  endpoint does not exist.

Snapshots go through SQLite's online backup API, so they are consistent while
traces are being written (the store runs in WAL mode; a plain file copy could
miss the write-ahead log).
"""
from __future__ import annotations

import gzip
import logging
import shutil
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

PREFIX = "exchequer-"
SUFFIX = ".db.gz"
CHECK_EVERY_SECONDS = 3600

_stop = threading.Event()
_thread: threading.Thread | None = None


def backup_dir() -> Path:
    return config.DB_PATH.parent / "backups"


def snapshot(dest: Path, source: Path | None = None) -> Path:
    """Write a gzipped, consistent copy of the store to ``dest``."""
    source = source or config.DB_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        raw = Path(tmp) / "snapshot.db"
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=15)
        try:
            out = sqlite3.connect(raw)
            try:
                src.backup(out)
            finally:
                out.close()
        finally:
            src.close()
        partial = dest.with_name(dest.name + ".part")
        with raw.open("rb") as fin, gzip.open(partial, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
        partial.replace(dest)  # never leave a half-written file under the real name
    return dest


def daily(now: datetime | None = None) -> Path | None:
    """Today's snapshot, if it is not there yet; then drop the oldest."""
    if not config.DB_PATH.exists():
        return None
    day = (now or datetime.now(tz=timezone.utc)).strftime("%Y-%m-%d")
    dest = backup_dir() / f"{PREFIX}{day}{SUFFIX}"
    made = None
    if not dest.exists():
        made = snapshot(dest)
        logger.info("Store snapshot written: %s (%d bytes)", dest.name, dest.stat().st_size)
    prune(config.BACKUP_KEEP)
    return made


def prune(keep: int) -> list[Path]:
    snaps = sorted(backup_dir().glob(f"{PREFIX}*{SUFFIX}"))
    old = snaps[:-keep] if keep > 0 else []
    for path in old:
        path.unlink(missing_ok=True)
    return old


def _loop() -> None:
    while not _stop.is_set():
        try:
            daily()
        except Exception:  # a failed snapshot must not take the server down
            logger.exception("Store snapshot failed")
        _stop.wait(CHECK_EVERY_SECONDS)


def start_in_background() -> None:
    global _thread
    if not config.BACKUPS_ENABLED or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="store-backups", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
