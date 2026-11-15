# Handoff: fiu-ind-status-note

- **Feature**: Feature 7 / feature 1 data: a dated, sourced FIU-IND note (registration as of 9 Mar 2026, enforcement actions, penalties) about the exchange a trace reached, on the report's FINDING and the exchange letters, behind `EXCHEQUER_FIU_IND_NOTE`
- **Issue**: #290
- **Branch**: `feat/fiu-ind-status-note`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: slice 1 (#291): the data file, the lookup and the flag; slice 2 (stacked) prints the note

## Done

- Claimed (issue #290, draft PR #291).
- `backend/data/fiu_ind_status.json`: 33 exchanges the label files name. 29 FIU-IND acted against (PIB releases 1991372, 2098153, 2173758, 2308131; Lok Sabha USQ 5805 Annexure-II; FIU-IND Orders 08, 10, 15, 16/DIR/FIU-IND/2024), and 4 registered Indian exchanges (WazirX, CoinDCX, CoinSwitch, Unocoin) from Annexure-I. 8 are registered as of 9 Mar 2026 (Binance, KuCoin, Bybit, Coinbase and the 4 Indian ones). Penalties: Binance, KuCoin, Bybit; Coinbase a warning.
- `backend/app/fiu_ind_status.py`: lookup by name (closure suffix stripped), and the note text with its sources; nothing with the flag off.
- `tests/test_fiu_ind_status.py`: every fact dated and sourced, names are label-file exchange names, the note's text, flag off no note, unlisted exchange and bad file silent.

## Decisions

- Wording: facts and dates only, each with its source; never "illegal" or advice. "Not on the 9 Mar 2026 list", never "not registered" without a date.
- An Annexure-II row is cited only where no PIB release records that action (OKX, Bitget, BitMart, Gemini, Crypto.com, Coinbase).
- Left out: Delta Exchange (Annexure-I's is the Indian entity; the label files do not say which Delta Exchange their wallet is), the ambiguous Annexure-II names, and the 39 named exchanges with no wallet in the label files.
- No test fails on the file's age (a date-based failure would break CI on a day, not on a change); the note prints the as-of date instead.
- Separate data file, `backend/data/fiu_ind_status.json`, not a third status in `exchange_status.json`: closure and FIU-IND standing are independent (BitMEX is closed and was noticed; Coinbase was listed for takedown and is registered).

## Next

1. Slice 2: print the note on the report's FINDING and the exchange letters, with the flag-off byte-identical test and the docs.
2. Owner: decide whether to switch `EXCHEQUER_FIU_IND_NOTE` on (checks in `docs/flag-rollout.md`).
3. Re-check the file against any newer Parliament answer or PIB release; update `_meta.checked_on`.
4. Optional: wallets for the 39 FIU-IND-named exchanges with none in the label files (Huione, BC.Game, Paxful, Changelly, LBank, Phemex, ...), sourced as usual; then add their entries.

## Open questions

- Whether the PDF page 1 summary should show the note too (it is in the signed text, Part 2, already).

## Files mid-change (do not touch)

- none
