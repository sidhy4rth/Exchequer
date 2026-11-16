# Handoff: contract-wallet-inference

- **Feature**: the contract_wallet retype of #234 changes nothing a trace concludes: the retyped rows keep their old type as a `role`, which deposit inference and scoring read
- **Issue**: #237
- **Branch**: `fix/contract-wallet-inference` (stacked on `fix/contract-wallet-types`, PR #234)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: merged with #234 (as #238) on 2026-11-15

## Done

- Each of the 26 rows #234 retyped records the type it had as `"role"` (20 exchange_wallet, 4 cold_wallet, 2 hot_wallet); `check_label_code.apply` writes it on any later retype.
- `exchange_matcher.role_of`: a contract_wallet with a role in hot/cold/exchange wallet is read as that role. The matcher loads `role` only on a contract_wallet row; `ExchangeMatch.role` carries it.
- Deposit inference: a sweep into a contract_wallet counts only through its role, and never when `never_flag` calls the address a token, DEX router or system address.
- Scoring: match directness uses the role, so the six hot/cold rows stay at 1.0 and the 20 exchange_wallet rows at 0.8.
- Guard: `tests/test_label_code.py` checks the labels its recording holds and warns, naming what to run, on any added since. `python -m scripts.check_label_code --check` (offline, writes nothing) fails on an unread label; it is a gate in `docs/label-releases.md`.

## Decisions

- Contract wallets with no role (the 34 older Ethereum ones and the proof-of-reserves ones on other chains) are still not sweep destinations: the label audit gave that type to deposit forwarders, and admitting them would change traces.

## Next

1. Done: merged with #234 on 2026-11-15.

## Open questions

- ~~Should the older contract_wallet rows with no role get a role and count as sweep destinations?~~ Answered by #253: measured on chain in #254 (`952e3b79`), roles on main in #268 (`fdaa9219`), Bitget round in #270 (`fcd6b0a8`); see `contract-wallet-roles.md`.

## Files mid-change (do not touch)

- none
