# Handoff: case bundle

- **Feature**: one zip per case for handing over or producing in court: the signed report (text and PDF), the registers as CSV, the audit trail and a MANIFEST.txt of hashes (suite feature 6)
- **Issue**: #186
- **Branch**: `feat/case-bundle` (server), `feat/case-bundle-screen` (button, stacked)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: server and button done behind `EXCHEQUER_CASE_BUNDLE` (off); in review

## Done

- Server (#187): `backend/app/case_bundle.py` builds the zip, `backend/app/routes/case_bundle.py` serves
  `GET /trace/{id}/bundle` and the probe `GET /case-bundle`, tests in `backend/tests/test_case_bundle.py`.
- Button (stacked PR on `feat/case-bundle-screen`): "Case bundle" beside the report files on the Evidence tab.
  It is not shown where the case as served already names what it withheld (`redacted`, case_privacy.py), which
  happens only for a browser that did not trace it; after any 403 it is disabled and says why. Nothing new
  is asked of the server to decide this (security review, 14 Nov).

## Decisions

- Who may download: the browser or unit that traced the case (what `/audit` asks), or anyone for a public
  demo case (whose report anyone may download). Anyone else holding the link gets 403: the bundle carries
  the audit trail and the registers, which are theirs only.
- The report files are `report_cache.text()` and the report route's own `_pdf()` (cache, rate limits),
  so they are byte for byte what the report download serves, the reader's redacted copy included.
- Registers are read with their own `list_for()`, as their routes read them for this caller; a demo caller
  on a demo case gets only their own rows and no audit trail (MANIFEST.txt says it was left out).
- One audit row, `case.bundle_download`, with `{"files": n}`; the registers' own list events are not
  recorded again.
- 64 MB cap on all files before compression (413 past it); the zip is written to a spooled temporary file
  (disk past 8 MB) and streamed in 64 KB chunks. Files in the order of `PARTS`, MANIFEST.txt last.
- The s.63(4) certificate drafts are left out (drafts the officer completes); MANIFEST.txt says so.
- The manifest is not signed; it says so and points at /verify for the report.
- Each CSV starts with a UTF-8 byte order mark, so Excel reads it as UTF-8. The formula guard stays: a cell
  starting with `=`, `+`, `-` or `@` gets a leading apostrophe, so a +91 phone number reads `'+91`;
  MANIFEST.txt says both (security review, 14 Nov).
- The spooled file is closed by the response itself, however it ends: sent in full, or the client gone
  before the first byte or part way (tested).

## Next

1. When a register PR merges (tasks #122, custody #129, statements #146, letters of request #126), add it
   with one `add_register(...)` call at the bottom of `case_bundle.py` (name, what it is, its route, its id
   field, its columns, and its `list_for` as the route reads it), and add the two file names to `FILES`
   in `tests/test_case_bundle.py`.
2. Switch on `EXCHEQUER_CASE_BUNDLE` once reviewed (owner decision).

## Open questions

- none

## Files mid-change (do not touch)

- none
