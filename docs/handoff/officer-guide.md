# Handoff: officer-guide

- **Feature**: a plain-English guide for investigating officers to the suite's features, by task (docs only; touches features 2 to 9)
- **Issue**: #191
- **Branch**: `docs/officer-guide`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: merged in #192 (`fc38891e`) on 2026-11-15; evening update in #283 (`946615a3`); #279 wording merged in #289 (`a2985838`)

## Done

- `docs/officer-guide.md`: nine task sections (trace; evidence and custody; notices and letters, incl. a letter of request abroad; tasks and deadlines; export scan; statements and CDRs; domain and Telegram lookups; multisig custody; case bundle). Each says where it is, the steps, what is recorded and never recorded, and the limits.
- 15 Nov update: tasks (#122 stack) now Live; case bundle (#187) and the privacy-protocol category (#149 stack) "Merged, switched off"; new subsections for the label changes on main (India round 2 #135, clean-up and closed exchanges #212/#213, lifted freezes #206, sanctions/mixers/forfeitures #149, Tron proof of reserves #221), sign-off binding (#133, old limit paragraph removed), stopping a trace (#227/#228); a section 10 for NCRP and CFCFRMS (#218 stack, #230); Bybit/OKX labels (#226) and store exchange rows (#223/#224) as Coming.
- 15 Nov evening update (live build 97f1bae): privacy-protocol category now Live (#232; Privacy Pools no longer a mixer stop; payouts of a many-payout pool still not followed); report issuer https://exchequer.co.in (#240, older reports verify, #239); label store labels-2026-11-15, 69,410,610 (#261); Bitget reserve wallets (#258); hot-wallet roles on Kraken 5, Coinbase 10, Gemini 2 (#268, #270); verified example 3 reaches no exchange (#260); bundle now holds tasks (#244). README figures matched to live `/chains` (69.3M poisoning, 26,157 exchange addresses) and the Privacy Pools mixer wording.
- After #279 merged (live in build 470541e3): the privacy limits now quote the note's new wording for a pool whose payouts were not followed, #288's neutral section lede and reverse-trace wording, and that cases traced before #279 keep the old note.
- One line each in `README.md` ("Why it is built this way") and `docs/suite-features.md` linking it.

## Decisions

- Live = its code is on `main` (`git cat-file -e origin/main:<path>`). Coming features are split into "behind a switch until reviewed" (custody, statements, CDR, export scan, Telegram, case bundle: each adds a FLAGS entry) and "in review" (tasks, letters of request: no flag, so they appear on merge).
- Every behaviour described was checked in the code on `main`, or in the PR body and branch handoff of the open PR. Legal references are only those the code already cites (s.63(4) certificate in the BSA Schedule, BNSS s.112 / CrPC s.166A, BNSS s.497 as the Karnataka High Court read it, the MHA's 2019 guidelines).
- A fourth status, "Merged, switched off": merged code whose FLAGS entry is not on in `render.yaml`. The live switch state is not visible without `/health/detail`, so the guide does not claim one is on.
- Bank holds: one neutral line that courts differ on police-directed holds without a Magistrate's order and the officer should follow their unit's legal advice. No recommendation, no new citation.

## Next

1. When a Coming PR merges or a flag is switched on, change that section's status line.
2. When a "Merged, switched off" switch goes on, change it to Live.
3. ~~After the next deploy, drop the status note that #221 is not yet on the site.~~ Nothing to drop: on `main` the #221 entry (`docs/officer-guide.md:146`) sits under **Live** and no note says it is not on the site.

## Open questions

- none

## Files mid-change (do not touch)

- none
