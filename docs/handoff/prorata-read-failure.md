# Handoff: pro-rata read failure

- **Feature**: when the pro-rata window read fails at the provider, retry it once and, if it still fails, say so plainly instead of silently lowering the score
- **Issue**: #320
- **Branch**: `fix/prorata-read-failure`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: done, PR #321 ready for the lead

## Done

- PR #321: the window read pro-rata needs is made once more, 10 s later, when it failed for a passing reason (rate limit, no answer) and the case has 40 s to spare (`provider_errors.read_again_once`, wrapped inside `read_once` in `pipeline.run_trace`). The clients already retried each request (5 attempts on Etherscan, about 7.5 s of backoff); out of retries they now raise `ProviderUnavailableError` (with `rate_limited`), still an `EtherscanError`, so every existing handler and public sentence is unchanged.
- A read that still fails sets `prorata.read_failure` (`provider_errors.failure_kind`) and the case says so: amount component explanation, limitations, signed report (both via `confidence_detail`), and an officer note in the exchange and instant-exchanger letter drafts. Documented in `docs/contracts/case.md` (additive, v1-style).
- Tests: `backend/tests/test_prorata_read_failure.py` (demo 3's recorded window answer replayed through a real `EtherscanClient`: success, 429 then success, 429 throughout; end to end with a fake provider).

## Decisions

- Scoring unchanged: [ADR-0007](../adr/0007-pro-rata-not-all-or-nothing.md) says a wallet that could not be read in full earns the amount no credit, so "unknown" stays 0; only the disclosure is added.

## Next

1. Optional: show `prorata.read_failure` on the trace screen (the note already shows there as a limitation; `TraceView.jsx`'s pro-rata line still says only the reason)). Taken in #322 / PR #323, see `prorata-read-failure-ui.md`.

## Open questions

- none

## Files mid-change (do not touch)

- none
