# Handoff: landing-flagged-figure

- **Feature**: the landing and citizen sign-in hero's flagged-address figure says what it counts and agrees with the chain rows under it
- **Issue**: #285 (merged in #292); now #346
- **Branch**: `feat/landing-overlap-metadata` (was `fix/landing-flagged-figure`)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: #292 merged (`b287826b`); #346 in progress: the store records its overlap with the lists

## Done

- `frontend/src/components/ExchangeGlobe.jsx`: the hero reads "Flagged addresses screened, live, counted once per chain" and shows its figure to two decimals (69,452,797 -> "69.45M"), like the chain rows under it; one decimal rounded it up to "69.5M".
- `frontend/src/components/ExchangeGlobe.test.jsx`: renders the hero from a mocked GET /chains and checks the wording, the headline and the chain rows.
- `README.md` (after #283, which added "counted once per chain"): the badge and the flagged figure say 69.45M, what GET /chains sums (the 69.4M store and the repository's lists); exchange addresses 26,157 -> 26,204 and the feature table's 26,136 -> 26,204, the live /chains sum after #277; the label-file table's Ethereum (25,332; 1,314 exchange wallets), BSC (227) and Tron (144) counts, from the files.

## Decisions

- Measured with the app's own matchers against release `labels-2026-11-15` (15 Nov): the store holds 69,410,610 rows, one per address and chain, so each category count is of different rows (no address is counted under two categories on one chain). The JSON lists in `backend/data` add 42,189 entries, of which 32 (8 Ethereum: 4 mixer, 4 frozen; 24 Tron) are also in the store. So the /chains sum (69.45M) is the store plus the repository's lists, per chain, and only those 32 are counted twice. A reviewer measured 68,527,888 distinct addresses across chains; the site counts per chain, and now says so.
- Not done: removing the 32. It needs one store lookup per list entry (~42,000), measured at 4 to 8 seconds here, on every start (main.py logs the counts) or on the first /chains request. `RiskMatcher.counts_by_category` already notes the overstatement.

## Next

1. If an exact count is wanted: have `scripts/build_label_store.py` or the release checks record the overlap with the repository's lists, rather than querying at start.

## Open questions

- None. `docs/officer-guide.md` and `docs/suite-features.md` keep 69.4 million: they speak of the store alone.

## Files mid-change (do not touch)

- none
