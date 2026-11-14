"""A task list per case (tasks.py): what still has to be done in it.

    GET   /trace/{case_id}/tasks   the case's tasks this browser or unit may read
    POST  /trace/{case_id}/tasks   add one
    PATCH /tasks/{task_id}         change it, close it (done or dropped), open it again, or add a note
    GET   /tasks/due               open tasks due within ?days= (default 7) or overdue

Writes are limited per connection, like the requests log, and audited by what
changed, never by the text, which may name officers.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import audit, tasks
from ..auth import CurrentUser
from .requests import _allow_write, _owner

router = APIRouter()


class NewTask(BaseModel):
    title: str = Field(..., max_length=200)
    assignee: str = Field("", max_length=120)
    due_on: str = Field("", max_length=10)
    notes: str = Field("", max_length=2000)


class TaskChange(BaseModel):
    title: str | None = Field(None, max_length=200)
    assignee: str | None = Field(None, max_length=120)
    due_on: str | None = Field(None, max_length=10)
    status: str | None = Field(None, max_length=16)
    notes: str | None = Field(None, max_length=2000)
    note: str | None = Field(None, max_length=300)


@router.get("/trace/{case_id}/tasks")
def list_tasks(case_id: str, user: CurrentUser) -> dict[str, Any]:
    rows = tasks.list_for(user, case_id)
    audit.record("task.list", case_id=case_id)
    return {"case_id": case_id, "count": len(rows), "open": sum(t["status"] == "open" for t in rows), "tasks": rows}


@router.post("/trace/{case_id}/tasks", status_code=201)
def add_task(case_id: str, body: NewTask, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    try:
        made = tasks.create(_owner(user), case_id, body.model_dump(), user)
    except tasks.TaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record("task.add", case_id=case_id, detail={"task_id": made["task_id"]})
    return made


@router.patch("/tasks/{task_id}")
def change_task(task_id: str, body: TaskChange, user: CurrentUser, http: Request) -> dict[str, Any]:
    _allow_write(http)
    try:
        updated = tasks.update(task_id, body.model_dump(exclude_none=True), user)
    except tasks.TaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except tasks.TaskConflict as exc:
        raise HTTPException(status_code=409, detail="Someone changed this task at the same moment. "
                                                    "Reload and try again.") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="No task with that id that you can change.")
    changed, noted = updated.pop("changed"), updated.pop("noted")
    if changed or noted:  # every new history entry is audited; a note's words never are
        detail = {"task_id": task_id, "changed": changed, **({"noted": True} if noted else {})}
        if "status" in changed:
            detail["status"] = updated["status"]
        audit.record("task.update", case_id=updated["case_id"], detail=detail)
    return updated


@router.get("/tasks/due")
def due_tasks(user: CurrentUser, days: int = Query(7, ge=0, le=90)) -> dict[str, Any]:
    rows = tasks.due_for(user, within_days=days)
    audit.record("task.due", detail={"count": len(rows)})
    return {"count": len(rows), "tasks": rows}
