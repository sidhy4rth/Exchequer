# Handoff: label-notes-no-local-paths

- **Feature**: label-file notes describe their checks in words a repository reader can follow, with no path on the owner's machine
- **Issue**: #316
- **Branch**: `labels/notes-no-local-paths`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16 (status after merge)
- **Status**: merged in #317 on 2026-11-15 (19:41 UTC, `76101ce0`); live

## Done

- `backend/data/exchange_labels.json` and `backend/data/exchange_labels_tron.json`: in one `checks` note each, "not on ~/exchequer-flagged/never_*.txt" now reads "not on the hunt's never-flag lists (kept with the label-store build, not in this repository)". No address, count or other text changed.

## Decisions

- Only these two notes were in scope here. The script docstrings and the other handoff files that name `~/exchequer-flagged` paths are not changed in this PR: PR #313 (`docs/handoffs-no-local-paths`) replaces those paths with a `<hunt-dir>` placeholder or a description a reader can follow. The `--hunt-dir` default in `import_gambling_labels.py` is code and stays as it is.

## Next

1. None.

## Open questions

- none. #311 merged first (`d3e95969`); its conflict on the Tron `checks` line was resolved by keeping #311's text and changing only the never-flag phrase.

## Files mid-change (do not touch)

- none
