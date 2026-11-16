# Handoff: CI runs its two slowest checks in shards

- **Feature**: "backend tests" and "accessibility (WCAG 2.2 AA)" run as three and four shards at once behind one job with the required name, so a pull request waits about half as long for CI
- **Issue**: #373
- **Branch**: `ci-speed`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: PR open, ready for review

## Done

- `.github/workflows/test.yml`: `backend` and `a11y` are matrix jobs (3 and 4 shards); `backend_all` and `a11y_all` carry the required names and pass only when every shard passed.
- `backend/tests/shards.py` + a `pytest_collection_modifyitems` hook in `backend/tests/conftest.py`: `EXCHEQUER_TEST_SHARD=k/n` keeps shard k's files; unset keeps everything.
- `frontend/playwright.a11y.config.js`: `fullyParallel: true`, so Playwright's `--shard` splits the one spec file evenly.
- Tests: `backend/tests/test_ci_shards.py`. Docs: `docs/operations.md`, "CI on pull requests".

## Decisions

- Shards run on separate runners, so no shared temporary file or port; the suite already resets its process-wide state per test (conftest autouse fixtures).
- The backend split is by file, a function of file names and sizes only, so every runner computes the same split and each file lands in exactly one shard. No pytest-xdist (a dependency change, and not proven safe in one process).
- Ruff and the FIU-IND note run once, in shard 1.
- Left out: path filters (backend tests read frontend/ and citizen/ files, and the a11y check serves the backend), docker layer cache (needs a non-`actions/*` action, which test_workflows refuses), and more Playwright workers per runner (untested for flakiness).

## Next

1. If the backend suite grows unevenly, raise the shard count in test.yml (matrix and the `/3`) and the a11y one likewise; test_ci_shards checks they match.

## Open questions

- none

## Files mid-change (do not touch)

- none
