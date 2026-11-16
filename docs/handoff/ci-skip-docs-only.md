# Handoff: CI skips heavy jobs on docs-only pull requests

- **Feature**: a pull request that changes only `docs/**` or root Markdown files skips the frontend, accessibility, image and migrations jobs and the citizen site's npm steps, while every required check still reports
- **Issue**: #318
- **Branch**: `ci/skip-heavy-jobs-for-docs`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: PR open, ready for the owner

## Done

- `changes` job in `.github/workflows/test.yml` and `.github/scripts/docs_only.sh`; gated steps in the five jobs; tests in `backend/tests/test_ci_docs_only.py`; `docs/operations.md`, "CI on pull requests".

## Decisions

- Step-level gates, not job-level `if` or workflow `paths-ignore`: the required checks keep starting and reporting success.
- Fail-closed: the gated jobs run with `!cancelled()`, so a failed `changes` job means a full run, never a silent pass.
- Backend tests and the citizen API tests are never skipped: they read docs files and scan every tracked file for keys.
- Only Markdown at the root counts as docs; Markdown elsewhere can ship in the image or a build.
- No third-party action (test_workflows allows only pinned `actions/*`): the diff is plain git on the merge commit, trees only.

## Next

1. After merge, check the first docs-only pull request: the five gated jobs show the "Only documentation changed" step and pass in seconds.

## Open questions

- Skipping backend tests too would need a reliable list of the tests that read docs; not done (owner).
- CodeQL default setup cannot be path-filtered from a workflow; switching to advanced setup is an owner decision.

## Files mid-change (do not touch)

- none
