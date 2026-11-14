# Handoff: focus-after-actions

- **Feature**: keyboard focus stays on the Evidence tab's identifiers and exhibits panels after an add or a check, instead of falling to the page
- **Issue**: #180
- **Branch**: `fix/focus-after-actions`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: open for review

## Done

- `frontend/src/components/case/IdentifiersPanel.jsx`: after Add to the case, the new identifier's row takes focus (falls back to the Add a reported identifier button).
- `frontend/src/components/case/ExhibitsPanel.jsx`: the status line takes focus once a file is recorded (the form closes) or checked (the file box is disabled while it hashes).
- Tests for both in the panels' test files.

## Decisions

- Same pattern as #127 and #136: the new content or the status line takes focus. No shared helper; each panel keeps a ref and an effect.
- The lookup button (Look up public records) is left to #170, which rewrites that button for t.me pages and fixes its focus for both kinds; this branch does not touch it, so the two merge cleanly.
- Withdraw / Record the note / Hand over close their small forms too; not changed here.

## Next

1. Review and merge.

## Open questions

- none

## Files mid-change (do not touch)

- none
