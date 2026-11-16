# Handoff: handoff-status-sweep-8

- **Feature**: after the 16 Nov merges, the handoffs say what is merged (PR and commit), name nobody as Current and list only what is left; `docs/suite-features.md` and the flag table say what is on `main`; the officer guide describes what officers see now or once a switch is on (docs only)
- **Issue**: #365
- **Branch**: `docs/handoff-status-sweep-8`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: done; the pull request for #365 is ready for review

## Done

- Handoffs moved to merged (PR, short commit), Current = nobody, done Next items struck: `ci-skip-docs-only.md` (#319), `prorata-read-failure.md` (#321), `prorata-read-failure-ui.md` (#323), `prorata-read-failure-nits.md` (#331), `sop-steps.md` (#327), `okx-sweep-basis-internal-rows.md` (#329), `custody-balance-check.md` and `asset-register.md` (#333, #344, #345), `case-tasks.md` (#335), `store-deposit-rows.md` (#267, #337, #349), `trace-screen-store-basis.md` (#337), `describe-double-stop.md` and `privacy-protocol-category.md` (#339; its Next 1 was done in #232), `government-platforms.md` and `ncrp-portal-links.md` (#327, #341), `landing-flagged-figure.md` (#347), `letter-of-request-store-basis.md` (#349), `review-nits-15nov.md` (#357), `handoff-status-sweep-7.md` (#351).
- `docs/suite-features.md`: date line; rows 6, 8 and 9 say "on `main`" for #335, #327, #341 and the custody balance check (#333, #344, #345).
- `docs/flag-rollout.md`: the `EXCHEQUER_SOP_STEPS` row (#327 added the flag but no row), the custody balance row's PRs, and the count, twenty-one, as `config.FLAGS` has on `main` (part 7's "Small things" 1).
- `docs/officer-guide.md`: the FIU-IND-named exchanges' wallets (live, #343, #355, #359), "When the amount could not be checked" (live), the store basis on the trace screen and in a letter of request, two more task suggestions, "Checking custody balances on chain", "Links to cybercrime.gov.in and 1930" and "The SOP's steps beside the case", each with its switch and that it is off until switched on.

## Decisions

- #325 merged while this was open (10:29 UTC, `6d74f649`): its three handoffs were already right, so only the officer guide's build line (now #325, build 6d74f64, as live `/health` reported at 10:40 UTC) and `postmerge-6-small-things.md` were changed after it. Left alone because an open PR edits them: `letters-of-request.md` (#353), `fiu-named-exchange-wallets.md` and row 1 of `docs/suite-features.md` (#359 wrote them; #362 and #363 edit them).

## Next

1. After #362 merges: `fiu-named-exchange-wallets.md` still says batches 1 to 3 are in review; they merged in #343 (`a0f60d49`), #355 (`66f88d59`) and #359 (`a26dc77b`).
2. After #353 merges: `letters-of-request.md`'s status.
3. Still for Barenyam or the owner: `dependency-bumps.md`, `exhibit-register.md` and `report-certificate.md` name Barenyam as Current although their work is merged (`handoff-status-sweep-7.md` Next 1).

## Open questions

- none

## Files mid-change (do not touch)

- none
