# Handoff: exhibit-register

- **Feature**: suite feature 3 (memory and disk tools), and the first piece of feature 6's evidence locker: a register of the files outside forensic tools produced, with their hashes and chain of custody
- **Issue**: #102
- **Branch**: `feat/exhibit-register`
- **Current**: Barenyam
- **Last worked on**: Barenyam, 2026-11-13
- **Status**: claimed; plan written, no code yet

## The nine features (see `docs/suite-features.md`)

1 Attribution data (Sidhyarth, #91) · 2 Mobile and computer forensics · **3 Memory and disk tools (Barenyam, this file)** · 4 OSINT · 5 Telecom and bank analysis · 6 Case management and evidence locker · 7 Request and letter generator (merged, #99) · 8 Government platforms · 9 Custody wallet tooling (merged, #101). Unnamed ones are unclaimed.

## Done

- Nothing yet beyond the claim.

## Decisions

- The file is never uploaded. The officer records the hash the tool printed; the browser can check a file against it by computing its SHA-256 locally, in chunks, so a phone or disk image of many GB never leaves the machine and never has to fit in memory.
- SHA-256 is the main hash; SHA-1 and MD5 are kept when the tool gives them (BSA s.63 Part B names all three), and at least one is required.
- Nothing is deleted. Hand-overs are history entries (who, to whom, when, why), never edits.
- Free-text fields refuse private keys and seed phrases, reusing `assets.py`'s check.

## Next

1. Server: model, migration after `g7_assets_1`, `backend/app/exhibits.py`, routes, tests first.
2. Screen: an "Exhibits" panel on the Evidence tab (one import, one line in `EvidenceTab.jsx`), with an add form, hand-over, and "Check a file".

## Open questions

- none yet

## Files mid-change (do not touch)

- none yet
