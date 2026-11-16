# Handoff: flow-lights-overflow

- **Feature**: the Flow tab's moving lights no longer make the page scroll sideways on desktop
- **Issue**: #377
- **Branch**: `fix/vf-overflow`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: fix done, PR #378 ready for review

## Done

- Claimed (#377); fix and stylesheet test in PR #378.

## Decisions

- The layer reaches 16px past the stage (inside the chart card's 22px padding) so a dot's glow at the chart's edges is not cut, and each light starts 16px in, so the dots sit exactly where they did.
- Fix in `frontend/src/components/case/VictimFlow.css` only: the lights' layer clips what is inside it. The animation and how it looks inside the chart stay the same, and so does reduced motion.

## Next

1. Review and merge #378. After the deploy, open `/demo/11` at 1280 px and check the page does not scroll sideways.

## Open questions

- none

## Files mid-change (do not touch)

- none
