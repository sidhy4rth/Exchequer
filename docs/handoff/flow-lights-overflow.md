# Handoff: flow-lights-overflow

- **Feature**: the Flow tab's moving lights no longer make the page scroll sideways on desktop
- **Issue**: #377
- **Branch**: `fix/vf-overflow`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: claimed; fix in progress

## Done

- Claimed (#377).

## Decisions

- Fix in `frontend/src/components/case/VictimFlow.css` only: the lights' layer clips what is inside it. The animation and how it looks inside the chart stay the same, and so does reduced motion.

## Next

1. Clip `.vf-lights` with a small margin for the dots' glow, add a stylesheet test, and check the live demos' layout in a local build at 1280 and 390 px.

## Open questions

- none

## Files mid-change (do not touch)

- `frontend/src/components/case/VictimFlow.css`: the lights' layer rules
