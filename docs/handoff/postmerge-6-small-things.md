# Handoff: postmerge-6-small-things

- **Feature**: docs say what is true after the 15-16 Nov night merges: the officer guide's build, three handoff statuses, the 60-day schedule pause for `fiu-staleness.yml`, and the `KEEP_AWAKE` variable's state
- **Issue**: #324
- **Branch**: `docs/postmerge-6-small-things`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: done; PR #325 ready for review

## Done

- Claimed (issue #324, draft PR #325).
- `docs/officer-guide.md`: the status line names #317 (build 76101ce), origin/main's HEAD when the branch was cut and the build live `/health` reported (`76101ce0a925`) on 16 Nov.
- Handoffs moved to merged, Current = nobody: `fiu-ind-status-note.md` (#310 `c60e7e0a`, #314 `d4d9a1cd`), `label-notes-no-local-paths.md` (#317 `76101ce0`), `okx-sweep-destinations.md` (#277 `470541e3`).
- `docs/flag-rollout.md` (EXCHEQUER_FIU_IND_NOTE, re-checking the sources): GitHub disables scheduled workflows in a public repository after 60 days with no activity, quoted from GitHub's docs, so `fiu-staleness.yml` can stop warning; how to re-enable it.
- `docs/operations.md` (Keeping the site awake): `KEEP_AWAKE` = `on` since 19:35 UTC on 15 Nov 2026 (`gh variable list`: 2026-11-15T19:35:29Z).

## Decisions

- `KEEP_AWAKE`'s state is recorded in `docs/operations.md`, next to the on/off steps for the workflow, since there is no keep-awake handoff and `docs/flag-rollout.md` covers Render flags, not repository variables.

## Next

1. Before merge: if anything else has merged and deployed, change the officer guide's "#317 (build 76101ce)" to the build live `/health` reports.

## Open questions

- none

## Files mid-change (do not touch)

- none
