# Handoff: contract-wallet-roles

- **Feature**: a deposit address that sweeps into an exchange's contract-held hot wallet is read as a deposit, because that contract wallet's role is measured on chain and recorded
- **Issue**: #253, then #269
- **Branch**: `labels/contract-wallet-roles` (measurement, PR #254), then `labels/contract-wallet-roles-apply` (the roles, stacked on it)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: roles on main (#268); round 2 (#269) measured Bitget's 12 Ethereum wallets: no role

## Done

- `backend/scripts/measure_contract_wallet_roles.py`: for every role-less exchange `contract_wallet` (81 rows on 4 EVM chains: 34 Ethereum, 22 Arbitrum, 22 Polygon, 3 BSC), reads keylessly from Blockscout's public API whether the exchange's deposit-shaped addresses sweep into it (the #248 method), and writes `backend/tests/fixtures/contract_wallet_roles.json`. `--apply` writes the roles into the label files; `--check` (offline) compares them. Gate 7 in `docs/label-releases.md`.
- Measured 15 Nov 2026: 5 Ethereum wallets meet the rule (Kraken 5, Coinbase 10, Crypto.com: MultiSig, Gemini 2, WazirX 5). WazirX 5 and Crypto.com: MultiSig are held (`HELD` in the script); the other 3 get `role: hot_wallet` in the stacked PR (`--apply`, which also writes `_meta.contract_wallet_roles_2026_11_15` in `exchange_labels.json`). `docs/suite-features.md` row 1 says so.
- Tests: `backend/tests/test_contract_wallet_roles.py`.

## Decisions

- A role comes only from a source or this measurement, never a guess. No exchange source the repository records gives a hot or cold role for any of the 81 (Bybit's and OKX's PoR files say so in `source_kind`).
- Rule: at least 10 of a seeded sample of up to 30 unlabelled, non-contract senders each sent the wallet 2+ transfers and value nowhere else (except the same exchange's labelled wallets). Zero-value token transfers are ignored (address poisoning). A forwarder is never measured.
- Arbitrum and Polygon Blockscout answered every API call with a browser challenge (403) on 15 Nov, and BSC has no Blockscout, so those 47 rows stay role-less ("not measured"). Node `eth_getLogs` alone misses native payments, so it was not used instead.

## Next

1. Later (owner's call): re-run `--record` when Arbitrum/Polygon Blockscout answer again, then `--apply`, run the suite and `scripts/check_demos.py`.

## Open questions

- none. Owner's decisions (15 Nov): Gemini 2 keeps its role at exactly 10 of 30 (the threshold is the rule); Crypto.com: MultiSig gets no role, because every sweep read is from 2019 to 2020 (measurement kept in the fixture); WazirX 5 stays role-less and the India exchanges seed and test are left as they are; Arbitrum, Polygon and BSC wait for a later run.

## Files mid-change (do not touch)

- none

## 15 Nov, later: landing on main
#262 was merged into its base branch (`labels/contract-wallet-roles`) instead of `main`, so its three roles never reached `main`; and #258 then added 16 Bitget contract wallets (12 Ethereum, 4 BSC) that the evidence file did not list, which failed `test_every_measured_row_is_a_contract_wallet_and_every_roleless_one_was_measured` on `main`. This PR lands #262's content on `main` and re-records the evidence with the new `--record --offline --cache DIR`: answers come only from the 15 Nov cache, and a wallet with no cached answer is recorded as "not measured yet" with no role. Measure the 12 Ethereum Bitget wallets online later (`--record --cache DIR`, no `--offline`).

## 15 Nov, round 2 (#269)
- `--record --cache DIR` (online, keyless Blockscout) measured the 12 Ethereum Bitget contract wallets #258 added. None met the rule: at most 17 unlabelled senders were found, and none of them swept only into the wallet (6 of the 12 had 3 senders or fewer; 3 had none). They stay role-less, each with its reason in the fixture. Every other row was answered from the cache and is unchanged.
- Arbitrum, Polygon and BSC: no keyless indexer can do the method. arbitrum/polygon.blockscout.com still answer with a browser challenge (403); Routescan's keyless API says "chain not supported" for all three; publicnode's Arbitrum node refuses log reads without a token, and its Polygon and BSC nodes read logs only for one named contract over at most 10,000 or 50,000 blocks, so a sender's outflows in every token (and its native payments) cannot be read. The 51 rows there stay "not measured" (comment above `BLOCKSCOUT` in the script).

## 15 Nov, apply takes back its own roles (fix/roles-apply-removes)
- Reviewer finding: `--apply` never removed a role. A wallet an earlier `--apply` gave `hot_wallet`, measured role-less by a later `--record`, dropped out of `_meta`'s `given` but kept `role: hot_wallet`; the next `--record` then skipped it (it had a role and was no longer in `given`), so `--check` stopped comparing it.
- Fix: `apply()` removes the `role` of a wallet listed in the previous `given` when the evidence now says role-less (also when no wallet on the chain gets a role); roles from any other source (#248's OKX proxy, PoR rows) are never touched. `roleless()` also includes every wallet the evidence file measured, so it is re-measured and `--check` keeps comparing it.
- No-op on today's data: `--check` passes, `--apply` leaves every label file and the evidence file byte-identical, `roleless()` returns the same sets as before on all 4 EVM chains.
