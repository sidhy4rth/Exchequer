# Handoff: exchange attribution from label-store rows (OKX proof of reserves)

- **Feature**: a trace that reaches a wallet an exchange publishes as its own, held in the label store (OKX's 474,530 Tron addresses), names that exchange
- **Issue**: #222
- **Branch**: `feat/store-exchange-rows-contract` (contract + ADR), `feat/store-exchange-rows` (code, stacked on it)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: contract + ADR PR and stacked code PR open for review; flag `EXCHEQUER_STORE_EXCHANGE_ROWS` off

## Done

- [ADR-0011](../adr/0011-exchange-rows-in-the-label-store.md): exchange rows live in their own optional store table,
  `exchange_rows`; `schema_version` stays 1 (old readers never open the table; a store without it reads as before).
- Contract: `matches[].attribution_basis` (`docs/contracts/case.md`), absent unless a match came from such a row.
- Code (stacked PR): `LabelStore.exchange_row` (never a system address, token, router or casino wallet),
  `ExchangeMatcher.lookup` reads it behind `EXCHEQUER_STORE_EXCHANGE_ROWS`, `ExchangeMatch.basis` ->
  `matches[].attribution_basis`; `backend/scripts/add_store_exchange_rows.py` adds the table to a built store from a
  CSV (gates, `<csv>.left_out.tsv`, re-run replaces a source's rows, meta `exchange_rows`). Tests:
  `backend/tests/test_store_exchange_rows.py`.
- OKX staged outside the repo: `~/exchequer-flagged/store/next-release/okx_por_tron.csv`, 474,529 rows from OKX's
  1 Nov 2026 file (SHA-256 93095583...367a6, 474,530 listed, all signed with a balance; 1 already in the label file
  as OKX). Trial ingest into an empty store: 3 s, +17.7 MB after VACUUM. Ingest steps in
  `~/exchequer-flagged/store/NEXT-RELEASE.md`.

## Decisions

- Order in the exchange matcher: JSON files (and the instant-exchanger seed), then a store exchange row (flag on),
  then a store instant-exchanger row. JSON always wins.
- An address a store row attributes is an exchange wallet to every precedence rule, as a JSON row is.

## Next

1. Next store release: run `add_store_exchange_rows.py` on the release copy (NEXT-RELEASE.md), once the code PR is merged.
2. After the next store release holds the table: re-record the demo whose trace passes 5 OKX addresses
   (`backend/data/recorded_demos.json`) in the same PR that turns the flag on.

## Open questions

- Owner: when to turn the flag on (needs the store release with the table, then the demo re-record).

## Files mid-change (do not touch)

- none
