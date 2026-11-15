# Handoff: pro-rata read failure, review nits

- **Feature**: two follow-ups from review of #321: the watch and warm-up error text stays plain and stable; only real rate-limit messages from NodeReal count as a rate limit
- **Issue**: #330
- **Branch**: `fix/prorata-read-failure-nits` (stacked on `fix/prorata-read-failure`, #321)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: claimed

## Done

- none yet

## Decisions

- none yet

## Next

1. `backend/app/watchlist.py` (check_watch) and `backend/app/warmup.py` (_loop): stop showing #321's new class names.
2. `backend/app/nodereal_client.py` (_rpc): narrow the rate-limit match; tests.

## Open questions

- none

## Files mid-change (do not touch)

- backend/app/watchlist.py, backend/app/warmup.py, backend/app/nodereal_client.py, backend/app/provider_errors.py
