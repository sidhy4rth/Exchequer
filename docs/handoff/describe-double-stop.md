# Handoff: describe-double-stop

- **Feature**: a risk or privacy note never shows ".." when its source text already ends in a full stop
- **Issue**: #338
- **Branch**: `fix/describe-double-stop`
- **Current**: nobody (in review)
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: done; PR #339 in review

## Done

- `RiskMatch.describe` adds the full stop after the source only when the source does not already end in one (PR #339). 50 distinct source strings in the label files end in one (privacy and threat files); every other note is byte-identical (checked against all 33,381 source strings in `backend/data/*.json` across every branch). Recorded demos contain no "..", so they are unchanged.
- Tests: `backend/tests/test_risk_matcher.py` (`test_describe_puts_one_full_stop_*`, `test_describe_adds_the_full_stop_*`).
- The #293 doc nits (contract-wallet roles) were already merged in #294 (`de179250`); nothing more to do for them.

## Decisions

- Only a trailing "." counts; the Tron warning-tag note keeps "(source)." since the source sits in brackets there.

## Next

1. none; the lead merges #339.

## Open questions

- none

## Files mid-change (do not touch)

- none
