# Handoff: Bitget proof-of-reserves labels

- **Feature**: label Bitget's own reserve wallets on Ethereum, BNB Smart Chain and Tron from its proof-of-reserves API
- **Issue**: #257
- **Branch**: `labels/bitget-por`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: claimed; rows being added

## Done

- nothing yet

## Decisions

- Same method as #221 (Tron) and #226 (EVM): one row per address, citing the source URL, the audit id, the retrieval date and the SHA-256 of the answer read.
- The 16 EVM addresses are EIP-1167 minimal proxies, so they are `contract_wallet` with no `role`: Bitget's list gives no hot or cold role and no on-chain reading was done to support one (#248's `role_basis` method).
- Bitcoin (no bitcoin chain in the repo) and the chains Exchequer does not trace are left out.

## Next

1. Add the rows, tests and source records.

## Open questions

- none

## Files mid-change (do not touch)

- none
