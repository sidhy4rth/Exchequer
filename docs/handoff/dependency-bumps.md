# Handoff: dependency-bumps

- **Feature**: clear the open Dependabot pull requests so dependencies stay current and CI stays green
- **Issue**: #ISSUE
- **Branch**: `feat/dependency-bumps`
- **Current**: Barenyam
- **Last worked on**: Barenyam, 2026-11-12
- **Status**: all 8 Dependabot PRs reviewed; nothing closed or merged yet

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

- Merge lockfile PRs one at a time and wait for Dependabot's rebase and CI between them.
- Fixes go in our own PRs, never as pushes to a Dependabot branch (Dependabot stops maintaining a branch someone else pushed to).

## Next

1. #82 fix: `citizen/api/requirements.txt` still pins psycopg and psycopg-binary 3.3.6. Raise both to 3.3.7, copying their hash lines from #82's `backend/requirements.txt` (never by hand). `citizen/api/tests/test_endpoints.py::test_the_dependencies_are_psycopg_alone_pinned_with_hashes` checks every citizen hash appears in the backend lock; that is the one test failing in both red jobs of #82.
2. After agreement: close #1, #2, #3, #56 with a one-line reason each.
3. Then merge in order: #80, #81 (rebased), #82 with its fix, #61 last.

## Open questions

- pypdf 6 → 7 (major) was only in the stale #56. Do we want it? If so, its own PR, tested against the evidence report PDFs. (Barenyam and Sidhyarth)
- Who merges the Dependabot PRs: Sidhyarth, or whoever approves them?

## Files mid-change (do not touch)

- none
