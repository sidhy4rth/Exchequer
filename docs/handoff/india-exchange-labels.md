# Handoff: India exchange labels

- **Feature**: a first set of Indian exchange wallets, each row with its public source, so a trace that reaches one names the exchange
- **Issue**: #134
- **Branch**: `feat/india-exchange-labels`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: PR #135 ready for review

## Done

- `backend/data/india_exchanges.json`: 26 rows (WazirX 5, CoinDCX 5, CoinSwitch 16; Ethereum 20, Polygon 4, BSC 1, Tron 1), each with source URL, source date and retrieval date; what was left out and why, and one conflict, are in its `_meta`
- the same 26 addresses added to `exchange_labels.json`, `_polygon`, `_bsc`, `_tron` as `{exchange, label, type}`, so the matcher, never-flag check and letters read them unchanged
- `app/tron_tags.py`: "coinswitch" added to `CANONICAL`, so a TronScan tag naming CoinSwitch reads as CoinSwitch (the Tron label file's labels must read back as their exchange)
- `tests/test_india_exchanges.py`: format, sources, validity, duplicates, agreement with the label files, no collisions with other lists or never-flag, left-out addresses unlabelled, and a trace that reaches a set address names the exchange (with a silent control)

## Decisions

- sources: an explorer's own public name tag on the address page (etherscan.io, polygonscan.com), or a wallet list the exchange published itself (CoinSwitch, Jan and Jul 2023); dawsbot/eth-labels and brianleect/etherscan-labels only supplied candidate addresses to look up
- an address with no transactions on that chain's page is left out, as the importers do
- WazirX's July 2024 attacked multisig (0x27fd...c9b4) is left out: who controls it since the attack is not established
- `0x294b...34d9`: CoinSwitch lists it as its own, the label file has it as Binance 41; reported, not overwritten
- pages behind a bot check (BscScan, Arbiscan, Etherscan label lists, CoinDCX and ZebPay PoR pages) were not read

## Next

1. owner decides the 0x294b conflict (CoinSwitch's list vs Etherscan's "Binance 41")
2. find public sources for ZebPay, Bitbns, Giottus, Mudrex, Unocoin, BuyUcoin; add rows to `india_exchanges.json` and the chain label file together (the tests check they agree)

## Open questions

- see Next 1

## Files mid-change (do not touch)

- none
