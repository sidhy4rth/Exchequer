# Handoff: hunt8-sanctions-mixers

- **Feature**: screen traces against the government-listed addresses and mixer pools the 11 Nov hunt found, which the 14 Nov label release could not carry
- **Issue**: #148
- **Branch**: `feat/hunt8-sanctions-mixers` (PR 1, sanctions), `feat/hunt8-mixers` (PR 2, stacked)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: claimed; work starting

## Done

- nothing yet

## Decisions

- Sanctions go through the repo's own importers and data files (risk_labels*, intl_sanctions*), not the label store, which has no sanctioned category.

## Next

1. PR 1: OFAC re-import, Israel orders re-check with additions, U.S. forfeiture orders as an import_intl_sanctions source.
2. PR 2: mixer rows into the threat label files.

## Open questions

- none yet

## Files mid-change (do not touch)

- backend/scripts/import_intl_sanctions.py, backend/data/risk_labels*.json, backend/data/intl_sanctions*.json
