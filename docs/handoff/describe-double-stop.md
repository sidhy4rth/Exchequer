# Handoff: describe-double-stop

- **Feature**: a risk or privacy note never shows ".." when its source text already ends in a full stop
- **Issue**: #338
- **Branch**: `fix/describe-double-stop`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: claimed; fix in progress

## Done

- Claimed (issue #338, draft PR).

## Decisions

- none yet

## Next

1. `backend/app/risk_matcher.py` `RiskMatch.describe`: add the full stop after `self.source` only when the source does not already end in one; tests in `backend/tests/test_risk_matcher.py`.

## Open questions

- none

## Files mid-change (do not touch)

- `backend/app/risk_matcher.py`: `RiskMatch.describe`
