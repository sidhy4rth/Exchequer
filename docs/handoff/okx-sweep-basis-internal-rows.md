# Handoff: okx-sweep-basis-internal-rows

- **Feature**: the `sweep_basis` of #277's 47 OKX Ethereum sweep-destination labels counts only rows that are still customer-deposit sweeps, after the label-store build's internal-wallet filter dropped OKX-funded rows
- **Issue**: #328
- **Branch**: `labels/okx-sweep-basis-internal-rows`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16 (status after merge)
- **Status**: merged in #329 on 2026-11-16 (`76bd1f9d`); live (data notes only; no app code reads `sweep_basis`)

## Done

- `backend/data/exchange_labels.json`: 29 of #277's 47 `sweep_basis` rows now say how many of the rows they counted (from `okx_por_ethereum_deposits.dropped.tsv`) the label-store build's internal-wallet filter dropped (`okx_por_ethereum_deposits.dropped_internal.tsv`, rules A/B: funded by OKX's own wallets) and how many are left; 79 of the 821 counted rows were dropped. For 13 wallets none is left (217, 218, 220, 230, 231, 233, 237, 238, 241, 250, 252, 258, 260). Reserve Wallets 237 and 258 also cite the 16 Nov hand check: each of their 20 rows was funded 0.5 ETH by an OKX PoR wallet on 18 May 2026 and sent part back in block 25126685. `_meta.okx_sweep_destinations_2026_11_15.revised_2026_11_16` holds the files' SHA-256s, per-wallet counts and the 20 rows' tx hashes; the note's `rule` says the sweep part was revised. No label, type or source changed.
- Tests: three new tests in `backend/tests/test_okx_sweep_destination_labels.py`.

## Decisions

- The labels stay: each is on OKX's own PoR file (Non Staking) and the classification classes it exchange_wallet.
- Rows the filter dropped are "not taken as customer deposits", following the filter; only 237's and 258's 20 rows were checked by hand. 0x8167a1eb (an OKX relay, also dropped) swept into Reserve Wallet 216 (#248) and was never counted here.

## Next

1. Owner: decide whether the 13 wallets with no deposit sweep left should stay labelled (they pass the PoR + classification rule, which is what the label claims).

## Open questions

- none

## Files mid-change (do not touch)

- none
