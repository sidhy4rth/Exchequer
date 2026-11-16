# Handoff: okx-sweep-destinations

- **Feature**: the OKX Ethereum deposit addresses that sweep only into OKX proof-of-reserves wallets the label file did not name can get a deposit row, because those destination wallets are labelled
- **Issue**: #276
- **Branch**: `labels/okx-sweep-destinations`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16 (status after merge)
- **Status**: merged in #277 on 2026-11-15 (15:57 UTC, `470541e3`); live

## Done

- `backend/data/exchange_labels.json`: 47 OKX Ethereum wallets ("OKX: Reserve Wallet 217" to "263"), each cited to OKX's November 2026 PoR file as the #226 rows are, with a `sweep_basis` (the release classification and how many dropped deposit rows swept into it). 40 are accounts typed `exchange_wallet`; 7 are EIP-1967 proxies (code identical to #248's Reserve Wallet 215) typed `contract_wallet`, role `exchange_wallet`. `_meta.okx_sweep_destinations_2026_11_15` holds the source, the classification file's SHA-256, each address's PoR rows, the checks and what was left out.
- `backend/tests/fixtures/label_code/ethereum.json`: the 47 answers (full `--record` run, block 26421367, every other answer unchanged) under `_meta.read_since`.
- Tests: `backend/tests/test_okx_sweep_destination_labels.py`; `test_por_labels._por_rows` leaves out `sweep_basis` rows.

## Decisions

- Only wallets OKX's own PoR file lists (Non Staking) and the release's on-chain classification (`okx_por_ethereum_classified.csv`) classes `exchange_wallet` are labelled.

- 16 Nov 2026: the sweep counts were revised in #328 (PR #329): 79 of the 821 counted rows were later dropped by the label-store build's internal-wallet filter, leaving 13 wallets with no deposit sweep; see `docs/handoff/okx-sweep-basis-internal-rows.md`.
- No hot or cold role is claimed: the PoR file gives none, and `exchange_wallet` is already a sweep destination (directness 0.8).
- Left out: `0x0003b5aa5e30e97fcc596bb5d0f3a75255e08d4e` (passes, but `test_por_labels.OKX_ETH_STORE_ROW` names it as a store-only row; no dropped row needs it), and 13 destinations the classification does not class `exchange_wallet`.

## Next

1. After merge: regenerate `okx_dest.json` from main and rerun `okx_deposits_scripts/build.py` + `verify.py`; expect 821 of the 825 dropped rows back (see the next-release notes kept with the label-store build, not in this repository; the 825 dropped rows and the 4 still left out after this PR are attached to label-store release `labels-2026-11-16` in sidhy4rth/exchequer-labels as `okx_por_ethereum_deposits.dropped.tsv` (SHA-256 f2f4467858e5b3dc9d298fa1e0a38cae44f7ce031200caf90f2b8e899d0c7cf2) and `okx_por_ethereum_deposits.dropped_after_277.tsv`).

## Open questions

- none

## Files mid-change (do not touch)

- none
