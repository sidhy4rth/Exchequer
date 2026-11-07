"""Traces that run in the background, so a page can watch them.

POST /trace holds one HTTP request open for the whole trace -- up to minutes
on a free key -- with nothing to show but a clock, and a dropped connection
loses the answer. A job runs the same pipeline on its own thread; the page
gets an id at once, watches progress over server-sent events (or polls), and
picks the finished case up even after a reload. The case is stored exactly
as POST /trace stores it.

In memory, per process: a restart forgets running jobs (their case is lost,
as a POST /trace in flight would be) and finished ones are forgotten after
JOB_TTL_SECONDS -- by then the case store has the result. A finished job holds
its result only briefly: a stored case's payload for RESULT_HOLD_SECONDS
(then only its id; the page reads the case from the store), an unsaved one's
for UNSAVED_RESULT_TTL (then the job is forgotten). A case can be megabytes,
and 500 jobs kept whole for 30 minutes could fill a 512 MB instance.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

JOB_TTL_SECONDS = 30 * 60
RESULT_HOLD_SECONDS = 120
UNSAVED_RESULT_TTL = 5 * 60
MAX_JOBS = 100

RUNNING, DONE, FAILED = "running", "done", "failed"


@dataclass
class Job:
    id: str
    started: float = field(default_factory=time.time)
    status: str = RUNNING
    progress: dict[str, Any] = field(default_factory=lambda: {"stage": "starting"})
    finished: float | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    version: int = 0
    # Who may stop it (the owner hash of the browser that started it) and the
    # trace's clock, which a stop cancels (api_budget.TraceBudget).
    owner: str | None = None
    budget: Any = None
    case_id: str | None = None

    def snapshot(self, with_result: bool = False) -> dict[str, Any]:
        end = self.finished or time.time()
        out: dict[str, Any] = {
            "job_id": self.id,
            "status": self.status,
            "progress": dict(self.progress),
            "elapsed": round(end - self.started, 1),
            "case_id": self.case_id,
            "error": self.error,
        }
        if with_result and self.status == DONE:
            out["result"] = self.result
        return out


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, owner: str | None = None, budget: Any = None) -> Job:
        job = Job(id=str(uuid.uuid4()), owner=owner, budget=budget)
        with self._lock:
            self._prune()
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            self._prune()
            return self._jobs.get(job_id)

    def report(self, job: Job, fields: dict[str, Any]) -> None:
        with self._lock:
            job.progress.update(fields)
            job.version += 1

    def finish(self, job: Job, result: dict[str, Any] | None = None,
               error: dict[str, Any] | None = None) -> None:
        with self._lock:
            job.finished = time.time()
            job.result = result
            job.case_id = (result or {}).get("case_id")
            job.error = error
            job.status = FAILED if error else DONE
            job.progress["stage"] = "done" if not error else "failed"
            job.version += 1

    def _prune(self) -> None:
        now = time.time()
        for job in list(self._jobs.values()):
            if not job.finished:
                continue
            age = now - job.finished
            if age > JOB_TTL_SECONDS or (job.case_id is None and job.result is not None and age > UNSAVED_RESULT_TTL):
                del self._jobs[job.id]
            elif job.case_id is not None and age > RESULT_HOLD_SECONDS:
                job.result = None  # the case store has it
        if len(self._jobs) >= MAX_JOBS:
            for job in sorted((j for j in self._jobs.values() if j.finished), key=lambda j: j.finished):
                del self._jobs[job.id]
                if len(self._jobs) < MAX_JOBS:
                    break


store = JobStore()
