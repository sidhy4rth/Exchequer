# Handoff: contract-wallet-types

- **Feature**: an Ethereum exchange label typed hot, cold or exchange wallet is an account the exchange holds the key to, never a contract
- **Issue**: #233
- **Branch**: `fix/contract-wallet-types`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: merged in #234 (with #238) on 2026-11-15

## Done

- `scripts/check_label_code.py` read the code of all 1,252 non-deposit Ethereum exchange labels with keyless `eth_getCode` (publicnode, block 26416966) and kept the answers in `tests/fixtures/label_code/ethereum.json`.
- 26 labels on proxy or forwarder contracts retyped `contract_wallet` (20 exchange_wallet, 4 cold_wallet, 2 hot_wallet). Each is listed with its reason in `_meta.code_check_2026_11_15.retyped`.
- 6 EIP-7702 delegated accounts kept their type, listed in `_meta.code_check_2026_11_15.eip7702_delegated`.
- 25 other contracts kept their type, listed in `_meta.code_check_2026_11_15.left_for_review`.
- Guard tests in `tests/test_label_code.py`, offline on the recording.
- #249 (`fix/check-label-code-default`): a run without flags kept none of the 26 retyped rows in the note (a fresh plan no longer lists them) and `--record` dropped answers the node did not give; both now merge into what is recorded, and a rerun on an unchanged file changes nothing.

## Decisions

- EIP-7702: the account still has its own key, held by the exchange, so it stays a keyed wallet. The label schema has no note field, so the delegation is listed in `_meta`.
- Proxy: code of 1 KB or less that uses DELEGATECALL (EIP-1167, Gnosis Safe proxy, EIP-1967, older delegatecall proxies). Forwarder: code of 1 KB or less with no functions whose fallback CALLs out. Anything else is "other" and needs a person to read it.
- The guard checks the recorded labels; a new Ethereum keyed-wallet label is caught by `check_label_code --check` at import (#237).

## Next

1. Owner: decide the 25 review rows (see Open questions).

## Open questions

- 14 of the 25 review rows are multisig wallets by their verified source on Blockscout (11 BitGo `WalletSimple`, 3 Gnosis `MultiSigWallet`). Retype them `contract_wallet` too? (Sidhyarth)
- Answered by #237 (`fix/contract-wallet-inference`): each retyped row keeps its old type as `role`, and deposit inference and scoring read the role, so a deposit sweeping into Bitget Hot Wallet 1 or 2 is inferred as before.

## Files mid-change (do not touch)

- none
