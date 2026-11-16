# Handoff: demo3-candidate-a

- **Feature**: DEMO.md trace 3 moves to a quiet documented phishing wallet that reaches a probable exchange deposit address through an intermediary, with a pro-rata amount
- **Issue**: #284
- **Branch**: `demos/demo3-candidate-a`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: owner approved the swap (15 Nov); merged in #286 (`dde8e1ee`)

## Done

- Candidate A `0x0067b43cb530e683dbffb43f5caacde867472721` (Etherscan `Fake_Phishing4989`) traced on a local backend from this branch (Routescan's keyless Etherscan-compatible API, because Blockscout's returned 429 for about 20 minutes) and on the live site (`check_demos.py --record --only 3,4`, then `record_demos.py --only 3`). Both gave the same answer: HitBTC, probable deposit address `0x4a1265873468a63a9710a3185fdcff7154a2c50c` (inferred) at 2 hops, 0.6688 moderate, pro-rata 0.740266 of 1.0626 ETH, 24 addresses.
- DEMO.md section 3 rewritten from that trace, keeping the old wallet's history in a subsection; header, demo 4, running order and *If a live trace disappoints* updated where they named the old trace 3. README demo row, `TraceForm.jsx` demos 03 and 04, `demo_traces.json` (warm-up) updated.
- `demo_expectations.json`: demo 3's address changed, expectations re-recorded from live for demos 3 and 4 (demo 4 unchanged: no exchange). `recorded_demos.json`: demo 3 re-recorded from live.
- `TraceForm.test.jsx`: the demo-03 band check now expects "HitBTC ... moderate confidence", the band the new recording carries.
- The old demo 3 recording (14 Oct, `0x536c4921…`) is kept verbatim as `backend/tests/fixtures/recorded_demo3_2026-10-14_usdt_follow_on.json` (the row from `recorded_demos.json` on main). The 14 tests that need a swap with a USDT follow-on read it (via `conftest.swap_recording`), with unchanged assertions; `build_contract_fixtures.py` builds demo 3's fixture from it, so the contract fixtures are unchanged except an additive `pinned_recordings` key in `index.json`. `verify_case._demo_report` takes an optional recordings file.
- `test_letters_of_request`: demo 3's "claims no more than the case holds" check now looks for "to an account at HitBTC", the exchange the new recording names.
- DEMO.md demo 3 says HitBTC still operated on 15 Nov 2026 and is not FIU-IND registered (s.13 PMLA notice, 1 Oct 2025, PIB 2173758). Demo 4's totals updated from a 15 Nov reverse trace (local backend from this branch): 304.7749 ETH, largest 135.5910 ETH, still 10 senders and no exchange.

## Decisions

- Demo 4 stays on `0x536c4921…`: its expectation (no exchange among the funders) still holds on live. On the new wallet a reverse trace finds 2 funders, one of them Coinbase 3, which is a different story.
- Demo 3's check is strict (lead's decision, 15 Nov): `"volatile"` removed from its expectation, since the new wallet has 5 transactions ever and a change should fail the daily check. `test_check_demos` now asserts no demo is marked as moving (`test_no_demo_is_marked_as_moving`).

## Next

1. None. (~~Lead: merge~~: merged in #286.)

## Open questions

- none

## Files mid-change (do not touch)

- none
