# Handoff: okx-tron-own-wallets

- **Feature**: OKX Tron deposit addresses that sweep into an OKX wallet other than Hot Wallet 8 can get an ADR-0012 deposit row, because OKX's own Tron wallets from its proof-of-reserves list are labelled
- **Issue**: #298
- **Branch**: `labels/okx-tron-own-wallets`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: in review (PR #304)

## Done

- `backend/data/exchange_labels_tron.json`: 10 OKX Tron wallets ("OKX: Reserve Wallet 264" to "273"), typed `exchange_wallet`, each citing OKX's November 2026 PoR file with a `sweep_basis`; `_meta.okx_own_wallets_2026_11_15` holds the source, the rules, the evidence file's SHA-256, what was left out and why, and the checks. Counts updated.
- `backend/scripts/classify_okx_tron_wallets.py`: the keyless TronGrid reader and the recorded rules (`classify`).
- `backend/tests/fixtures/okx_tron_own_wallets.json`: the reads of 15 Nov 2026 for all 21 candidates and each one's class.
- `backend/scripts/seed_tron_labels.py`: `keep_previous` keeps a `sweep_basis` row as it keeps a `por:` row.
- Tests: `backend/tests/test_okx_tron_own_wallets.py`.

## Decisions

- Only wallets OKX's own PoR file lists, and that keyless on-chain reads show to be OKX's own operating wallets by recorded rules, are labelled. Deposit-like addresses are left out.
- Only real USDT (`contract_address` filter, `Transfer`, value > 0) and successful TRX transfers count: fake-token events with a forged `from` made one sweep-only address look like a payer in an unfiltered read.
- No hot or cold role is claimed; numbers continue after the Ethereum OKX Reserve Wallets (263) so none is shared across chains.
- 5 addresses that pass are left out because a recorded demo and the contract fixture use them (TM1zz..., TJbHp48..., TCz47..., TWGZ..., TSaRZ...).

## Next

1. After merge: let the Tron deposit-row join accept the 10 new destinations (see `~/exchequer-flagged/store/NEXT-RELEASE.md`).
2. Owner decision: re-record the demo and `tests/fixtures/contract/exchange_wallet.json` by their scripts, then label the 5 left-out wallets the same way.

## Open questions

- none

## Files mid-change (do not touch)

- none
