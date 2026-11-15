# Handoff: okx-tron-demo-wallets

- **Feature**: 5 more of OKX's own Tron wallets labelled, the ones older OKX deposits swept into, so the Tron deposit-row join can accept them as `sweeps_to`
- **Issue**: #307
- **Branch**: `labels/okx-tron-demo-wallets`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16 (status after merge)
- **Status**: merged in #308 on 2026-11-15 (18:59 UTC, `c9f723bf`); live. The owner delegated the merge decision to the lead, who accepted the statement-only exception: the 5 appear only as statement senders in demo 9, and no demo was changed or re-recorded

## Done

- `backend/data/exchange_labels_tron.json`: "OKX: Reserve Wallet 274" to "278" added the way #304 added 264 to 273 (same source, `sweep_basis` from the same recorded reads). The note's `left_out` no longer lists them; `in_demo_statement_only` says where they are in the demo files and why that is safe. Counts updated.
- `backend/tests/test_okx_tron_own_wallets.py`: counts 10 -> 15 and OKX 11 -> 16; a new test checks each of the 5 is in a recorded demo only as a statement sender (demo 9's `statement.credits[].counterparty`, and the same in the contract fixture), and nowhere in the demo traces or expectations.

## Decisions

- No demo was re-recorded: demos 9, 11 and 12 traced locally (keyless TronGrid, JSON label files only) with and without the 5 rows gave identical results apart from the label file's hash in provenance. A statement row carries no label, so there is nothing for a recording to change.
- `import_por_tron_labels.listed_elsewhere()` is unchanged: the exception is per address, listed in the note, and checked by a test.

## Next

1. Done: merged in #308 (decision above).
2. Next label-store release: let the Tron deposit-row join accept the 5 new destinations (steps in the release notes kept outside the repository; the release's own GitHub notes in `sidhy4rth/exchequer-labels` will say what it did).

## Open questions

- none. The statement-only exception to the "re-record before labelling" rule was accepted by the lead on the owner's behalf when #308 merged (Status above).

## Files mid-change (do not touch)

- none
