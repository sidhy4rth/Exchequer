# Handoff: minor-hardening

- **Feature**: four small fixes from the 15 Nov security spot-check of main (none exploitable today)
- **Issue**: #241
- **Branch**: `fix/minor-hardening`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: one PR, ready for review

## Done

- `exchange_matcher.FIRM_ACCOUNT`: the gap before "Deposit" may start only where a run of spaces starts
  (`(?<!\s)`), so a long run no longer makes the match quadratic; `firm_account()` also refuses a label
  longer than `FIRM_LABEL_MAX` (200, TronScan's tag cap). A 20,000-character input now takes well under 0.2 s.
- `DELETE /trace/jobs/{id}` records `case.trace_stopped` with `job_id` and `was_running` only. A refused
  stop (403, 404) records nothing.
- `letters_of_request.draft()`: `{country}`, `{court}`, `{presiding}` and `{treaty}` are filled in one
  `re.sub` pass, so an officer's own text that contains a placeholder stays as typed. The MHA wording file
  is unchanged (its SHA pin test passes).
- `GET /trace/{id}/bundle`: charged per client (20 an hour) and site-wide (120 an hour), as PDF renders
  are; 429 with Retry-After. A 403 or 404 is not charged, nor a request whose PDF was refused (busy, or the
  PDF limit: 429), which is refunded. The test suite resets both limiters.

## Decisions

- The bundle limits are constants in `routes/case_bundle.py`, like `report_cache.pdf_renders`, not
  config settings: the route is behind a flag and the numbers can move to config if the flag goes on.

## Next

1. Review and merge.

## Open questions

- none

## Files mid-change (do not touch)

- none
