# Handoff: privacy-protocol-category

- **Feature**: privacy protocols (Railgun, Aztec, Hinkal, Privacy Pools) shown on a trace as a note, never a risk hit or a stop
- **Issue**: #189
- **Branch**: `feat/privacy-protocol-category` (PR 1, contract), `feat/privacy-protocol-trace` (PR 2, stacked), `feat/privacy-protocol-ui` (PR 3, stacked)
- **Current**: nobody (awaiting review, then the owner's yes before the flag is turned on)
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: built behind `EXCHEQUER_PRIVACY_CATEGORY` (off); all three PRs ready for review

## Done

- PR 1 (contract change): `privacy_matches[]`, `privacy_notes[]` and `graph.nodes[].privacy_entity` in
  `docs/contracts/case.md`; `PrivacyMatch` in `backend/app/contracts/case_v2.py` (category always `privacy`,
  `is_terminal` always false). Fixtures unchanged: no recorded demo passes a privacy contract, and the flag is off.
- PR 2 (trace): `data/privacy_protocols*.json` (27 contracts on 5 chains: the 25 the hunt found new, plus Privacy
  Pools' 2), each with the source the hunt recorded and its contract code re-checked keylessly on 14 Nov (same code
  size and hash as 11 Nov). `risk_matcher.annotate_privacy`, `privacy_lookup`, `is_labelled`; the pipeline writes
  `privacy_matches`/`privacy_notes` only with the flag on.
- PR 3 (UI): `components/case/PrivacyNotes.jsx` (grey, dotted, not the red alert) under the risk alert; a `privacy`
  role on both maps (grey, dotted halo; key entry only when one is on the map) and on the Entities card.

## Decisions

- A separate list, not a value in `risk_matches`: every count of risk hits (Cases, Present, the report, the risk
  alert, victim_flow's stops) stays untouched by construction, and nothing has to remember to skip it.
- Not in `risk_matcher.CATEGORIES`: a risk file that says "privacy" is skipped; only a privacy file is read for it.
- Privacy Pools: flag off, it stays a mixer and a stop exactly as on main; flag on, its threat-file mixer tag gives
  way to the privacy entry. Only the threat file's mixer tag gives way: a government listing, a freeze or a theft tag
  on a privacy contract stands, and then no privacy note is shown for it.
- Files are named `privacy_protocols*.json`, not `*_labels*.json`: they are not risk label files, and the shipped
  label-file checks load those as risk files.
- Not added to `risk_matcher.LISTS` (list freshness, provenance): that would change every case's output with the flag
  off. Add it when the flag is retired.

## Next

1. Owner: say yes or no to turning the flag on (and to moving Privacy Pools out of the mixers).
2. If yes: set `EXCHEQUER_PRIVACY_CATEGORY=1` on Render; later retire the flag (delete the `config.PRIVACY_CATEGORY`
   branches in `risk_matcher._risk_matcher` and `pipeline.run_trace`), add the privacy file to `LISTS`, and move
   Privacy Pools out of `threat_labels.json`.

## Open questions

- Should the report and the letters mention privacy notes? Not done: they read `risk_notes` only. (owner)
- The hunt's Solana and Base Hinkal rows are not filed: Exchequer traces neither chain.

## Files mid-change (do not touch)

- none
