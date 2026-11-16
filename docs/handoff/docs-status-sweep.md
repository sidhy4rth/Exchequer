# Handoff: docs-status-sweep

- **Feature**: the docs on `main` say what the code on `main` does after the 14-15 Nov merges
- **Issue**: #235
- **Branch**: `docs/status-sweep`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: merged in #236 (`b1803f17`)

## Done

- `docs/suite-features.md`: every row says what is live, what is on `main` behind a flag (off) and nothing is listed as in review. Round 1 (main at 47aadf5): rows 2, 5 and 9 (export scan #147, statements and CDRs #146, custody wallets #129). Round 2 (main at 87d5881): row 1 (India round 3 #247, OKX's two Ethereum consolidation wallets #248, the `contract_wallet` retype #234 with #238), row 4 (Telegram lookups #162, off), row 6 (bundle registers #244), row 8 (NCRP note #218 live; SOP summary #219/#220 and SOP reminders #230, both off).
- `README.md`: every route in `backend/app/routes/*.py` and `access.py` is in the endpoint tables, grouped by area, checked by comparing the route decorators with the tables (106 routes with `/health`, none missing; round 2 added the two SOP summary routes and the Telegram case of the lookup route). The figures match live `/chains` at build 87d5881 (26,136 exchange addresses, 24,018 deposit addresses, 14,827 frozen, 100,000+ hack and scam wallets); the exchange label table (Ethereum 25,273 / 96 exchanges, BSC 223, Tron 139 / 26) and the Indian exchanges paragraph (175 wallets, Unocoin added) match the label files.
- `docs/flag-rollout.md`: a table of every flag in `config.py` `FLAGS` on `main` (fifteen), with the PR that merged it and its `render.yaml` state (only `EXCHEQUER_OSINT_LOOKUPS` is set there); every feature section says "Merged"; a new section for `EXCHEQUER_SOP_DEADLINES`; the migration note names `g7_statements_2` as the head.
- `docs/officer-guide.md` (#192): status lines for #162, #218, #219/#220 and #230; the case bundle's new registers (#244); the label notes for #234, #247 and #248; the build the site ran (87d5881).
- `docs/handoff/*.md`: Sidhyarth's merged handoffs set to merged, Current nobody (round 1: `bank-statement-import`, `custody-wallets`, `forensic-import`; round 2: `case-bundle`, `contract-wallet-inference`, `contract-wallet-types`, `government-platforms`, `india-exchange-labels`, `minor-hardening`, `officer-guide`, `okx-consolidation-wallets`, `osint`, `sop-deadlines`); the "nobody" handoffs whose work merged say so. Barenyam's handoffs: only status lines about Sidhyarth's merged PRs changed (`letters-bank-telecom.md`, `asset-register.md`).

## Decisions

- Whether a flag is set in the Render dashboard was not checked; the docs say "off in `render.yaml`" and point to `/health/detail`.

## Next

1. None. (~~Review and merge~~: merged in #236.)

## Open questions

- none

## Files mid-change (do not touch)

- none
