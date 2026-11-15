# Handoff: docs-status-sweep

- **Feature**: the docs on `main` say what the code on `main` does after the 14-15 Nov merges
- **Issue**: #235
- **Branch**: `docs/status-sweep`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: in review

## Done

- `docs/suite-features.md`: rows 1, 2, 4, 5, 6, 7 and 9 say what is live, what is behind a flag and what is still in review. Round 1 refresh (after `main` reached 47aadf5): rows 2, 5 and 9 now say the export scan (#147), statements and CDRs (#146) and custody wallets (#129) are on `main` behind their flags, off; #162 (Telegram) is still open.
- `README.md`: every route in `backend/app/routes/*.py` and `access.py` is in the endpoint tables, grouped by area, checked by comparing the route decorators with the tables (104 routes with `/health`, none missing). The statement, CDR and custody routes have their own sections; the export-scan routes are with the evidence routes. The figures match live `/chains` at build 3a0cfbf (26,127 exchange addresses, 24,018 deposit addresses, 14,827 frozen, 100,000+ hack and scam wallets); the exchange label table and the Indian exchanges paragraph match the label files.
- `docs/flag-rollout.md`: a table of every flag in `config.py` `FLAGS` on `main` (twelve), with the PR that merged it and its `render.yaml` state; the custody, statement, CDR and export-scan sections say "Merged"; the migration note names `g7_statements_2` as the head on `main` and says the re-points are done.
- `docs/handoff/*.md`: Sidhyarth's merged handoffs set to merged, Current nobody (round 1 adds `bank-statement-import.md`, `custody-wallets.md`, `forensic-import.md`); the "nobody" handoffs whose work merged say so. Barenyam's handoffs: only status lines about Sidhyarth's merged PRs changed (`letters-bank-telecom.md`, `asset-register.md`).

## Decisions

- Whether a flag is set in the Render dashboard was not checked; the docs say "off in `render.yaml`" and point to `/health/detail`.

## Next

1. A final refresh once the remaining PRs merge (#162 Telegram, #218 NCRP/CFCFRMS, #230 SOP reminders, #234 labels), then review and merge.

## Open questions

- none

## Files mid-change (do not touch)

- none
