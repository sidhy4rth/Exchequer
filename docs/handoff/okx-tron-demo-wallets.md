# Handoff: okx-tron-demo-wallets

- **Feature**: 5 more of OKX's own Tron wallets labelled, the ones older OKX deposits swept into, so the Tron deposit-row join can accept them as `sweeps_to`
- **Issue**: #307
- **Branch**: `labels/okx-tron-demo-wallets`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: draft PR, waiting for the owner's decision

## Done

- `backend/data/exchange_labels_tron.json`: "OKX: Reserve Wallet 274" to "278" added the way #304 added 264 to 273 (same source, `sweep_basis` from the same recorded reads). The note's `left_out` no longer lists them; `in_demo_statement_only` says where they are in the demo files and why that is safe. Counts updated.
- `backend/tests/test_okx_tron_own_wallets.py`: counts 10 -> 15 and OKX 11 -> 16; a new test checks each of the 5 is in a recorded demo only as a statement sender (demo 9's `statement.credits[].counterparty`, and the same in the contract fixture), and nowhere in the demo traces or expectations.

## Decisions

- No demo was re-recorded: demos 9, 11 and 12 traced locally (keyless TronGrid, JSON label files only) with and without the 5 rows gave identical results apart from the label file's hash in provenance. A statement row carries no label, so there is nothing for a recording to change.
- `import_por_tron_labels.listed_elsewhere()` is unchanged: the exception is per address, listed in the note, and checked by a test.

## Next

1. Owner: decide whether to merge (then mark the PR ready and request review).
2. After merge: let the Tron deposit-row join accept the 5 new destinations (see the next-release notes kept with the label-store build, not in this repository).

## Open questions

- Whether the owner accepts the statement-only exception to the "re-record before labelling" rule.

## Files mid-change (do not touch)

- none
