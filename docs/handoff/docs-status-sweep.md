# Handoff: docs-status-sweep

- **Feature**: the docs on `main` say what the code on `main` does after the 14-15 Nov merges
- **Issue**: #235
- **Branch**: `docs/status-sweep`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: in review

## Done

- `docs/suite-features.md`: rows 1, 2, 4, 5, 6, 7 and 9 say what is live, what is behind a flag and what is still in review (#129, #146, #147 and #162 are open).
- `README.md`: every route in `backend/app/routes/*.py` and `access.py` is in the endpoint tables, grouped by area; the figures match live `/chains` at build 3a0cfbf (26,127 exchange addresses, 24,018 deposit addresses, 14,827 frozen, 100,000+ hack and scam wallets); the exchange label table and the Indian exchanges paragraph match the label files.
- `docs/flag-rollout.md`: a table of every flag in `config.py` `FLAGS` on `main`; the migration note names `g7_tasks_2` as the head on `main`.
- `docs/handoff/*.md`: Sidhyarth's merged handoffs set to merged, Current nobody; the "nobody" handoffs whose work merged say so. Barenyam's handoffs are unchanged.

## Decisions

- Whether a flag is set in the Render dashboard was not checked; the docs say "off in `render.yaml`" and point to `/health/detail`.

## Next

1. Review and merge.

## Open questions

- none

## Files mid-change (do not touch)

- none
