# Handoff: landing-flagged-figure

- **Feature**: the landing and citizen sign-in hero's flagged-address figure says what it counts and agrees with the chain rows under it
- **Issue**: #285
- **Branch**: `fix/landing-flagged-figure`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: PR ready; frontend only

## Done

- `frontend/src/components/ExchangeGlobe.jsx`: the hero reads "Flagged addresses screened, live, counted once per chain" and shows its figure to two decimals (69,452,797 -> "69.45M"), like the chain rows under it; one decimal rounded it up to "69.5M".
- `frontend/src/components/ExchangeGlobe.test.jsx`: renders the hero from a mocked GET /chains and checks the wording, the headline and the chain rows.
- README not changed here: #283 adds "counted once per chain" to its figures.

## Decisions

- Measured with the app's own matchers against release `labels-2026-11-15` (15 Nov): the store holds 69,410,610 rows, one per address and chain, so each category count is of different rows (no address is counted under two categories on one chain). The JSON lists in `backend/data` add 42,189 entries, of which 32 (8 Ethereum: 4 mixer, 4 frozen; 24 Tron) are also in the store. So the /chains sum (69.45M) is the store plus the repository's lists, per chain, and only those 32 are counted twice. A reviewer measured 68,527,888 distinct addresses across chains; the site counts per chain, and now says so.
- Not done: removing the 32. It needs one store lookup per list entry (~42,000), measured at 4 to 8 seconds here, on every start (main.py logs the counts) or on the first /chains request. `RiskMatcher.counts_by_category` already notes the overstatement.

## Next

1. If an exact count is wanted: have `scripts/build_label_store.py` or the release checks record the overlap with the repository's lists, rather than querying at start.

## Open questions

- README says 69.4M (the store alone); the site says 69.45M (the store and the lists). Both true; whether the README should say 69.45M is the owner's call.

## Files mid-change (do not touch)

- none
