# Handoff: okx-consolidation-wallets

- **Feature**: a trace through one of OKX's per-customer Ethereum deposit addresses can be read as an OKX deposit, because the two wallets OKX sweeps USDT and USDC into today are labelled
- **Issue**: #246
- **Branch**: `feat/okx-consolidation-wallets`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: in review

## Done

- `backend/data/exchange_labels.json`: `0x559432e18b281731c054cd703d4b49872be4ed53` ("OKX: Reserve Wallet 216", `hot_wallet`, an account) and `0x445f16314284b43dfa1fd3cd77b9dea4a1bebd97` ("OKX: Reserve Wallet 215", `contract_wallet` with role `hot_wallet`, an ERC-1967 proxy). Both rows cite OKX's November 2026 PoR file exactly as the #226 rows do, and add `role_basis`: the on-chain reading the hot role stands on. `_meta.okx_consolidation_2026_11_15` gives the PoR file's lines for each, the conflict and chain checks, and the label-store overlap.
- `backend/tests/fixtures/label_code/ethereum.json`: the two answers (read at block 26419391 by `scripts.check_label_code --record`, every other answer unchanged) are recorded under `_meta.read_since`, as #247 recorded Unocoin; the fixture's `block` stays 26416966, and a flag-less `scripts.check_label_code` run (#250) rewrote the `_meta` note.
- Tests: `backend/tests/test_okx_consolidation_labels.py`. `test_por_labels._por_rows` now leaves out rows with a `role_basis` (they are checked in the new file).

## Decisions

- The PoR file gives no role. The hot role comes from on-chain reads (15 Nov 2026, keyless RPCs): in a seeded random sample of 300 of OKX's 17,046 Ethereum PoR addresses, 25 small-balance addresses swept to the USDT wallet and 31 to the USDC proxy, sending value nowhere else. Each row says so in `role_basis`.
- The rows' numbers come from `import_por_labels.numbering`, so they stay unique across chains.

## Next

1. If a later OKX PoR file drops either address, recheck the role before keeping it.
2. `0xa9ac43f5b5e38155a288d1a01d2cbc4478e14573` also receives ETH sweeps from OKX PoR addresses but is in no OKX source; it needs a source before it can be labelled.

## Open questions

- none

## Files mid-change (do not touch)

- none
