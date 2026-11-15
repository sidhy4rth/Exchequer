# Handoff: label-notes-no-local-paths

- **Feature**: label-file notes describe their checks in words a repository reader can follow, with no path on the owner's machine
- **Issue**: #316
- **Branch**: `labels/notes-no-local-paths`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: done; PR ready

## Done

- `backend/data/exchange_labels.json` and `backend/data/exchange_labels_tron.json`: in one `checks` note each, "not on ~/exchequer-flagged/never_*.txt" now reads "not on the hunt's never-flag lists (kept with the label-store build, not in this repository)". No address, count or other text changed.

## Decisions

- Only these two notes were in scope. Script docstrings and other handoff files that name `~/exchequer-flagged` paths were left as they are (they are run instructions for the owner, not label evidence).

## Next

1. None.

## Open questions

- Open PR #311 rewrites the same Tron `checks` line and keeps the old phrase. Whichever PR merges second must resolve the conflict by keeping #311's text and applying this one phrase change.

## Files mid-change (do not touch)

- none
