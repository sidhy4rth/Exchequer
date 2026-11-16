# Handoff: test-fake-store-exchange-row

- **Feature**: the fake label store in `backend/tests/test_tron_tags.py` has the real store's `exchange_row`, so the test passes with `EXCHEQUER_STORE_EXCHANGE_ROWS` on as well as off
- **Issue**: #384
- **Branch**: `fix/test-fake-store-exchange-row`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: in review

## Done

- `test_a_store_instant_exchanger_is_still_named_once_tronscan_names_another_wallet`: its fake `Store` gains `exchange_row(chain, address)` returning `None`, the real `LabelStore.exchange_row`'s answer for an address with no exchange row (`backend/app/label_store.py`). No assertion changed.
- Searched every other test for a hand-written label store fake: none. The rest use a real `LabelStore`.

## Decisions

- Test-only fix; no product code changes.

## Next

1. none

## Open questions

- none

## Files mid-change (do not touch)

- none
