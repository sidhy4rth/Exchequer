# Label releases

The label store (`backend/app/label_store.py`) ships as a pinned release built
by `backend/scripts/build_label_store.py`. Releasing one is the owner's call,
and every release goes through the same gates first.

## The gates, before every release

1. **Tokens:** no row may name a token contract (the token-list exclusion check;
   collisions must be 0).
2. **Exchanges and services:** no risk row may name an exchange, router or
   casino wallet the repository already labels (`never_flag`); the gambling
   rows get their DEX-contract scan.
3. **Demos:** look up every address in `recorded_demos.json`,
   `demo_traces.json`, `demo_expectations.json` and `DEMO.md`. Only demo 1's
   intended poisoner may hit.
4. **Tiers:** each row's tier comes from who published it
   (`app/label_rules.SOURCE_TIERS`); a source the rules do not place stops the
   build until a line there says what it is.
5. **`check_data.py`** on the candidate files: counts, validity, cross-list
   conflicts, demo impact and the merge plan.

## Instant exchangers (category `instant_exchanger`, added 10 Nov 2026)

No-KYC swap services (FixedFloat, ChangeNOW, SideShift, SimpleSwap, Exolix,
StealthEX, LetsExchange...). An order pays one asset in and another out, to an
address the customer gives, so a payment into one is a cash-out point a
request can be sent to: it is matched as an exchange, never screened as risk.

- **Today:** the code reads them from `backend/data/instant_exchangers.json`,
  a seed of `{address, chain, service, source, checked_on}`. It holds only
  addresses the repository's own exchange label files already name under a
  swap service (ChangeNOW and FixedFloat, 15 rows on 4 chains), each citing
  that file. The live store has no rows of this category yet.
- **Next store release:** give each row the hunt category `instant exchanger`
  (`CATEGORY_MAP` maps it to `instant_exchanger`, at most tier 3) with the
  service as its entity. The store reads such a row only through
  `LabelStore.instant_exchanger()`; `LabelStore.lookup()`, the risk
  screening's read, leaves it out. Then:
  - run every gate above. A row on an address the exchange files already label
    is refused by `never_flag` at build time, which is fine: that file's record
    already matches it, and the seed says what kind of service it is;
  - add a line to `SOURCE_TIERS` for each new source before building;
  - for every new demo hit, check whether a recorded demo's Flow changes
    (`scripts/check_demos.py`), and say so in `DEMO.md`.
- **Adding to the seed instead:** only an address an in-repository file
  already names, citing that file. Never one from memory or from the network
  without the release gates.
