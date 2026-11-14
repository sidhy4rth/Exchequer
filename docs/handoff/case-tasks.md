# Handoff: case-tasks

- **Feature**: suite feature 6 (case management): a task list per case: what still has to be done, who it is assigned to (a name), by when, and what came of it
- **Issue**: #121
- **Branch**: `feat/case-tasks`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: server built and tested (PR #122); the screen comes next, in its own PR

## Done

- Server (PR #122): model `CaseTask` in `models.py`, migration `g7_tasks_1` (one table, `case_tasks`), `backend/app/tasks.py`, `backend/app/routes/tasks.py` (one import and one `include_router` line in `main.py`). Routes: `GET/POST /trace/{case_id}/tasks`, `PATCH /tasks/{task_id}`, `GET /tasks/due?days=7`.
- 29 tests in `backend/tests/test_tasks.py`, including the migration going down and up; the full suite passes (3,274).

## Decisions

- Modelled on the asset and exhibit registers (`assets.py`, `exhibits.py`): rows readable by the browser that made them and the officer's unit, nothing deleted, every change in the row's history, the audit log records which fields changed and never their text.
- Assignees are names only, as the asset register's key holders are.
- Free text refuses private keys and seed phrases (`assets.looks_like_secret`).
- A task is open, done or dropped. Done needs no reason; dropping a task or opening it again does, so nothing quietly disappears. A closed task takes only a note or reopening.
- A past due date is allowed (a task can be entered late) and shows as overdue; dates before 2009 or more than 10 years ahead are refused as typos.
- The list shows open tasks first, soonest due first, undated last; then closed ones, latest first.
- Two writes to one task at once: the second re-reads and tries again (row version), as the exhibit register does.

## Next

1. Screen: a `TasksPanel` on the case (`frontend/src/components/case/`), API calls in `frontend/src/api/`, then the due tasks on the home page (one import, one line in `Home.jsx`).
2. Later: suggest tasks from what the case already shows (a freeze request with no reply, an asset with no court order).

## Open questions

- none yet

## Files mid-change (do not touch)

- none yet
