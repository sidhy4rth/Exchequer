# Handoff: custody-trx-stake-check

- **Feature**: suite feature 9 follow-up: check the custody balance check's TRX sum (free balance plus stake) on real Tron accounts against TronScan
- **Issue**: #376
- **Branch**: `trxstake-verify`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: done, in review; no counting error found, no code changed

## Done

- Five public accounts read keyless on 2026-11-16 (24 API requests in all, at least 1.5 s apart: 17 to TronGrid `/v1/accounts`, 1 to TronScan's SR list, 6 to TronScan's account APIs, which answered 401 without a key; so TronScan's figures were read from its account pages in a browser, one visit each). Saved, trimmed to the fields that matter, in `backend/tests/fixtures/custody_trx_stake/` (each `_meta` gives the request, fetch time, SHA-256 of the whole answer, what was dropped, and TronScan's figures).
- `backend/tests/test_custody_trx_stake.py`: the module's total for each equals the figure derived field by field and TronScan's TRX total, to the sun.

| Account (TronScan name) | What it has | Module total (TRX) | TronScan total (TRX) |
|---|---|---|---|
| TMG95kirH4cKW5GnKoCcCye1dBqbt77yGu (MinerGate SR) | 2.0 own bandwidth, delegated out bandwidth + energy | 6,975,373.304661 | 6,975,373.304661 |
| TDD97yguPESTpcrJMqU6h2ozZbibv4Vaqm (Cryptomus SR) | 2.0 own energy, delegated out energy | 18,898,084.619669 | 18,898,084.619669 |
| TAuUCiH4JVNBZmDnEDZkXEUXDARdGpXTmX (HTX-Cold 6) | unfrozenV2 (bandwidth + energy), delegated in | 786,759,959.026665 | 786,759,959.026665 |
| TBsyKdNsCKNXLgvneeUJ3rbXgWSgk6paTM (Kraken SR) | Stake 1.0 frozen bandwidth + energy, delegated in | 40.000002 | 40.000002 |
| TLyqzVGLV1srkB7dToTAEqgDSfPtXRJZYH (Binance Staking SR) | delegated in only (all four kinds) | 617.559505 | 617.559505 |

## Decisions

- Unclaimed SR or voting rewards (`allowance`) stay out of the total: they are not in the account's balance until claimed, and TronScan shows them apart ("Claimable Rewards"), not in its TRX total.
- Cryptomus delegates many times a minute: its stake moves between `frozenV2` and `delegated_frozenV2_balance_for_energy`, and three reads two minutes apart kept the same 18,879,500 TRX sum, which shows delegating moves stake out of `frozenV2` (no double count). The fixture is the read made right after the TronScan page.

## Next

1. Nothing. If Stake 1.0 stake delegated out (`delegated_frozen_balance_for_bandwidth`, `account_resource.delegated_frozen_balance_for_energy`) is ever seen on a real account, add it as a sixth fixture: none of the five has it.

## Open questions

- none

## Files mid-change (do not touch)

- none
