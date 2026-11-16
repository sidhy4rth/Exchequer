# Handoff: trace screen shows a label-store row's basis

- **Feature**: when the trace's case address came from a label-store exchange row, the trace screen says what the attribution stands on (the exchange's own list, and for a deposit row the sweep), in the report's words
- **Issue**: #336
- **Branch**: `feat/trace-deposit-basis`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: PR #337 ready for review; shows only when the trace read a store row (`EXCHEQUER_STORE_EXCHANGE_ROWS`, off)

## Done

- `frontend/src/components/case/StoreRowBasis.jsx` (+ `.css`): under the address to cite, a "Basis" line ("INFERRED from the exchange's own list and a sweep into it", or "the exchange's own published address list (PoR)", as the report's Basis line) and the sentences of `report.basis_lines`: the list, and for a deposit row "Sent funds to <sweeps_to> (<label>), a wallet labelled as <exchange>'s, in tx <sweep_tx> (checked <checked_on>) ... This is an inference from public records, which only <exchange> can confirm." Reads `matches[].attribution_basis` of the match the case names (as `report.store_basis` does). Renders nothing without one. One import + one JSX line in `TraceView.jsx`, after the address to cite (not under the pro-rata line, which PR #323 uses).
- Wording pinned both sides by one fixture, `backend/tests/fixtures/store_basis_lines.json` (built by running `report.basis_lines`): `backend/tests/test_store_basis_wording.py` and `StoreRowBasis.test.jsx` check it. `TraceView.storebasis.test.jsx`: demo 11 unchanged shows nothing; with a deposit basis on its match it shows the lines.

## Decisions

- No backend or contract change: `matches[].attribution_basis` is already in the trace result (#267, `docs/contracts/case.md`).
- Plain sentences, grey text, no colour or badge: a statement of sources, not a finding.

## Next

1. None. If `report.basis_lines` changes, regenerate the fixture from it and change `StoreRowBasis.basisLines` to match.

## Open questions

- none

## Files mid-change (do not touch)

- none
