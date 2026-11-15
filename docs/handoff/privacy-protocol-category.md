# Handoff: privacy-protocol-category

- **Feature**: privacy protocols (Railgun, Aztec, Hinkal, Privacy Pools) shown on a trace as a note, never a risk hit or a stop
- **Issue**: #189
- **Branch**: `feat/privacy-protocol-category` (PR 1, contract), `feat/privacy-protocol-trace` (PR 2, stacked), `feat/privacy-protocol-ui` (PR 3, stacked), `feat/privacy-in-report` (PR 4, stacked: the report)
- **Current**: nobody (merged; the owner said yes, and the flag was set to `1` in the Render dashboard on 2026-11-15)
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: all four PRs merged to `main` inside #149 (#194, #195, #196, #198), behind `EXCHEQUER_PRIVACY_CATEGORY`, on in production since 2026-11-15. The `render.yaml` entry and `docs/flag-rollout.md` section are in the switch-on PR

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
- PR 4 (report): with the flag on and at least one match, the signed text report has a section
  "PRIVACY PROTOCOLS ON THE PATH (A NOTE, NOT AN ACCUSATION)" after the screening: the screen's lede, then each
  match's own sentence (address, protocol, hop, source), the main trace's and each follow-on's. The JSON report
  gains `privacy_protocols` under the same rule. PDF page 1 shows a grey block drawn from that signed section
  (so /verify still redraws page 1 exactly); Part 2 is the signed text. Flag off, or no match: report bytes
  unchanged (tested, recorded demos included). Report format stays v2.3: the section is optional.

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

- Letters (`request_letters.py`) never mention privacy protocols, by choice: they are requests to a third party,
  kept to the facts the request needs. A test pins that each letter is identical with and without the matches.
  There is no letter-of-request module on this stack (#126/#127 are elsewhere) and no generated officer-notes
  section to add it to.

## Next

1. When the owner says yes: set `EXCHEQUER_PRIVACY_CATEGORY=1` in the Render dashboard (Environment) and
   redeploy, check `/health/detail` → `flags`, do the checks in `docs/flag-rollout.md`, then merge the draft PR
   that adds the same key to `render.yaml` (as #108 did for `EXCHEQUER_OSINT_LOOKUPS`).
2. The owner approved the category and moving Privacy Pools to it on 14 Nov (relayed by the lead). Later retire the flag (delete the `config.PRIVACY_CATEGORY`
   branches in `risk_matcher._risk_matcher` and `pipeline.run_trace`), add the privacy file to `LISTS`, and move
   Privacy Pools out of `threat_labels.json`.

## Open questions

- Report: done in PR 4. Letters: deliberately not (see Decisions); revisit only if the owner wants it.
- `RiskMatch.describe` prints "..unchanged.." (a source ending in a full stop, then ". "): cosmetic, from PR 2.
- The hunt's Solana and Base Hinkal rows are not filed: Exchequer traces neither chain.

## Files mid-change (do not touch)

- none
