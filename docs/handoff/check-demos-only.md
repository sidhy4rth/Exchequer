# Handoff: check-demos-only

- **Feature**: `backend/scripts/check_demos.py` can run a subset of the demos (`--only 3,6-8`) and sit out the live site's hourly trace limit (`--wait-on-429`)
- **Issue**: #271
- **Branch**: `tools/check-demos-only`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: merged in #272 (`5704bc7b`)

## Done

- `--only`: numbers and ranges; an unknown demo number is a usage error (exit 2). With `--record` only those entries change; the rest of `demo_expectations.json` stays byte-identical (the file is exactly what the writer produces, and a test holds that). With `--state`, a skipped demo keeps its remembered miss.
- `--wait-on-429`: waits Retry-After (else 60 s, at most 3600 s) and retries that demo up to 3 times, printing why it is waiting. Off by default.

## Decisions

- The Demo health Action does not use `--wait-on-429`: it traces 12 demos a day, far under 30 an hour, so a 429 there is most likely the wrong-code lockout, where each retry sends the wrong code again; and its 30-minute job timeout is shorter than the limit's hour.

## Next

1. None.

## Open questions

- none

## Files mid-change (do not touch)

- none
