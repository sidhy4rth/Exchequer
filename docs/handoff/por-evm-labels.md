# Handoff: por-evm-labels

- **Feature**: a trace that ends in one of Bybit's or OKX's own wallets on Ethereum, BNB Smart Chain, Polygon or Arbitrum names that exchange, because the wallet is labelled from the exchange's own proof-of-reserves list
- **Issue**: #215
- **Branch**: `feat/bybit-okx-evm-labels` (stacked on `fix/label-quality`, #212, which holds #213)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: in review

## Done

- `backend/scripts/import_por_labels.py` reads Bybit's PoR CSV and OKX's PoR zip (downloaded by hand), keeps the 0x addresses each lists on the four chains, leaves out every conflict, reads each address on chain through a keyless public node, and adds the rows to `backend/data/exchange_labels*.json`. Each row carries `source_kind`, `source`, `source_archive`, `source_date` and `retrieved`; each file's `_meta.por_2026_11_15` names the files read (URL, Internet Archive copy, SHA-256, snapshot heights) and how many rows it added.
- Tests: `backend/tests/test_por_labels.py` (shipped rows' format and sources, no collisions, one label per address on every chain, a trace into a new Bybit wallet ends at Bybit, and the importer's rules).

## Decisions

- Neither file says hot or cold, so a row is `exchange_wallet` (the role is not recorded), or `contract_wallet` when the address holds contract code. The source's own words are in `source_kind`.
- Labels read "Bybit: Reserve Wallet N" / "OKX: Reserve Wallet N". An address keeps one number on every chain.
- An address the file already labels for the same exchange keeps its label. A conflict is left out and listed in the PR, never overwritten: an address listed by both exchanges, another exchange's label on any EVM chain, a never-flag token, a router/risk/threat/frozen/sanctions/gambling file, the instant-exchanger seed, a recorded demo, or a label-store row.
- "Used on this chain" means nonce > 0, or a native-coin, USDT or USDC balance. A listed address holding only other tokens is left out.

## Next

1. Each month both exchanges publish a new file. Rerun the script with the new file and a fresh `--sources` JSON; rows already held are kept, new wallets get the next numbers.
2. The PR's left-out list: owner to decide on the demo-named Bybit wallets (labelling them changes the recorded demos, which must then be re-recorded by `scripts/record_demos.py`).

## Open questions

- Should the recorded demos be re-recorded so the Bybit wallets they pass through are labelled? (Sidhyarth)

## Files mid-change (do not touch)

- none
