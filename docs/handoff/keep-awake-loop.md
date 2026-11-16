# Handoff: keep-awake loop

- **Feature**: the free Render instance stays awake because pings actually happen every 10 minutes, not only when GitHub delivers a schedule
- **Issue**: #379
- **Branch**: `fix/keep-awake-loop`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-16
- **Status**: PR open, awaiting review

## Done

- `.github/workflows/keep-awake.yml`: one run loops four legs of 340 minutes (ping every 10 minutes, 5 minutes rest at the end of a leg), hourly schedule, `concurrency` without cancel so only one loop runs; `KEEP_AWAKE=on` gate and `workflow_dispatch` kept, plus an "Ask once and stop" input. No secrets, `permissions: {}`, no actions used.
- `docs/operations.md` (Keeping the site awake) describes the loop.

## Decisions

- Measured before the change: two scheduled runs in ~15 hours after `KEEP_AWAKE=on` (23:30Z on 15 Nov, 03:05Z on 16 Nov); site-canary at 06:19Z on 16 Nov took 31 s to wake the site.
- Four sequential legs (`max-parallel: 1`) instead of one, because this repository's schedules arrive hours late (`watch-cron.yml` about every 4-7 hours, `demo-health.yml` about 6.5 hours late); one job may run at most 6 hours.
- No self-dispatch: it would need `actions: write`; the token stays without permissions.

## Next

1. After merge, check `gh run list --workflow keep-awake.yml`: one run in progress, legs green, pings every 10 minutes in the log.

## Open questions

- Owner: is exchequer.co.in the only free web service in the Render workspace? Awake all month uses about 720-744 of the 750 free instance hours; a second free service would share them.

## Files mid-change (do not touch)

- none
