# Handoff: custody-balance-check

- **Feature**: suite feature 9, part 2: read each custody address's balance on chain and flag where it differs from what the asset register records
- **Issue**: #332
- **Branch**: `feat/custody-balance-check` (#333), then stacked `feat/custody-balance-runs`, `feat/custody-balance-panel`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: three stacked PRs ready for review, behind `EXCHEQUER_CUSTODY_BALANCE_CHECK` (off)

## Done

- Part 1 (#333, `feat/custody-balance-check`): `backend/app/custody_balance.py` reads and compares (`read_all`), flag `EXCHEQUER_CUSTODY_BALANCE_CHECK`; tests in `backend/tests/test_custody_balance.py` on the real provider clients over `httpx.MockTransport` (no network).
- Part 2 (`feat/custody-balance-runs`): each run stored (model `CustodyBalanceCheck`, migration `g7_custody_3`, one table `custody_balance_checks`), `GET/POST /trace/{case_id}/custody-balance` in `backend/app/routes/custody.py`, route and migration tests; `docs/flag-rollout.md`, `docs/suite-features.md` row 9.
- Review nits (16 Nov), part 1: staked TRX counted (see Decisions); a register amount with more decimal places than the asset has is "not checked" with "The recorded amount, <x>, has more decimal places than <asset> allows (<n>) ...", the chain's figure still shown, never a mismatch (trailing zeros do not count as places). 4 new tests. Part 2: `GET /trace/{case_id}/custody-balance` also returns `can_check` (false for the demo caller, whom the POST refuses) and `check_note`, as `GET /identifiers` does with `lookups_enabled` / `lookups_note`.
- Part 3 (`feat/custody-balance-panel`): `frontend/src/components/case/CustodyBalance.jsx` (+ `.css`, `.test.jsx`) on the Letters tab under the custody wallets (one import, one line in `LettersTab.jsx`); `fetchCustodyBalance` / `runCustodyBalance` in `frontend/src/api/custody.js`. Review nit (16 Nov): "Check balances on chain now" shows only when the GET says `can_check`; a demo caller sees `check_note` instead, and the last run still shows. 1 new test.

## Decisions

- Behind its own flag, off by default, separate from `EXCHEQUER_CUSTODY_WALLETS`: it reads the register, which is live, and spends provider allowance.
- What is compared: asset-register rows with holder custody and status held, readable by the viewer, summed per chain, address and asset. The address is the linked custody wallet's (custody.py), else the row's own `held_at` if valid on the row's chain; otherwise the row is "not checked" and says why.
- Three outcomes: match (exactly equal, exact decimals), mismatch (more or less, with the gap in words), unchecked (asset not read on that chain, no address, provider not configured, allowance spent, or no usable answer). Unchecked is never shown as a match. The panel says each in words; colour only repeats it.
- Reuses the trace engine's clients through `chain_data.open_source` and their own request paths (`_request`, `_rpc`, `_get`): same pacers, daily allowance, key redaction and evidence log; no new HTTP code and no change to the client files. One retry per read (inside a web request), at most `MAX_READS` (10) address-asset pairs per run.
- Decimals always from `config.CHAINS` (native or token), never from the provider's answer. Etherscan: `account/balance` or `account/tokenbalance` at `latest` (never cached). NodeReal: `eth_getBalance` or ERC-20 `balanceOf` by `eth_call` at the client's head block (head less its index lag), so the answer is for a stated block. TronGrid: `/v1/accounts/{address}`; a missing `balance` field is 0 TRX, a token absent from `trc20` is 0, and no account record at all is "not checked". TRX counts staked TRX too, since TronGrid's `balance` is only the free part: the account's own stake (`frozenV2[].amount`, Stake 1.0 `frozen[].frozen_balance`, `account_resource.frozen_balance_for_energy`), stake it delegated out (`delegated_frozenV2_balance_for_bandwidth`, `account_resource.delegated_frozenV2_balance_for_energy`, and the Stake 1.0 `delegated_frozen_*` twins) and stake being unstaked (`unfrozenV2[].unfreeze_amount`), field names from TRON's account schema (developers.tron.network/reference/get-account-info-by-address). Stake delegated to it (`acquired_*`) is someone else's and is left out. The result gives `staked_amount` and says it in words.
- Running a check needs a signed-in officer (it spends allowance); reading the last run does not. Audit detail is the check id and counts only.
- A result where the chain shows more than the register is still a mismatch; its text says another case's money in the same wallet would show like this.

## Next

1. Owner: switch on per `docs/flag-rollout.md` (section `EXCHEQUER_CUSTODY_BALANCE_CHECK`) once reviewed; try it on an address the unit controls.
2. If another migration off `g7_statements_2` merges first, re-point `g7_custody_3`'s `down_revision` so `alembic heads` shows one head.

## Open questions

- A unit wallet recorded in several cases: should the check sum held rows across all cases the viewer can read at that address, instead of this case's only? Today it is per case, and the "more on chain" text says why it may differ. Sidhyarth / Barenyam to decide.

## Files mid-change (do not touch)

- none
