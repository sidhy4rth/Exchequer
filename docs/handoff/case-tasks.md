# Handoff: case-tasks

- **Feature**: suite feature 6 (case management): a task list per case: what still has to be done, who it is assigned to (a name), by when, and what came of it
- **Issue**: #121
- **Branch**: `feat/case-tasks` (server, PR #122); `feat/case-tasks-screen` (screen, #123, on top of it); `feat/case-tasks-suggest` (suggestions, on top of #123)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: built and tested end to end in three stacked PRs (#122 server, #123 screen, then suggestions); all wait for review

## Done

- Server (PR #122): model `CaseTask` in `models.py`, migration `g7_tasks_1` (one table, `case_tasks`), `backend/app/tasks.py`, `backend/app/routes/tasks.py` (one import and one `include_router` line in `main.py`). Routes: `GET/POST /trace/{case_id}/tasks`, `PATCH /tasks/{task_id}`, `GET /tasks/due?days=7`.
- 29 tests in `backend/tests/test_tasks.py`, including the migration going down and up; the full suite passes (3,274).
- Screen: `frontend/src/components/case/TasksPanel.jsx` (+ `.css`, `.test.jsx`) at the top of the Evidence tab's registers (one import, one line in `EvidenceTab.jsx`); `frontend/src/components/TaskDeadlines.jsx` (+ `.css`), a "Tasks due" card on the home page under the court deadlines (one import, one line in `Home.jsx`); API calls in `frontend/src/api/tasks.js` (one re-export line in `api.js`). 11 tests; all 1,626 frontend tests and the build pass.
- End to end in a browser against the real server (throwaway database, a recorded demo saved as a case): added a task with a past due date (shown "Overdue by 2 days"), saw it on the home card, followed its link to the Evidence tab, dropped it with a reason (history and audit right, no text in the audit), added and marked done a second task.

- Suggestions (on top of #123): `tasks.suggestions(viewer, case_id)` works out, from the case's own records, the tasks they call for: a request sent 7+ days ago with no reply (follow up), an urgent freeze letter awaiting sign-off (get it) or signed off but not sent (send it), a freeze not in the asset register (record it), and held funds with no court order on custody (get it, due on the register's 45-day deadline). `GET /trace/{case}/tasks` returns them as `suggested`; `POST` with `source` takes one up, and with `note` too declines it (a dropped task with the reason). Column `case_tasks.source`, migration `g7_tasks_2`. 13 backend tests (each rule fires, and stays silent on recent, answered, ordered or released records), 3 frontend tests; checked in a browser against seeded records.

## Decisions

- Modelled on the asset and exhibit registers (`assets.py`, `exhibits.py`): rows readable by the browser that made them and the officer's unit, nothing deleted, every change in the row's history, the audit log records which fields changed and never their text.
- Assignees are names only, as the asset register's key holders are.
- Free text refuses private keys and seed phrases (`assets.looks_like_secret`).
- A task is open, done or dropped. Done needs no reason; dropping a task or opening it again does, so nothing quietly disappears. A closed task takes only a note or reopening.
- A past due date is allowed (a task can be entered late) and shows as overdue; dates before 2009 or more than 10 years ahead are refused as typos.
- The list shows open tasks first, soonest due first, undated last; then closed ones, latest first.
- Two writes to one task at once: the second re-reads and tries again (row version), as the exhibit register does.
- The panel sits on the Evidence tab, not a sixth tab: `CaseTabs.test.jsx` and `caseTab.test.jsx` pin five tabs, and feature 6's exhibit register and certificate already live there.
- API calls in their own `api/tasks.js`, not `api/evidence.js`, which Barenyam's #119 also changes.
- Suggestions are never stored: they are worked out on each read, from records the viewer may read, and name only what those records say. Taking one up uses the suggestion's own title and due date, never the caller's, and a key the case does not currently suggest is refused.
- A declined suggestion is a dropped task with the reason, so it never quietly returns and the decision is in the history; reopening it keeps the suggestion away too.
- `source` came as its own migration (`g7_tasks_2`) rather than an edit to `g7_tasks_1`, which was already up for review in #122.
- The panel opens on arrival when a task is open; after that only the officer folds it, so closing the last task does not snap it shut.

## Next

1. Review and merge #122, then the screen PR (retarget it to `main` once #122 is squash-merged: merge `main` into it, keeping its side).
2. Then the suggestions PR (retarget it to `main` the same way once #123 is merged).
3. Later, more rules, each only where a record says so: an exhibit handed over with no check since, a watch alert not yet looked at.

## Open questions

- The home-page card is one import and one line in `Home.jsx` (platform's page), under the court deadlines: Barenyam to confirm its place.

## Files mid-change (do not touch)

- none yet
