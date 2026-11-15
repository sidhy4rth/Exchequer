# Handoff: sop-deadlines

- **Feature**: suite feature 8 (government platforms): time limits from the MHA SOP for NCRP-CFCFRMS, quoted word for word, shown as reminders on bank holds in the asset register
- **Issue**: #229
- **Branch**: `feat/sop-deadlines`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: open for review, behind `EXCHEQUER_SOP_DEADLINES` (off by default)

## Done

- `backend/app/sop_reminders.py`: five reminders for a bank row that is still held. Each one has the section, the PDF page, the quote, and the source URL and copy date. `for_asset()` returns none for exchange, issuer and custody rows, or once a hold has ended.
- `backend/app/assets.py`: when the flag is on, `summary()` adds `sop_reminders`. When it is off, the rows are unchanged. The 45-day logic (`DEADLINE_DAYS`, `deadline`, `days_left`, `due`, `due_for`, the home-page card) is untouched.
- `frontend/src/components/case/SopReminders.jsx` (+ `.css`, `.test.jsx`): a collapsed list under the row, mounted with one import and one line in `AssetsPanel.jsx`.
- Tests: `backend/tests/test_sop_reminders.py` (9) and `SopReminders.test.jsx` (2). `test_assets.py` and `AssetsPanel.test.jsx` are unchanged.

## The SOP copy

- MHA, "Standard Operating Procedure (SOP) for NCRP-CFCFRMS, Custody, Restoration of money and Grievance Redressal": https://www.zoroastrianbank.bank.in/download/SOP-NCRP.pdf
- PDF ModDate 11 Feb 2026, 52 pages, SHA-256 `65400b47a16ae9986e7bb9b339b26db920435a3ce6c128e804492b6e4be3bd42`, fetched 15 Nov 2026. This is the copy the feature 8 research and the freeze legal brief read.
- Each quote was checked against this copy's text, on the cited page.

## Decisions

- Reminders only. Nothing is refused, blocked or reordered, and the screen says "Not a deadline Exchequer enforces".
- Bank holds only. Annexure I (the hold notice under s.168 read with s.94 BNSS) is addressed to a bank, and §10.1 covers grievances about a hold at a bank or FI. The register does not record whether a hold went through CFCFRMS, so the list is headed "if this hold went through CFCFRMS". It adds no field and no migration.
- Only the Annexure I 90-day limit runs from a date the register holds (the date seized). The rest run from the complaint or a grievance, so they are shown without a date.
- No reminder for telling the Magistrate. This copy gives no number of hours or days: its steps say "forthwith" for the s.106(3) BNSS report. The 24-hour rule in the legal brief comes from a High Court judgment, not from the SOP.
- No reminder for exchange or issuer holds: §9.4 sets no time limit.

## Next

1. The owner decides whether to turn the flag on (Render env `EXCHEQUER_SOP_DEADLINES=1`) once the reviewer has checked the quotes against the PDF.
2. Courts cite other SOP versions (02.01.2026, 10.04.2026). If a newer official copy is found, re-check each quote and its section number in `sop_reminders.py`.

## Open questions

- Should a row record "hold placed through CFCFRMS", so that reminders show only then? That needs a migration. Owner to decide.

## Files mid-change (do not touch)

- none
