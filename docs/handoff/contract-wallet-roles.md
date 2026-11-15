# Handoff: contract-wallet-roles

- **Feature**: a deposit address that sweeps into an exchange's contract-held hot wallet is read as a deposit, because that contract wallet's role is measured on chain and recorded
- **Issue**: #253
- **Branch**: `labels/contract-wallet-roles` (measurement, PR #254), then `labels/contract-wallet-roles-apply` (the roles, stacked on it)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: both PRs ready for review

## Done

- `backend/scripts/measure_contract_wallet_roles.py`: for every role-less exchange `contract_wallet` (81 rows on 4 EVM chains: 34 Ethereum, 22 Arbitrum, 22 Polygon, 3 BSC), reads keylessly from Blockscout's public API whether the exchange's deposit-shaped addresses sweep into it (the #248 method), and writes `backend/tests/fixtures/contract_wallet_roles.json`. `--apply` writes the roles into the label files; `--check` (offline) compares them. Gate 7 in `docs/label-releases.md`.
- Measured 15 Nov 2026: 5 Ethereum wallets meet the rule (Kraken 5, Coinbase 10, Crypto.com: MultiSig, Gemini 2, WazirX 5). WazirX 5 is held (see Open questions); the other 4 get `role: hot_wallet` in the stacked PR (`--apply`, which also writes `_meta.contract_wallet_roles_2026_11_15` in `exchange_labels.json`). `docs/suite-features.md` row 1 says so.
- Tests: `backend/tests/test_contract_wallet_roles.py`.

## Decisions

- A role comes only from a source or this measurement, never a guess. No exchange source the repository records gives a hot or cold role for any of the 81 (Bybit's and OKX's PoR files say so in `source_kind`).
- Rule: at least 10 of a seeded sample of up to 30 unlabelled, non-contract senders each sent the wallet 2+ transfers and value nowhere else (except the same exchange's labelled wallets). Zero-value token transfers are ignored (address poisoning). A forwarder is never measured.
- Arbitrum and Polygon Blockscout answered every API call with a browser challenge (403) on 15 Nov, and BSC has no Blockscout, so those 47 rows stay role-less ("not measured"). Node `eth_getLogs` alone misses native payments, so it was not used instead.

## Next

1. Re-run `--record` when Arbitrum/Polygon Blockscout answer again, then `--apply`, run the suite and `scripts/check_demos.py`.

## Open questions

- WazirX 5 (`0x305dcaea…7b`) measured 21/30 sweepers, but its row comes from `data/india_exchanges.json`, which `tests/test_india_exchanges.py` holds to exactly exchange, label and type. Giving it a role means changing that seed and its test: owner's call (`HELD` in the script).
- Gemini 2 met the rule at exactly 10 of 30, and its sweeps and Crypto.com: MultiSig's are from 2017 to 2020 (see `blocks_read`). Keep them? (Sidhyarth)

## Files mid-change (do not touch)

- none
