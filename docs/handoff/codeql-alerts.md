# Handoff: codeql-alerts

- **Feature**: close the two open CodeQL code-scanning alerts with code changes, not suppressions
- **Issue**: #364
- **Branch**: `fix/codeql-alerts`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: PR open for review

## Done

- Alert #33 (py/stack-trace-exposure, `backend/app/routes/batches.py`): the 400 for a batch with bad rows returned `str(exc)` of a `BatchError`. The text was always one of the row checks' own sentences, so nothing leaked, but the route depended on exception text reaching the response. Now `batches.check_rows` returns a `RowCheck` (clean rows, or the problem sentence and the per-row errors) as plain data, and the route returns that. `validate_rows` keeps raising `BatchError` for its existing callers. The unknown-chain row error is now written by the batch checks (same words as before) instead of copying the `UnknownChainError` text. The server logs only the count of bad rows.
- Alert #16 (py/incomplete-url-substring-sanitization, `backend/tests/test_gambling_labels.py`): the test checked `"Stake.com" in text` on a report sentence, not a URL. It now asserts the exact start of the sentence, where the platform is named as the wallet's owner, which is the stronger check the test meant.
- Dependency audit (16 Nov, `main` at 66f88d5): `pip-audit` on `backend/requirements.txt` (34 packages), `backend/requirements-dev.txt` (44) and `citizen/api/requirements.txt` (3): no known vulnerabilities. `npm audit` in `frontend/` and `citizen/`, with and without dev dependencies: none.

## Decisions

- Change the code so the response is built from data, rather than dismissing either alert.

## Next

1. Review and merge the PR; then check that alerts #33 and #16 close on the next CodeQL run on `main`.

## Open questions

- none

## Files mid-change (do not touch)

- none
