# Handoff: dependency-bumps

- **Feature**: clear the open Dependabot pull requests so dependencies stay current and CI stays green
- **Issue**: #95
- **Branch**: `feat/dependency-bumps`
- **Current**: Barenyam
- **Last worked on**: Barenyam, 2026-11-12
- **Status**: #82's Python patch updates and their fix are on this branch; #1, #2, #3, #56 closed as stale

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

## Decisions

- #82 is taken over on this branch: Dependabot raised psycopg to 3.3.7 in `backend/requirements.txt` only. This branch also regenerates `backend/requirements-dev.txt` with the repo's uv command (only psycopg and psycopg-binary changed) and copies the 3.3.7 hash blocks into `citizen/api/requirements.txt`. `tests/test_requirements_locked.py` and `citizen/api/tests/test_endpoints.py::test_the_dependencies_are_psycopg_alone_pinned_with_hashes` pass locally.

- Merge lockfile PRs one at a time and wait for Dependabot's rebase and CI between them.
- Fixes go in our own PRs, never as pushes to a Dependabot branch (Dependabot stops maintaining a branch someone else pushed to).

## Next

1. Review and merge this branch's PR (it carries #82's updates plus the fix), then close #82 as superseded.
2. Merge #80, then #81 once Dependabot has rebased it and CI is green.
3. #61 last, on its own, after reading the SQLAlchemy 2.1 and FastAPI release notes.

## Open questions

- pypdf 6 → 7 (major) was only in the stale #56. Do we want it? If so, its own PR, tested against the evidence report PDFs. (Barenyam and Sidhyarth)
- Who merges the Dependabot PRs: Sidhyarth, or whoever approves them?

## Files mid-change (do not touch)

- none
