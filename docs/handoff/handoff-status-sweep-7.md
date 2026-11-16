# Handoff: handoff-status-sweep-7

- **Feature**: the handoff files for merged work say it is merged, name nobody as Current, and list only the steps still left (docs only)
- **Issue**: #350
- **Branch**: `docs/handoff-status-sweep-7`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: PR #351 ready for review

## Done

- Claimed: issue #350, this file, PR #351.
- 20 handoffs updated (listed in #351's description).

## Decisions

- Each Status cites the PR that merged the work and its commit on `main`; each struck Next item cites the PR that did it.
- Handoff files that an open PR also edits are left alone (checked with `gh pr list --state open` on 16 Nov), so no two PRs touch the same file.

## Next

1. Lead: review and merge #351.
2. Later sweep: `dependency-bumps.md`, `exhibit-register.md` and `report-certificate.md` still name Barenyam as Current although their work is merged (#138 `76ff238a`; #103, #110, #181; #119). CLAUDE.md says not to edit a file someone else holds, so they were left for Barenyam or the owner.
3. Also left: handoffs an open PR edits (e.g. `landing-flagged-figure.md` in #347, `store-deposit-rows.md` in #337); fix them after those merge if still stale.

## Open questions

- none

## Files mid-change (do not touch)

- none
