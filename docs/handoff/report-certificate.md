# Handoff: report-certificate

- **Feature**: suite feature 6 (evidence locker): a draft of the s.63(4) certificate for Exchequer's own report of a case, stating the SHA-256 of the exact report file the officer will produce
- **Issue**: #118 (part 2; part 1, for exhibits, was #112)
- **Branch**: `feat/report-certificate`
- **Current**: Barenyam
- **Last worked on**: Barenyam, 2026-11-14
- **Status**: built and tested end to end; in review

## Done

- `certificates.draft_report()`: checks the given file as `/verify` does (`signing.verify_report`, `pdf_verify.verify_pdf`), requires "genuine" or "genuine_earlier_key" and this case's id, and drafts the same Schedule certificate with the SHA-256 of those bytes. `draft()` and `draft_report()` now share `_assemble()`.
- `POST /trace/{case_id}/report-certificate` in `routes/certificates.py`: the file as base64 in JSON (no new dependency), `current_user`, the write limit, read access to the case (`routes/evidence._case_or_404`).
- 12 tests in `backend/tests/test_report_certificate.py`, with real signed reports: genuine text and PDF, a changed character, a line added after signing, not a report, too large, another case's report, the route and its audit row.

- The form: `CertificateForm.jsx` asks what the certificate covers (forensic files from the register, or Exchequer's report of this case). For the report the officer picks the file; it shows even when the case has no exhibits. 2 new tests; the old "shows nothing with no exhibits" test now checks the report option instead.
- Checked in Chromium against a real server, both themes: a downloaded PDF report certified with its exact `sha256sum`; a copy with one word changed and another case's report refused with the reason; axe clean; no browser errors.

## Decisions

- The officer gives the file: `report_cache.py` keeps renders in memory only, so after a restart the same case renders with new bytes, and a hash of "today's" report could differ from the file in the case folder.
- Only a genuine report is certified. A PDF must also pass the page comparison. Anything else is refused with the verifier's own reason.
- The audit row keeps the first 16 hex characters of the hash (`report_sha256_16`): `audit._clean` blanks any string of 20 or more token characters as a possible secret.
- Part A is filled only with what the officer typed and the hash. The signature facts go in the hash report, not into the sworn statement.

## Next

1. Sidhyarth reviews the PR; after the merge, confirm on the live site with a report downloaded there (its ISSUED BY line then names exchequer.co.in).

## Open questions

- none

## Files mid-change (do not touch)

- none
