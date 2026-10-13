"""Traces that run in the background, so a page can watch them.

POST /trace holds one HTTP request open for the whole trace -- up to minutes
on a free key -- with nothing to show but a clock, and a dropped connection
loses the answer. A job runs the same pipeline on its own thread; the page
gets an id at once, watches progress over server-sent events (or polls), and
picks the finished case up even after a reload. The case is stored exactly
as POST /trace stores it.

In memory, per process: a restart forgets running jobs (their case is lost,
as a POST /trace in flight would be) and finished ones are forgotten after
JOB_TTL_SECONDS -- by then the case store has the result.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

JOB_TTL_SECONDS = 30 * 60
MAX_JOBS = 500

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

    def snapshot(self, with_result: bool = False) -> dict[str, Any]:
        end = self.finished or time.time()
        out: dict[str, Any] = {
            "job_id": self.id,
            "status": self.status,
            "progress": dict(self.progress),
            "elapsed": round(end - self.started, 1),
            "case_id": (self.result or {}).get("case_id"),
            "error": self.error,
        }
        if with_result and self.status == DONE:
            out["result"] = self.result
        return out


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(id=str(uuid.uuid4()))
        with self._lock:
            self._prune()
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
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
            job.error = error
            job.status = FAILED if error else DONE
            job.progress["stage"] = "done" if not error else "failed"
            job.version += 1

    def _prune(self) -> None:
        now = time.time()
        for job_id in [j.id for j in self._jobs.values()
                       if j.finished and now - j.finished > JOB_TTL_SECONDS]:
            del self._jobs[job_id]
        if len(self._jobs) >= MAX_JOBS:
            for job in sorted((j for j in self._jobs.values() if j.finished), key=lambda j: j.finished):
                del self._jobs[job.id]
                if len(self._jobs) < MAX_JOBS:
                    break


store = JobStore()
