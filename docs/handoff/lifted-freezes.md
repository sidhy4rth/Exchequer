# Handoff: lifted freezes

- **Feature**: a Tether freeze that has been lifted stops reading "Frozen by Tether"
- **Issue**: #202
- **Branch**: `fix/lifted-freezes`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: merged in #206 on 2026-11-15

## Done

- `scripts/import_tether_freezes.py --recheck-lifts`: asks the USDT contract's
  `isBlackListed(address)` for every held freeze on keyless public endpoints
  (publicnode; Tenderly / TronGrid confirm any "not frozen"), and moves lifted
  addresses to `_meta.excluded` with the RemovedBlackList tx. Leaves
  `last_reviewed` alone and does not rewrite a file when nothing was lifted.
- Run by hand on 2026-11-15: Ethereum 2,630 checked, 0 lifted; Tron 7,562
  checked, 28 lifted (all 28 with their release tx). The Tron file in this PR is
  that run's output.
- `scripts/import_all_lists.py`: a family can name `keyless_args`, run instead
  of being skipped when its key is missing. The Tether family uses
  `--recheck-lifts`. Such a run still counts as a skip for `has_problem`
  (strict nightly stays red) and never opens a date-only PR.

## Decisions

- A lift is acted on only when two endpoints both answer "not frozen"; one
  endpoint's word, an error or a rate limit keeps the freeze. More than 1% (at
  least 5) unreadable answers and nothing is written.

## Next

1. Owner: switch on the nightly refresh (`REFRESH_LISTS=on`) when ready; not
   done here.

## Open questions

- none

## Files mid-change (do not touch)

- none
