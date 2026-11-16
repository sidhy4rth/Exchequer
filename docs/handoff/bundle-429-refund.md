# Handoff: bundle-429-refund

- **Feature**: a case bundle whose report PDF was refused (429) no longer uses up a bundle from the hourly limit
- **Issue**: #255
- **Branch**: `fix/bundle-429-refund`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: merged in #256 (`6f82ef32`)

## Done

- `backend/app/routes/case_bundle.py` `download_bundle`: when `case_bundle.build` raises a 429 HTTPException
  (the PDF inside was refused: render slot busy, or the PDF limit), both bundle limiters (`bundles` per
  client, `bundles_total` site-wide) are refunded before the 429 is re-raised. This is commit 29b02474,
  written on `fix/minor-hardening` but pushed after #242 was squash-merged, cherry-picked onto main.
- `backend/tests/test_case_bundle.py`: `test_a_bundle_refused_because_its_pdf_was_refused_costs_nothing`
  holds the render slot, sets the client bundle limit to 1, and checks the refused request leaves that one
  bundle free. It fails on main without the fix.
- `docs/handoff/minor-hardening.md`: the bundle-limit line now says a PDF-refused request is refunded.

## Decisions

- Only a 429 is refunded. Other errors from the build (413 too large, 5xx) still count, as before.

## Next

1. None. (~~Merge the PR once CI is green~~: merged in #256.)

## Open questions

- none

## Files mid-change (do not touch)

- none
