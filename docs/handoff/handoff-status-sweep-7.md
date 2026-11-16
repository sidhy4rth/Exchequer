# Handoff: handoff-status-sweep-7

- **Feature**: the handoff files for merged work say it is merged, name nobody as Current, and list only the steps still left (docs only)
- **Issue**: #350
- **Branch**: `docs/handoff-status-sweep-7`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16 (status after merge)
- **Status**: merged in #351 on 2026-11-16 (`33b9d779`)

## Done

- Claimed: issue #350, this file, PR #351.
- 20 handoffs updated (listed in #351's description).

## Decisions

- Each Status cites the PR that merged the work and its commit on `main`; each struck Next item cites the PR that did it.
- Handoff files that an open PR also edits are left alone (checked with `gh pr list --state open` on 16 Nov), so no two PRs touch the same file.

## Next

1. Later sweep: `dependency-bumps.md`, `exhibit-register.md` and `report-certificate.md` still name Barenyam as Current although their work is merged (#138 `76ff238a`; #103, #110, #181; #119). CLAUDE.md says not to edit a file someone else holds, so they were left for Barenyam or the owner.
2. Done in part 8 (`handoff-status-sweep-8.md`): `landing-flagged-figure.md` and `store-deposit-rows.md`, after #347 and #337 merged.

## Open questions

- none

## Files mid-change (do not touch)

- none
