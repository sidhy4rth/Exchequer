# Handoff: fiu-named-exchange-wallets

- **Feature**: a trace that ends in a wallet of an exchange FIU-IND acted against, but that had no wallet in the label files, now names that exchange, so the FIU-IND note (`EXCHEQUER_FIU_IND_NOTE`) can appear
- **Issue**: #342
- **Branch**: `data/fiu-exchange-wallets`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: in progress (batch 1: BingX, LBank, XT.com, Phemex, Bitrue)

## Done

- Claimed (issue #342, draft PR).

## Decisions

- Source: the explorer's own public name tag on each address's Etherscan page, read keylessly from the page title, as `data/india_exchanges.json` round 1 does; candidates came from dawsbot/eth-labels @ 14247ba8. No ownership is inferred.

## Next

1. Read the candidates' Etherscan pages, check each on chain keylessly, add the rows and the FIU-IND entries.

## Open questions

- none yet

## Files mid-change (do not touch)

- `backend/data/exchange_labels.json`, `backend/data/fiu_ind_status.json`: rows being added
