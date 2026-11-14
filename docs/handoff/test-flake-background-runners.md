# Handoff: test-flake-background-runners

- **Feature**: batch and trace-job threads no longer outlive the test that started them
- **Issue**: none (follow-up to #159 / #160)
- **Branch**: `fix/flaky-tests-2`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: fixed and tested; waits for review

## Done

- Re-checked the one-off failures reported since #160: 6 full-suite runs on main 06f02ca, all passing. The ones reported from agent branches (`test_ownership` "another row available", `test_watch_status`, `test_provider_allowance` "database is locked") match the store-retry leak #160 fixed. Most of those branches do not include #160.
- A scratch plugin that logs the live threads at each test boundary showed request-started threads still running after their test's teardown:
  - `batch-*` / `heartbeat-*` from `tests/test_console_switch.py::test_open_mode_never_asks_for_an_officer[POST-/batches-body3]` (5 of 6 runs);
  - `trace-job-*` from three stream tests in `tests/test_jobs.py` (12 times in 6 runs);
  - `heartbeat-*` from `tests/test_batch_fairness.py::test_a_finished_batch_frees_its_owner` (once, in a later run).
- They read `models._engine` when they run, and the batch ones were still alive when the next test's fixture swapped in its own store and started the app, so they could write into that store while it was being migrated. No failure was traced to this in these runs.
- New autouse fixture `_wait_for_background_runners` in `tests/conftest.py`. At teardown it joins every `batch-`, `heartbeat-` or `trace-job-` thread the test started, and fails the test if one is still running after 10 s. It takes `monkeypatch`, so it runs before the test's patches are undone and the threads end against the test's own engine and stubs. Autouse rather than per file: which test leaks depends on timing, and the third leak showed up only after the first two were fixed.

## Decisions

- No app change. The threads are meant to outlive the HTTP response. In production they end with their work, and only the suite swaps stores between requests.

## Next

1. Review and merge.

## Open questions

- none

## Files mid-change (do not touch)

- none
