# Handoff: dependency-bumps

- **Feature**: clear the open Dependabot pull requests so dependencies stay current and CI stays green
- **Issue**: #95
- **Branch**: `feat/dependency-bumps`
- **Current**: Barenyam (Sidhyarth's session continued this, 14 Nov)
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: #82's updates and their fix merged as #96. #80 retested on `main` at 39b3292, ready to merge; #81 waits for #80; #61 redone as our own PR on `feat/python-minor-bumps`

## Done

- Reviewed #1, #2, #3, #56, #61, #80, #81, #82 against `main` at b59fe63 (versions, CI, overlap).

| PR | What | CI | Verdict |
|---|---|---|---|
| #1 | source-map-js 1.2.1 → 1.2.2 (frontend) | old run | Close: `main` already resolves 1.2.2 |
| #2 | pytest 8.3.4 → 9.0.3 | old run | Close: `main` pins 9.1.1 |
| #3 | python-dotenv 1.0.1 → 1.2.2 | old run | Close: `main` pins 1.2.4 |
| #56 | 9 Python packages, `pip` ecosystem | old run | Close: based on a580f93, before the hashed uv lock (d1372c5); superseded by #61 and #82 |
| #80 | npm patch group (frontend, citizen) | green | Merge first |
| #81 | npm minor group: react/react-dom 19.3.1, @playwright/test 1.64.1 | green | Merge after #80, once Dependabot has rebased it and CI is green again |
| #82 | Python patch group: psycopg 3.3.7, pydantic 2.14.2, alembic 1.20.1, ruff 0.17.3 | red | Needs the fix below |
| #61 | Python minor group: SQLAlchemy 2.0 → 2.1, FastAPI 0.143 → 0.162, Starlette 1.7 → 1.10, reportlab 5.1, pytest 9.2 | green | Hold: biggest jumps; last, on its own, after reading release notes |

- 13 Nov, checked against `main` at ad3768b (after features 3, 4, 7 and 9):
  - #80 merges cleanly. With it, all 1,577 frontend tests and 230 citizen tests pass, and both builds pass, run locally. Ready to merge.
  - #81 merges cleanly on its own, but its lockfiles conflict with #80's. After #80 merges, Dependabot must rebase #81 (never hand-merge a lockfile).
  - #61 conflicts in `requirements.in` and `requirements-dev.in` with #96. Dependabot must recreate it, or we redo it in our own PR after reading the SQLAlchemy 2.1 and FastAPI release notes.

- 14 Nov (Sidhyarth's session), against `main` at 39b3292:
  - #80: its CI ran on 5da13fa (55 commits behind), so we asked Dependabot to rebase it. Merged locally into 39b3292: 1,592 frontend tests and 230 citizen page tests pass, 65 citizen API tests pass, both builds pass. Ready to merge once the rebased CI is green.
  - #81: unchanged; waits for #80 and Dependabot's rebase.
  - #61: redone on `feat/python-minor-bumps` (supersedes #61): FastAPI 0.162.0, Starlette 1.10.0, SQLAlchemy 2.1.6, reportlab 5.1.0, pytest 9.2.0 in `requirements.in` / `requirements-dev.in`, both locks recompiled with the uv command in `requirements.in`. Same versions as #61; greenlet leaves the lock because SQLAlchemy 2.1 no longer requires it (we use no asyncio). `citizen/api/requirements.txt` pins none of these. Backend 3,245 passed / 6 skipped, ruff clean, `alembic upgrade head` and `alembic check` clean on a fresh SQLite file, citizen API 65 passed. Release notes read; nothing in them touches our code (details in the PR).

## Decisions

- #82 is taken over on this branch: Dependabot raised psycopg to 3.3.7 in `backend/requirements.txt` only. This branch also regenerates `backend/requirements-dev.txt` with the repo's uv command (only psycopg and psycopg-binary changed) and copies the 3.3.7 hash blocks into `citizen/api/requirements.txt`. `tests/test_requirements_locked.py` and `citizen/api/tests/test_endpoints.py::test_the_dependencies_are_psycopg_alone_pinned_with_hashes` pass locally.

- Merge lockfile PRs one at a time and wait for Dependabot's rebase and CI between them.
- Fixes go in our own PRs, never as pushes to a Dependabot branch (Dependabot stops maintaining a branch someone else pushed to).

## Next

1. Merge #80 once Dependabot's rebase is green.
2. Wait for Dependabot to rebase #81, then merge it when CI is green.
3. Review and merge the `feat/python-minor-bumps` PR, then close #61 as superseded.
4. FastAPI's TestClient now warns that it wants `httpx2` instead of `httpx` (Starlette deprecation). Not urgent; a later bump can add `httpx2` to `requirements-dev.in` once it is out of the deprecation window.

## Open questions

- pypdf 6 → 7 (major) was only in the stale #56. Do we want it? If so, its own PR, tested against the evidence report PDFs. (Barenyam and Sidhyarth)
- Who merges the Dependabot PRs: Sidhyarth, or whoever approves them?

## Files mid-change (do not touch)

- none
