# Handoff: exchange attribution from label-store rows (OKX proof of reserves)

- **Feature**: a trace that reaches a wallet an exchange publishes as its own, held in the label store (OKX's 474,530 Tron addresses), names that exchange
- **Issue**: #222
- **Branch**: `feat/store-exchange-rows-contract` (contract + ADR), `feat/store-exchange-rows` (code, stacked on it)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: contract and ADR first; code in the stacked PR, behind `EXCHEQUER_STORE_EXCHANGE_ROWS` (off)

## Done

- [ADR-0011](../adr/0011-exchange-rows-in-the-label-store.md): exchange rows live in their own optional store table,
  `exchange_rows`; `schema_version` stays 1 (old readers never open the table; a store without it reads as before).
- Contract: `matches[].attribution_basis` (`docs/contracts/case.md`), absent unless a match came from such a row.

## Decisions

- Order in the exchange matcher: JSON files (and the instant-exchanger seed), then a store exchange row (flag on),
  then a store instant-exchanger row. JSON always wins.
- An address a store row attributes is an exchange wallet to every precedence rule, as a JSON row is.

## Next

1. Stacked PR: `label_store.LabelStore.exchange_row`, the matcher reading it, the flag, `scripts/add_store_exchange_rows.py`.
2. After the next store release holds the table: re-record the demo whose trace passes 5 OKX addresses
   (`backend/data/recorded_demos.json`) in the same PR that turns the flag on.

## Open questions

- Owner: when to turn the flag on (needs the store release with the table, then the demo re-record).

## Files mid-change (do not touch)

- none
