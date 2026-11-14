# Handoff: test-flake-store-retry

- **Feature**: the backend suite no longer fails at random with alembic setup errors (`KeyError: 'script'`)
- **Issue**: #159
- **Branch**: `fix/report-cache-test-flake`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: fixed and tested; waits for review

## Done

- Found the cause. `tests/test_degraded_start.py::test_the_site_starts_and_serves_what_needs_no_store` starts the app with an unreachable store. The lifespan then starts `main._retry_store_in_background()`, a thread that runs until the store opens and is never stopped.
  - The thread outlived the test. It either ran at once against the next test's store, or failed and slept for `DB_RETRY_SECONDS` (60 s once the test's patch was undone). It then woke up during a random later test and ran `models.init_db()` there.
  - Alembic keeps one migration context per process (`alembic.context`). Two upgrades at once tear down each other's context, which fails with `KeyError: 'script'` or `KeyError: 'config'`, or breaks a batch migration (`no such table: _alembic_tmp_alerts`).
- Fixed it in `tests/test_degraded_start.py` only:
  - the `unreachable` fixture records that the retry was scheduled instead of starting the thread, and the test asserts it was scheduled;
  - a new test runs the retry loop itself, waits for it to finish and checks that the thread ended.

## Decisions

- No change to `app/main.py`. In production the retry thread ends with the process. Only the test suite runs several apps in one process.

## Next

1. Review and merge.

## Open questions

- none

## Files mid-change (do not touch)

- none
