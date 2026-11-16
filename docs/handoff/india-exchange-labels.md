# Handoff: India exchange labels

- **Feature**: a set of Indian exchange wallets, each row with its public source, so a trace that reaches one names the exchange
- **Issue**: #134 (round 1), #207 (round 2), #245 (round 3), #361 (round 4)
- **Branch**: `feat/india-exchange-labels` (round 1); round 2 is stacked on it as `feat/india-exchange-labels-2`, `-3`, `-4`; round 3 is `feat/india-por-coindcx-unocoin` off main; round 4 is `feat/india-wazirx-por-page2` off main
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: rounds 1 and 2 merged in #135 (with #209, #210, #211); round 3 merged in #247; all on 2026-11-15

## Done

- round 1 (#135): 26 rows (WazirX 5, CoinDCX 5, CoinSwitch 16) from explorer name tags and CoinSwitch's Jan and Jul 2023 wallet lists
- round 2, part 1 (`-2`): 51 rows. WazirX 7 (BSC 2, Arbitrum 1, Tron 4) from WazirX's own proof-of-reserves page as the Internet Archive kept it (11 Nov 2024); CoinSwitch 44 from its third, fourth and fifth proof-of-reserves posts (May 2024, Oct 2024, May 2025): BSC 10, Tron 9, Arbitrum 3, Polygon 2, and the 20 Ethereum wallets whose latest listing is the third or fourth edition. 14 left out (10 with no activity seen, 4 Tron rows whose link and shown address disagree), listed in `_meta.left_out`
- round 2, part 2 (`-3`): 62 CoinSwitch Ethereum wallets in the fifth edition that an earlier edition also lists
- round 2, part 3 (`-4`): 29 CoinSwitch Ethereum wallets listed only in the fifth edition
- round 3 (`feat/india-por-coindcx-unocoin`): 7 rows. CoinDCX 6 (Tron 5, BSC 1) from the wallet list CoinDCX's own post of 24 Nov 2022 says it published through Nansen Portfolio (the list is in the dashboard's JavaScript bundle; both cited as Internet Archive copies with SHA-256); Unocoin 1 (its Ethereum cold-storage wallet from its own June 2023 proof-of-reserves post). 27 listed CoinDCX wallets already labelled CoinDCX kept as held (`_meta.listed_by_coindcx_and_already_labelled`, including `0x3698...4384`, round 1's "CoinDCX 3"); 12 left out (no activity, or a Tron account created after the list with dust only; Unocoin's address on chains its post does not name)
- round 4 (`feat/india-wazirx-por-page2`): 9 WazirX rows (Ethereum 7, BSC 2) from the second page of WazirX's own proof-of-reserves data (`x.wazirx.com/api/v2/wazirx-wallet-addresses?limit=30&page=2`). The Internet Archive holds only the first page, so this page was read from WazirX's own server. It serves the same 24 Oct 2024 snapshot, and its first page matches round 2's rows. Each row carries the SHA-256 of the response; the response itself is kept outside the repo (`~/exchequer-flagged/resume-17nov/checks/`). `0x618f...2bd7` is held on Ethereum as "WazirX: Withdrawals" (Etherscan tag) and is now also a BSC row, because WazirX lists it under BSC. The searches are written up in `~/exchequer-flagged/resume-17nov/checks/india-sources-17nov.md`
- every row is in `data/india_exchanges.json` and in its chain's label file; `tests/test_india_exchanges.py` checks the two agree

## Decisions

- sources: an explorer's own public name tag on the address page, or a wallet list the exchange published itself (CoinSwitch's posts; WazirX's proof-of-reserves page). An Internet Archive copy is cited with its timestamp
- a row needs activity on its chain, read without a key: nonce > 0, a balance, or contract code (EVM); an existing account that is not a contract (Tron)
- a list row whose link and shown address disagree is left out, unless a later edition lists the address cleanly (CoinSwitch's AXS wallet `0x758e...ef43`, now a row)
- `0x294b...34d9`: CoinSwitch's third edition lists it again; the label file still has it as Binance 41; reported, not overwritten
- CoinDCX's Nov 2022 post pointing to its Nansen-hosted list counts as CoinDCX's own statement (owner, 15 Nov 2026); each such row cites the post (`statement`) and the list (`source`), each with its archived copy's SHA-256
- CoinGabbar's pages (where WazirX's Jan 2023 PoR PDF says its wallets are listed) and CoinDCX's PoR posts gave nothing usable through the archive; coindcx.com is behind a bot check, not read

## Next

1. ~~owner decides the 0x294b conflict (CoinSwitch's lists vs Etherscan's "Binance 41")~~ Decided by the owner: 0x294b…34d9 stays labelled Binance (owner decisions in issue #193).
2. still no public source for ZebPay, Bitbns, Giottus, Mudrex or BuyUcoin wallets (round 4 looked again: Giottus's own PoR page ships an empty list and has no archived copy; ZebPay's PoR post has archived copies, but they and zebpay.com met bot checks and were not read)
3. WazirX's server still serves its whole list (8,073 pages of 30, same 24 Oct 2024 snapshot). Rounds 2 and 4 used pages 1 and 2. Reading more pages is a bulk fetch from WazirX's server and needs the owner's go-ahead. A request for bigger pages was refused by the session's permission check and was not retried
4. add rows to `india_exchanges.json` and the chain label file together (the tests check they agree)

## Open questions

- Next 3: whether to read more pages of WazirX's list (Next 1 answered in issue #193)

## Files mid-change (do not touch)

- none
