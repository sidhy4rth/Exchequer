# Handoff: review-16nov-backend

- **Feature**: fixes from a correctness review of the backend merged on 16 Nov 2026 (76101ce0..66f88d59)
- **Issue**: #368
- **Branch**: `fix/pmr-backend-review`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: in review

## Done

- `backend/app/request_letters.py`: the letter to an instant exchanger that is not the case's named exchange no longer carries the pro-rata read-failure note (#321). That letter never states an amount (the case's estimate is for its own exchange), so "Trace again later for an estimate" was untrue there. The named exchange's own letters keep the note.
- `backend/app/custody_balance.py`: a run's `checked_at` is kept to the microsecond, so `latest()` returns the newest of two runs made in one second (it returned the older one). `summary()` still shows it to the second. Older runs, kept to the second, sort correctly against the new ones.
- Tests: one new test in `test_prorata_read_failure.py`, one new test in `test_custody_balance.py`, and the existing "newest run" test now checks for the newest run (it used to accept either run).

## Decisions

- No migration: `checked_at` is `String(32)`, and an ISO time with microseconds and `+00:00` is exactly 32 characters.

## Next

1. The lead reviews and merges.

## Open questions

- none

## Files mid-change (do not touch)

- none
