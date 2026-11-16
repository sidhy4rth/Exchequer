# Handoff: focus-after-actions

- **Feature**: keyboard focus stays on the Evidence tab's identifiers and exhibits panels after an add or a check, instead of falling to the page
- **Issue**: #180
- **Branch**: `fix/focus-after-actions`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: merged in #181 (`64fc4194`) on 2026-11-15

## Done

- `frontend/src/components/case/IdentifiersPanel.jsx`: after Add to the case, the new identifier's row takes focus (falls back to the Add a reported identifier button); after Withdraw it or Record the note, that identifier's row does.
- `frontend/src/components/case/ExhibitsPanel.jsx`: the status line takes focus once a file is recorded (the form closes) or checked (the file box is disabled while it hashes); after Record the hand-over, Record the note or Record it, that exhibit's row does.
- Tests for both in the panels' test files.

## Decisions

- Same pattern as #127 and #136: the new content or the status line takes focus. No shared helper; each panel keeps a ref and an effect.
- The lookup button (Look up public records) is left to #170, which rewrites that button for t.me pages and fixes its focus for both kinds; this branch does not touch it, so the two merge cleanly.
- After a hand-over, note, withdrawal or end, the row takes focus rather than a status line: the row shows what changed (holder, status, history).

## Next

1. None.

## Open questions

- none

## Files mid-change (do not touch)

- none
