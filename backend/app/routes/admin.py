"""Operator endpoints. Each one exists only when its token is configured.

GET /admin/backup returns a fresh, consistent snapshot of the case store for
the nightly off-site copy (.github/workflows/backup.yml). The store holds
every case and the watch webhooks, so the endpoint answers 404 -- as if it
were not there -- unless EXCHEQUER_BACKUP_TOKEN is set, and 401 to anything
but that exact bearer token.
"""
from __future__ import annotations

import hmac
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse

from .. import backups, config

router = APIRouter()


def _authorised(request: Request) -> None:
    if not config.BACKUP_TOKEN:
        raise HTTPException(status_code=404, detail="Not Found")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        token.strip().encode(), config.BACKUP_TOKEN.encode()
    ):
        raise HTTPException(status_code=401, detail="Not authorised.")


@router.get("/admin/backup", include_in_schema=False)
def backup(request: Request, tasks: BackgroundTasks) -> FileResponse:
    _authorised(request)
    tmp = Path(tempfile.mkdtemp(prefix="exq-backup-"))
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = backups.snapshot(tmp / f"exchequer-{stamp}.db.gz")
    tasks.add_task(_cleanup, tmp)
    return FileResponse(path, media_type="application/gzip", filename=path.name,
                        headers={"Cache-Control": "no-store"})


def _cleanup(folder: Path) -> None:
    for item in folder.iterdir():
        item.unlink(missing_ok=True)
    folder.rmdir()
