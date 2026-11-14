# Handoff: officer-guide

- **Feature**: a plain-English guide for investigating officers to the suite's features, by task (docs only; touches features 2 to 9)
- **Issue**: #191
- **Branch**: `docs/officer-guide`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: written; in review

## Done

- `docs/officer-guide.md`: nine task sections (trace; evidence and custody; notices and letters, incl. a letter of request abroad; tasks and deadlines; export scan; statements and CDRs; domain and Telegram lookups; multisig custody; case bundle). Each says where it is, the steps, what is recorded and never recorded, and the limits.
- One line each in `README.md` ("Why it is built this way") and `docs/suite-features.md` linking it.

## Decisions

- Live = its code is on `main` (`git cat-file -e origin/main:<path>`). Coming features are split into "behind a switch until reviewed" (custody, statements, CDR, export scan, Telegram, case bundle: each adds a FLAGS entry) and "in review" (tasks, letters of request: no flag, so they appear on merge).
- Every behaviour described was checked in the code on `main`, or in the PR body and branch handoff of the open PR. Legal references are only those the code already cites (s.63(4) certificate in the BSA Schedule, BNSS s.112 / CrPC s.166A, BNSS s.497 as the Karnataka High Court read it, the MHA's 2019 guidelines).
- The bank-hold sign-off limit on `main` (tied to case and kind, not the details) is stated, with the workaround (close the request, ask again) and the fix in review (#133).

## Next

1. When a Coming PR merges or a flag is switched on, change that section's status line.
2. When #133 merges, delete the sign-off limit paragraph in section 3.
3. The brief mentioned a "privacy category"; no branch or PR for it existed on 14 Nov, so the guide does not describe it. Add it once it exists.

## Open questions

- none

## Files mid-change (do not touch)

- none
