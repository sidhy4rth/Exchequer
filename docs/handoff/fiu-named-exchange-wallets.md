# Handoff: fiu-named-exchange-wallets

- **Feature**: a trace that ends in a wallet of an exchange FIU-IND acted against, but that had no wallet in the label files, now names that exchange, so the FIU-IND note (`EXCHEQUER_FIU_IND_NOTE`) can appear
- **Issue**: #342 (batch 1), #354 (batch 2)
- **Branch**: `data/fiu-exchange-wallets` (batch 1), `data/fiu-exchange-wallets-2` (batch 2, stacked on #343)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: batch 1 (BingX, LBank, XT.com, Phemex, Bitrue) in PR #343; batch 2 (MoonPay, WOO X, Paxful, ProBit Global, LCX, CEX.IO) in PR #355, stacked on #343; both ready for review

## Done

- `backend/data/fiu_named_exchanges.json`: 105 rows (81 addresses): BingX 62, LBank 20, XT.com 16, Phemex 5, Bitrue 2; Ethereum 79, Polygon 26. Each row: the explorer page it came from, the page's own "As at" time, the UTC day read (15 Nov 2026 UTC). `_meta.left_out` lists every candidate not taken and why.
- The same rows in `exchange_labels.json` and `exchange_labels_polygon.json` (`_meta.fiu_named_exchanges` in each).
- `backend/data/fiu_ind_status.json`: entries for the five (PIB release 2173758 for BingX, LBank, Bitrue, Phemex; 2308131 for XT.com); none is in USQ 5805 Annexure-I (re-read 15 Nov 2026 UTC, SHA-256 `cd2c2281…59c7`, same as the original read). `_meta.rule` now says 34 named exchanges are left out.
- Release gate 6 (`docs/label-releases.md`): the 79 new Ethereum labels' code read alone with `check_label_code.record` (keyless node, block 26422970) into `tests/fixtures/label_code/ethereum.json` (`_meta.read_since` says so), then `check_label_code` run without flags: 0 retyped, XT.com: Hot Wallet listed as EIP-7702 delegated.
- `backend/tests/test_fiu_named_exchanges.py`: shape and sources, tag reads as the exchange and is not infrastructure, label files carry each row exactly, no collision with any other list, the India set, a demo or a test, left-out addresses unlabelled, the drained XT.com wallet unlabelled, each exchange's FIU-IND entry, and a trace into one wallet of each exchange names it and carries its FIU-IND note.

- Batch 2 (#354, PR #355): `app/tron_tags.py` CANONICAL reads Paxful, CEX.IO, LCX, ProBit Global, WOO X and MoonPay (names from PIB 2173758, PIB 2308131 and USQ 5805 Annexure-II, spelt as the explorers tag them), with tests in `test_tron_tags.py`. 37 rows (25 addresses): MoonPay 8 + 7, WOO X 7 + 2, Paxful 3 + 2, ProBit Global 3 + 1, LCX 2 + 1, CEX.IO 1 + 0 (Ethereum + Polygon), same method and fields, read 15 Nov 2026 UTC; `_meta.batches` says which batch each exchange is in. Their `fiu_ind_status.json` entries (MoonPay from Annexure-II, which no PIB release names it in). The 24 new Ethereum labels' code recorded into the label-code fixture (block 26423086); `check_label_code`: 0 retyped, MoonPay 7 and LCX 1 listed as EIP-7702 delegated.

## Decisions

- Source: the explorer's own public name tag on each address's page, read keylessly from the page title, as `data/india_exchanges.json` round 1 does; candidates came from dawsbot/eth-labels @ 14247ba8. No ownership is inferred. No first-party wallet list of the five could be read without a browser (see `_meta.first_party_sources`).
- A row needs transactions on that chain's explorer page. Each chain's own tag is the label (an address can read "XT.com 3" on Ethereum and "XT.com 2" on Polygon).
- An address tagged as a deposit funder on one chain is left out on every chain (`0x4fd7c9bd…`: "XT.com: Deposit Funder" on Etherscan, "XT.com 1" on PolygonScan).
- Left out: BingX 16 (a recorded demo names it as a statement counterparty), and XT.com 11 (`0xdb3ded77…`), which XT.com's 28 Nov 2024 statement names as the platform wallet assets were moved out of; who controls it since is not established.
- One XT.com wallet's code is an EIP-7702 delegation; it is an account, typed `exchange_wallet`.

- Batch 2 left out: LCX 2 (`0x4631018f…`), which sent the 8 Jan 2022 transfers to the address `threat_labels.json` labels "LCX Hacker" (drained wallet); LCX 3 (`0x2957ea6d…`), a control wallet in `data/validation/corpus.json`; CEX.IO (`0xc9f5296e…`), a statement counterparty in a recorded demo; Woo X 4 (`0xea319fd7…`), a Gnosis Safe proxy (a contract the exchange runs); and tags with a role the reader does not know ("MoonPay: Withdrawals 1", "LCX: Company Reserve", "Woo X: Team").
- LAToken and SimpleSwap were not taken: their names contain "token" and "swap", which `tron_tags.NOT_AN_EXCHANGE` and `scripts/_tag_words.NOT_CASH_OUT` treat as infrastructure, so a tag like "LAToken 6" never reads as an exchange. Taking them needs a narrow exception in both filters (owner's call).

## Next

1. Batch 3: YouHodler (2 Ethereum + 1 Polygon tags read), Changelly (1 Ethereum) and Mercuryo (1 Ethereum + 1 Polygon) have explorer tags in dawsbot/eth-labels; each needs a CANONICAL line, then the same method and their `fiu_ind_status.json` entries. LAToken and SimpleSwap need the filter decision above first.
2. BSC and Arbitrum rows for the five: BscScan and Arbiscan pages sit behind a bot check; a person in a browser, or a first-party list, is needed.
3. Replace or corroborate with a first-party list if any of the five publishes one readable without a browser (Phemex's proof-of-reserves page, which press coverage says shows part of its cold-wallet addresses, loads its data in the browser only).

## Open questions

- Should LAToken and SimpleSwap get a narrow exception in the two tag filters ("token"/"swap" inside the exchange's own name)? (Sidhyarth)
- Should LCX 3 be labelled and the validation corpus rebuilt without it as a control? (Sidhyarth)

- Should the BingX 16 wallet (`0x1651d700…`) be labelled and the recorded demo that names it re-recorded? It appears there only as a credit counterparty in a wallet statement. (Sidhyarth)

## Files mid-change (do not touch)

- none
