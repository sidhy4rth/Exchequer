# Handoff: India exchange labels

- **Feature**: a set of Indian exchange wallets, each row with its public source, so a trace that reaches one names the exchange
- **Issue**: #134 (round 1), #207 (round 2)
- **Branch**: `feat/india-exchange-labels` (round 1); round 2 is stacked on it as `feat/india-exchange-labels-2`, `-3`, `-4`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: merged in #135 (with round 2: #209, #210, #211) on 2026-11-15

## Done

- round 1 (#135): 26 rows (WazirX 5, CoinDCX 5, CoinSwitch 16) from explorer name tags and CoinSwitch's Jan and Jul 2023 wallet lists
- round 2, part 1 (`-2`): 51 rows. WazirX 7 (BSC 2, Arbitrum 1, Tron 4) from WazirX's own proof-of-reserves page as the Internet Archive kept it (11 Nov 2024); CoinSwitch 44 from its third, fourth and fifth proof-of-reserves posts (May 2024, Oct 2024, May 2025): BSC 10, Tron 9, Arbitrum 3, Polygon 2, and the 20 Ethereum wallets whose latest listing is the third or fourth edition. 14 left out (10 with no activity seen, 4 Tron rows whose link and shown address disagree), listed in `_meta.left_out`
- round 2, part 2 (`-3`): 62 CoinSwitch Ethereum wallets in the fifth edition that an earlier edition also lists
- round 2, part 3 (`-4`): 29 CoinSwitch Ethereum wallets listed only in the fifth edition
- every row is in `data/india_exchanges.json` and in its chain's label file; `tests/test_india_exchanges.py` checks the two agree

## Decisions

- sources: an explorer's own public name tag on the address page, or a wallet list the exchange published itself (CoinSwitch's posts; WazirX's proof-of-reserves page). An Internet Archive copy is cited with its timestamp
- a row needs activity on its chain, read without a key: nonce > 0, a balance, or contract code (EVM); an existing account that is not a contract (Tron)
- a list row whose link and shown address disagree is left out, unless a later edition lists the address cleanly (CoinSwitch's AXS wallet `0x758e...ef43`, now a row)
- `0x294b...34d9`: CoinSwitch's third edition lists it again; the label file still has it as Binance 41; reported, not overwritten
- CoinGabbar's pages (where WazirX's Jan 2023 PoR PDF says its wallets are listed) and CoinDCX's PoR posts gave nothing usable through the archive; coindcx.com is behind a bot check, not read

## Next

1. owner decides the 0x294b conflict (CoinSwitch's lists vs Etherscan's "Binance 41")
2. still no public source for ZebPay, Bitbns, Giottus, Mudrex, Unocoin or BuyUcoin wallets; WazirX's archived PoR data covers only its first page (30 wallets of 242,187)
3. add rows to `india_exchanges.json` and the chain label file together (the tests check they agree)

## Open questions

- see Next 1

## Files mid-change (do not touch)

- none
