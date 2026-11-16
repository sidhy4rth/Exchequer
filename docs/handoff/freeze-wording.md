# Handoff: freeze-wording

- **Feature**: suite feature 7: alternative wording for the bank-hold notice that rests only on the Magistrate's order, behind `EXCHEQUER_FREEZE_WORDING_V2` (off)
- **Issue**: #251
- **Branch**: `notices/freeze-wording-option`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: merged in #252 (`9ce0aee5`); flag off; waits for a lawyer before it is switched on

## Done

- `backend/app/config.py`: flag `EXCHEQUER_FREEZE_WORDING_V2`.
- `backend/app/notice_letters.py`: with the flag on, the bank hold asks the bank to give effect to the attached Magistrate's order as it directs, for no more than the amount stated; title, subject, a bracketed s.107 BNSS suggestion (officer to confirm) and the closing line change; the refusal without an order no longer says "a bank hold attaches money". Off, nothing changes.
- `backend/tests/test_freeze_wording.py`: the flag-off letter pinned in full (and by SHA-256 for the signed-off and blank-amount letters, and the refusal text), the flag-on wording, the safeguards kept, the information notices untouched, the route.
- `docs/legal/freeze-wording-review.md`: one page for counsel: both wordings, the questions, the sources.
- `docs/flag-rollout.md` row and section; `docs/suite-features.md` row 7.

## Decisions

- Of the three options in the owner's legal research note (15 Nov 2026), this builds the one that does not depend on the contested reading: keep the Magistrate's-order requirement (option A) and let the order, not the letter, say what the bank must do. No police-only "SOP hold" (options B/C) is offered.
- Only provisions and cases the research note cites with a source are used.
- The shared freeze header in `request_letters.py` is not changed; the bank hold replaces its first line only when the flag is on.

## Next

1. The owner hands `docs/legal/freeze-wording-review.md` to a lawyer.
2. On their answer: adjust the wording in `_bank_freeze`, then switch the flag on (`docs/flag-rollout.md`), or remove it and the old wording once the new one ships.

## Open questions

- The questions in `docs/legal/freeze-wording-review.md` (counsel).
- The module and test docstrings, and the old refusal text, still say a bank hold "attaches money"; change them when the flag is retired.
- The form's button still reads "Urgent hold" and the kind is `bank-freeze`; whether either should change is for after counsel answers.

## Files mid-change (do not touch)

- none
