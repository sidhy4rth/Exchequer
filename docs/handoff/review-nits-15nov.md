# Handoff: review nits on 15 Nov merges

- **Feature**: four small fixes from an independent review of main 76101ce0 (FIU-IND entry shapes, Tron re-seed drops, OKX self-transfers, runner pin)
- **Issue**: #356
- **Branch**: `feat/review-nits-15nov`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: done in PR #357, awaiting review

## Done

- `backend/app/fiu_ind_status.py`: an entry whose `actions` or `penalties` is not a list is skipped when the file is read, with an error logged; the other entries still give notes (#357).
- `backend/scripts/seed_tron_labels.py` `keep_previous`: a `sweep_basis` row is still never replaced by a TronScan tag, but is dropped when its address is in this run's not-an-exchange list; docstring now says Exchequer classed these rows (only the PoR listing is OKX's) (#357).
- `backend/scripts/classify_okx_tron_wallets.py`: transfers from an address to itself are not read, so self-sends cannot meet the "both ways" rule (#357).
- `.github/workflows/fiu-staleness.yml`: runner pinned to `ubuntu-24.04` (#357).

## Decisions

- Item 1 follows the module's existing per-entry pattern (skip that entry, keep the file); the skip is now logged at error level, since a skipped entry means a missing note.
- No class or label changes on main's data: the recorded OKX reads have no self-transfers, and the recorded not-an-exchange list drops no shipped Tron row (tests say so).

## Next

1. Review and merge #357.

## Open questions

- none

## Files mid-change (do not touch)

- none
