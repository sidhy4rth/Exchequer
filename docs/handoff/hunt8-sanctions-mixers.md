# Handoff: hunt8-sanctions-mixers

- **Feature**: screen traces against the government-listed addresses and mixer pools the 11 Nov hunt found, which the 14 Nov label release could not carry
- **Issue**: #148
- **Branch**: `feat/hunt8-sanctions-mixers` (PR 1, sanctions), `feat/hunt8-mixers` (PR 2, stacked)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: PR 1 (#149, sanctions) and PR 2 (mixers, stacked on it) ready for review

## Done

- PR #149 (sanctions): OFAC re-import from the SDN list published 11/13/2026 (+3 Ethereum, +18 Tron); 93 Israeli NBCTF
  Tron wallets in force added through `import_intl_sanctions --recheck il_mod_crypto --add` (each re-checked on the
  NBCTF site's own records); U.S. court forfeiture orders as a new importer source (`data/us_forfeiture_orders.json`,
  `--forfeiture`), 5 wallets whose notice was re-read on 14 Nov.
- PR 2 (mixers): 32 mixer pools and entry points into the threat files; Polygon and Arbitrum get a threat file.

## Decisions

- Sanctions go through the repo's own importers and data files (risk_labels*, intl_sanctions*), not the label store, which has no sanctioned category.

- U.S. forfeiture orders are filed `seized` (like Israel's orders), authority "United States", no end date.
- Privacy-protocol contracts (Railgun, Aztec, Hinkal; 25 rows) are not labelled: there is no non-crime category.

## Next

1. 17 U.S. forfeiture wallets from hunt 8 wait for their notice to be re-read: their only copy is on the Internet
   Archive, which answered HTTP 429 all of 14 Nov. List and URLs: PR #149 description. To add one, re-read its
   notice, add an entry to `backend/data/us_forfeiture_orders.json`, run
   `cd backend && .venv/bin/python -m scripts.import_intl_sanctions --forfeiture`.
2. Carry the 3 new Ethereum OFAC addresses to Polygon/Arbitrum: `scripts.port_evm_labels --sanctions-only` (needs
   the Etherscan key; not run here).

## Open questions

- Privacy Pools (2 Ethereum entries, already on main) is filed as a mixer although it screens deposits; keep it? (owner)
- Should privacy protocols get a category of their own (shown, never a stop)? (owner)

## Files mid-change (do not touch)

- none
