# Handoff: demo3-candidate-a

- **Feature**: DEMO.md trace 3 moves to a quiet documented phishing wallet that reaches a probable exchange deposit address through an intermediary, with a pro-rata amount
- **Issue**: #284
- **Branch**: `demos/demo3-candidate-a`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: draft PR, CI red on purpose: 14 backend tests are pinned to the old demo 3 recording; waiting for the owner

## Done

- Candidate A `0x0067b43cb530e683dbffb43f5caacde867472721` (Etherscan `Fake_Phishing4989`) traced on a local backend from this branch (Routescan's keyless Etherscan-compatible API, because Blockscout's returned 429 for about 20 minutes) and on the live site (`check_demos.py --record --only 3,4`, then `record_demos.py --only 3`). Both gave the same answer: HitBTC, probable deposit address `0x4a1265873468a63a9710a3185fdcff7154a2c50c` (inferred) at 2 hops, 0.6688 moderate, pro-rata 0.740266 of 1.0626 ETH, 24 addresses.
- DEMO.md section 3 rewritten from that trace, keeping the old wallet's history in a subsection; header, demo 4, running order and *If a live trace disappoints* updated where they named the old trace 3. README demo row, `TraceForm.jsx` demos 03 and 04, `demo_traces.json` (warm-up) updated.
- `demo_expectations.json`: demo 3's address changed, expectations re-recorded from live for demos 3 and 4 (demo 4 unchanged: no exchange). `recorded_demos.json`: demo 3 re-recorded from live.
- `TraceForm.test.jsx`: the demo-03 band check now expects "HitBTC ... moderate confidence", the band the new recording carries.

## Decisions

- Demo 4 stays on `0x536c4921…`: its expectation (no exchange among the funders) still holds on live. On the new wallet a reverse trace finds 2 funders, one of them Coinbase 3, which is a different story.
- Demo 3 keeps `"volatile": true`, so `test_only_demo_3_is_marked_as_moving` is unchanged. The new path is quiet, so the owner may prefer a strict check (drop the key and change that test with it).

## Next

1. Owner: decide whether to swap demo 3 (and whether HitBTC as the named exchange is acceptable).
2. If yes, decide how the old demo 3 recording (14 Oct, 0x536c4921..., the repo's only recorded swap with a USDT follow-on) survives for the 14 tests pinned to it: test_contract (2, incl. the contract-fixture drift test, since `scripts/build_contract_fixtures.py` builds `deposit_inferred.json` from demo 3), test_verify_case (7, via `scripts/verify_case.py::_demo_report`), test_letter_audit (2), test_read_fields (1), test_victim_flow_read (1), test_freeze_letters (1). One way: keep that recording verbatim as a test fixture and point those tests and the two scripts at it. That touches the contract fixtures, so it needs Barenyam's agreement (CLAUDE.md rule 3).
3. Then mark the PR ready and request review.

## Open questions

- Is HitBTC acceptable as the exchange the demo letter is addressed to? It is not in `exchange_status.json`, so the repo treats it as open; nobody has checked its current status for this PR.
- Keep `volatile` on demo 3, or make its check strict?
- Demo 4's table (43.5207 ETH total, largest sender 16.9325 ETH) no longer matches the live funders' amounts; the count (10) and "no exchanges" still do. Not changed here.

## Files mid-change (do not touch)

- none
