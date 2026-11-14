# Handoff: case-tasks

- **Feature**: suite feature 6 (case management): a task list per case: what still has to be done, who it is assigned to (a name), by when, and what came of it
- **Issue**: #121
- **Branch**: `feat/case-tasks`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: claimed; server being built

## Done

- Claimed (this file, draft PR).

## Decisions

- Modelled on the asset and exhibit registers (`assets.py`, `exhibits.py`): rows readable by the browser that made them and the officer's unit, nothing deleted, every change in the row's history, the audit log records which fields changed and never their text.
- Assignees are names only, as the asset register's key holders are.
- Free text refuses private keys and seed phrases (`assets.looks_like_secret`).

## Next

1. Server: model `CaseTask` in `models.py`, migration `g7_tasks_1` on top of `g7_domain_lookups_1`, `backend/app/tasks.py`, `backend/app/routes/tasks.py`, tests in `backend/tests/test_tasks.py`.
2. Screen: a panel on the case, and the due tasks on the home page.

## Open questions

- none yet

## Files mid-change (do not touch)

- none yet
