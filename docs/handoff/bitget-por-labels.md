# Handoff: Bitget proof-of-reserves labels

- **Feature**: label Bitget's own reserve wallets on Ethereum, BNB Smart Chain and Tron from its proof-of-reserves API
- **Issue**: #257
- **Branch**: `labels/bitget-por`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: PR #258 ready for review

## Done

- 21 rows (PR #258): Ethereum 12 and BSC 4 `contract_wallet` (EIP-1167 minimal proxies, no role) through the new `backend/scripts/import_bitget_por_labels.py`, which reuses `import_por_labels.py` (#226) for its checks, numbering and writing. Tron 5 `exchange_wallet` through `import_por_tron_labels.py` (#221), with three new `por:bitget:YYYY-MM` sources and a `bitget_json` parser.
- The four API answers the rows cite are in `backend/tests/fixtures/bitget_por/`, byte for byte (an answer to a POST has no Internet Archive copy). `tests/test_bitget_por_labels.py` checks every row against them.
- `tests/fixtures/label_code/ethereum.json`: the 12 Ethereum answers added (from a full `check_label_code --record` run whose other answers were unchanged), with `read_since` notes, as #248 did.

## Decisions

- Same method as #221 (Tron) and #226 (EVM). EVM rows also carry `source_audit` (the audit id in the POST body) and `source_sha256`, because one URL serves every audit.
- Each address cites the newest audit that lists it; `_meta.por_bitget_2026_11_15` in each EVM file records every answer read (12 audits) and the ones cited.
- `contract_wallet` with no `role`: Bitget's list gives no hot or cold role, and nothing was read on chain to support one (#248's `role_basis` method).
- `tests/test_por_labels.py::_por_rows` leaves out rows with a `source_audit` (as it already does for `role_basis` rows): they have no archive copy and are checked in their own test file. Every assertion there is unchanged.
- Bitcoin (no bitcoin chain in the repo) and the untraced chains (Optimism, AVAX C-Chain, Solana, zkSync Era) are left out. The 13 addresses already labelled Bitget keep their rows.

## Next

1. Owner: merge #258 when green. The `labels/contract-wallet-roles` branch (#254) works on contract_wallet roles in the same label files. This PR only adds rows and one new `_meta` key, so the two should merge cleanly. If #254 gives role-less contract wallets a role from sweep evidence, these 16 rows are candidates.

## Open questions

- Should these 21 also go on the hunt's `never_poison_services.txt` (outside the repo)? They are not on it today.

## Files mid-change (do not touch)

- none
