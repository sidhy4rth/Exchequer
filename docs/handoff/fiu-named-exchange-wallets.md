# Handoff: fiu-named-exchange-wallets

- **Feature**: a trace that ends in a wallet of an exchange FIU-IND acted against, but that had no wallet in the label files, now names that exchange, so the FIU-IND note (`EXCHEQUER_FIU_IND_NOTE`) can appear
- **Issue**: #342 (batch 1), #354 (batch 2)
- **Branch**: `data/fiu-exchange-wallets` (batch 1), `data/fiu-exchange-wallets-2` (batch 2, stacked on #343)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: batch 1 (BingX, LBank, XT.com, Phemex, Bitrue) in PR #343, ready for review; batch 2 in progress (#354)

## Done

- `backend/data/fiu_named_exchanges.json`: 105 rows (81 addresses): BingX 62, LBank 20, XT.com 16, Phemex 5, Bitrue 2; Ethereum 79, Polygon 26. Each row: the explorer page it came from, the page's own "As at" time, the UTC day read (15 Nov 2026 UTC). `_meta.left_out` lists every candidate not taken and why.
- The same rows in `exchange_labels.json` and `exchange_labels_polygon.json` (`_meta.fiu_named_exchanges` in each).
- `backend/data/fiu_ind_status.json`: entries for the five (PIB release 2173758 for BingX, LBank, Bitrue, Phemex; 2308131 for XT.com); none is in USQ 5805 Annexure-I (re-read 15 Nov 2026 UTC, SHA-256 `cd2c2281…59c7`, same as the original read). `_meta.rule` now says 34 named exchanges are left out.
- Release gate 6 (`docs/label-releases.md`): the 79 new Ethereum labels' code read alone with `check_label_code.record` (keyless node, block 26422970) into `tests/fixtures/label_code/ethereum.json` (`_meta.read_since` says so), then `check_label_code` run without flags: 0 retyped, XT.com: Hot Wallet listed as EIP-7702 delegated.
- `backend/tests/test_fiu_named_exchanges.py`: shape and sources, tag reads as the exchange and is not infrastructure, label files carry each row exactly, no collision with any other list, the India set, a demo or a test, left-out addresses unlabelled, the drained XT.com wallet unlabelled, each exchange's FIU-IND entry, and a trace into one wallet of each exchange names it and carries its FIU-IND note.

## Decisions

- Source: the explorer's own public name tag on each address's page, read keylessly from the page title, as `data/india_exchanges.json` round 1 does; candidates came from dawsbot/eth-labels @ 14247ba8. No ownership is inferred. No first-party wallet list of the five could be read without a browser (see `_meta.first_party_sources`).
- A row needs transactions on that chain's explorer page. Each chain's own tag is the label (an address can read "XT.com 3" on Ethereum and "XT.com 2" on Polygon).
- An address tagged as a deposit funder on one chain is left out on every chain (`0x4fd7c9bd…`: "XT.com: Deposit Funder" on Etherscan, "XT.com 1" on PolygonScan).
- Left out: BingX 16 (a recorded demo names it as a statement counterparty), and XT.com 11 (`0xdb3ded77…`), which XT.com's 28 Nov 2024 statement names as the platform wallet assets were moved out of; who controls it since is not established.
- One XT.com wallet's code is an EIP-7702 delegation; it is an account, typed `exchange_wallet`.

## Next

1. Batch 2: other FIU-IND-named exchanges with explorer tags in dawsbot/eth-labels (LAToken, SimpleSwap, MoonPay, WOO X, ProBit, CEX.IO, YouHodler, Paxful, Changelly, LCX). Each needs a line in `app/tron_tags.py` CANONICAL first (none is there). Same method; then their `fiu_ind_status.json` entries.
2. BSC and Arbitrum rows for the five: BscScan and Arbiscan pages sit behind a bot check; a person in a browser, or a first-party list, is needed.
3. Replace or corroborate with a first-party list if any of the five publishes one readable without a browser (Phemex's proof-of-reserves page, which press coverage says shows part of its cold-wallet addresses, loads its data in the browser only).

## Open questions

- Should the BingX 16 wallet (`0x1651d700…`) be labelled and the recorded demo that names it re-recorded? It appears there only as a credit counterparty in a wallet statement. (Sidhyarth)

## Files mid-change (do not touch)

- none
