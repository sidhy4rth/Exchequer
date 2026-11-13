# Handoff: exhibit-register

- **Feature**: suite feature 3 (memory and disk tools), and the first piece of feature 6's evidence locker: a register of the files outside forensic tools produced, with their hashes and chain of custody
- **Issue**: #102
- **Branch**: `feat/exhibit-register`
- **Current**: Barenyam
- **Last worked on**: Barenyam, 2026-11-13
- **Status**: server and Evidence-tab panel built, tested end to end in a browser; committed locally, NOT pushed: the repo's ruleset "Only the owner pushes or merges" (added 12 Nov) refuses branch creation for Barenyam

## The nine features (see `docs/suite-features.md`)

1 Attribution data (Sidhyarth, #91) · 2 Mobile and computer forensics · **3 Memory and disk tools (Barenyam, this file)** · 4 OSINT · 5 Telecom and bank analysis · 6 Case management and evidence locker · 7 Request and letter generator (merged, #99) · 8 Government platforms · 9 Custody wallet tooling (merged, #101). Unnamed ones are unclaimed.

## Done

- Server: `backend/app/exhibits.py`, `backend/app/routes/exhibits.py` (`GET/POST /trace/{case_id}/exhibits`, `PATCH /exhibits/{id}`, `POST /exhibits/{id}/check`), model `Exhibit`, migration `g7_exhibits_1` (after `g7_assets_1`), `assets.looks_like_secret` shared. 28 tests in `backend/tests/test_exhibits.py`; full suite and ruff pass (apart from the root-only signing test).
- Screen: `frontend/src/components/case/ExhibitsPanel.jsx` (+ `.css`, `.test.jsx`) at the end of the Evidence tab (one import, one line in `EvidenceTab.jsx`); `sha256.js` (+ test), a chunked SHA-256 checked against node's at every padding boundary, about 57 MB/s. All 1,547 frontend tests and the build pass.
- End to end in Chromium against the real server: a 40 MB file hashed in the browser in 1.4 s, equal to `sha256sum`; the largest request sent was 355 bytes; the same file matched, a copy with one byte changed did not; a hand-over recorded with its reason. axe (WCAG 2.2 AA) clean in both themes at desktop and phone size.

## Decisions

- The file is never uploaded. The officer records the hash the tool printed; the browser can check a file against it by computing its SHA-256 locally, in chunks, so a phone or disk image of many GB never leaves the machine and never has to fit in memory.
- SHA-256 is the main hash; SHA-1 and MD5 are kept when the tool gives them (BSA s.63 Part B names all three), and at least one is required.
- Nothing is deleted. Hand-overs are history entries (who, to whom, when, why), never edits.
- Free-text fields refuse private keys and seed phrases, reusing `assets.py`'s check.

## Next

1. Push `feat/exhibit-register` once Sidhyarth lets Barenyam push feature branches (narrow "Only the owner pushes or merges" to `main`), then open the PR.
2. Later: feed the exhibit list into the s.63 certificate the report generates (Part B states each file's hash).

## Open questions

- Checking a 64 GB image in the browser takes about 20 minutes at 57 MB/s. Good enough for a court check; a faster WebAssembly hash would be its own dependency PR if officers need it.

## Files mid-change (do not touch)

- none yet
