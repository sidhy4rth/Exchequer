# Handoff: pro-rata read failure, review nits

- **Feature**: two follow-ups from review of #321: the watch and warm-up error text stays plain and stable; only real rate-limit messages from NodeReal count as a rate limit
- **Issue**: #330
- **Branch**: `fix/prorata-read-failure-nits` (stacked on `fix/prorata-read-failure`, #321)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: done, PR #331 ready for the lead (retarget to `main` after #321 merges)

## Done

- PR #331: a watch that could not be read shows `provider_errors.public_reason` ("Could not read the address this round (the provider reported an error).") instead of an exception class name, so #321's new `*UnavailableError` classes do not reach the officer's Watchlist. The warm-up's status (`/health/detail`, operator only) keeps "ClassName: message", with a client out of retries named as before #321 (`provider_errors.error_name`: EtherscanError, NoderealError, TronError).
- NodeReal: only rate-limit messages (`etherscan_client._RATE_LIMIT_MESSAGES`: "rate limit", "max rate limit reached", "too many requests"; the repo's recorded NodeReal shape is `{"code": -32005, "message": "too many requests"}` in test_provider_pacing) are retried and set `rate_limited`. Before, any message with "limit" or "too many" was.
- Tests: `backend/tests/test_provider_error_text.py`.

## Decisions

- `last_error` has no contract (not in `docs/contracts/`); the watch's text is a sentence for the officer, so it may change. Stored rows keep their old text until the next check.
- `public_reason` is unchanged (cases are stored and signed with it), so a watch whose provider ran out of retries says "the provider reported an error", the sentence a case gives for the same failure.

## Next

1. none

## Open questions

- none

## Files mid-change (do not touch)

- none
