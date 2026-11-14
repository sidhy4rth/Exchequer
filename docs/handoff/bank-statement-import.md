# Handoff: bank and exchange statement import (suite feature 5)

- **Feature**: suite feature 5, first and second slices. An officer reads a bank statement CSV, or a transaction CSV an exchange provided, against a case: the rows that match the victim's payments, the UPI/IMPS/NEFT/RTGS references in narrations, the narrations that name a known exchange, on a timeline beside the trace's own on-chain times. The officer may save the rows they confirm (never the whole statement) to the case. Second slice: a call detail record (CDR) read the same way, its top contacts, handsets and the numbers on this or the officer's other cases; a summary saved, never the CDR.
- **Issue**: #144 (statements); #167 (call detail records, the second slice)
- **Branch**: four stacked PRs: `feat/bank-statement-import` (#146, the record), `feat/bank-statement-import-routes` (#151, the routes), `feat/bank-statement-import-parse` (#152, reading and matching in the browser), `feat/bank-statement-import-panel` (#153, the panel on the Evidence tab). CDR, stacked on #153: `feat/cdr-import` (#168, the record and routes), `feat/cdr-import-parse` (#172, reading in the browser), `feat/cdr-import-panel` (#173, the panel). Withdrawing a saved import, stacked on #173: `feat/statement-import-withdraw`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: first slice built in four stacked PRs, behind the flag `EXCHEQUER_STATEMENT_IMPORT` (off by default); awaiting review. Second slice (call detail records, #167) built in three stacked PRs behind its own flag `EXCHEQUER_CDR_IMPORT` (off); awaiting review

## Done

- Claimed: issue #144, this file, draft PR #146.
- The record (#146): table `statement_imports` (migration `g7_statements_1`, after `g7_domain_lookups_1`), `backend/app/statement_imports.py` (checks each saved row: date, debit or credit, amount, reference shape, an exchange name only when canonical and in the row's own text, free text refused when it looks like a key), flag `EXCHEQUER_STATEMENT_IMPORT`.
- The routes: `GET /trace/{case_id}/statements` (the saved rows this browser or unit may read, and the canonical exchange names; `enabled: false` with the flag off) and `POST /trace/{case_id}/statements` (403 with the flag off, and 403 for a caller who has not signed in as an officer: security review, 14 Nov). Audited as `statement.list` and `statement.save` with counts only.
- Reading and matching in the browser: `frontend/src/components/case/statement.js`. Header names (`HEADERS`), the account lines above the header skipped, day-first dates (dd/mm/yyyy, dd-MMM-yyyy, ISO for exchanges), amounts with lakh grouping, Dr/Cr suffixes, brackets and signs; NEFT (16), RTGS (22) and UPI/IMPS (12-digit RRN, only in a UPI or IMPS narration) references; canonical exchange names; hashes of the trace; a timeline beside the payments and the arrivals at the attributed exchange address, in India's time.
- The panel: `frontend/src/components/case/StatementPanel.jsx` on the Evidence tab, shown only when the server says the flag is on. Pick bank or exchange and the currency, choose a CSV, check the columns, add the rupee amounts the complaint reports, tick the rows to keep, save. Saved rows are listed with the case.

- CDR (#167): `backend/app/cdr_imports.py` and `routes/cdr.py`: `GET`/`POST /trace/{case_id}/cdr` (the saved summaries; save one) and `POST /trace/{case_id}/cdr/check` (the numbers the officer ticks, in the body: on this case's phone identifiers, and on the other cases they may read, via `identifiers.also_in`). Audited as `cdr.list`, `cdr.save`, `cdr.check` with counts only. `frontend/src/components/case/cdr.js` reads the CDR (header names in `CDR_HEADERS`, Indian numbers in the register's `+91` form, call types MO/MT/SMS-MO/SMS-MT, durations as seconds or h:mm:ss) and analyses it: the CDR's own number, top contacts by count and by call time with first and last contact, IMEIs and IMSIs with how often they changed, the most used first cells. `CdrPanel.jsx` on the Evidence tab.

- Withdrawal (`feat/statement-import-withdraw`): a signed-in officer withdraws a saved statement or CDR import entered by mistake. Migration `g7_statements_2` (after `g7_statements_1`) adds `withdrawn_at`, `withdrawn_by`, `withdrawn_reason` and `row_version` to `statement_imports`. `statement_imports.withdraw` (shared by both); routes `POST /trace/{case_id}/statements/{import_id}/withdraw` and `POST /trace/{case_id}/cdr/{import_id}/withdraw` with `{"reason": ...}`; `GET ...?withdrawn=1` lists withdrawn imports too, and every listing carries `withdrawn_count` and `can_withdraw`. Audited as `statement.withdraw` / `cdr.withdraw` with the import id only; a listing with withdrawn imports shown is audited with `{"withdrawn": true}`. Panels: `WithdrawImport.jsx` (the button, the reason, the "Show withdrawn (n)" toggle, the struck-through entry with who, when and why).

## Decisions

- The statement is read in the browser. Nothing leaves it until the officer saves the rows they confirmed; the server never sees the rest of the statement.
- Amounts are matched only within one currency: a rupee statement against rupee amounts the officer types from the complaint, an exchange's statement in the traced asset against the case's own payments (`intake.payments`). No exchange rates are used or guessed.
- An exchange is named only when a narration contains one of the repository's own canonical exchange names (the `exchange` field of the label files, as `ExchangeMatcher.exchanges` lists them), as a whole word. A few canonical names that are also ordinary words in Indian statements ("Liquid" as in a liquid fund) are not matched from narrations.
- The audit log records counts only (rows saved, by reason), never an account number, a reference or a narration.
- No real sample statements exist yet; every test row is synthetic and says so.
- An amount matches when it agrees to the places the statement prints (at least two) and its date is within 2 days (`WINDOW_DAYS`) of the payment's date in India. Direction is not required: a refund of the same amount is also worth a look.
- Caps (security review, 14 Nov): at most 50 imports per case, 1,000 per unit, 200 per browser and 10,000 in all (statements and CDRs share the table). An import can be about 150 KB, so the old 100,000 total let one caller grow the table to about 15 GB. A withdrawn import still counts: it is never deleted.

- Withdrawal never deletes: the rows stay in the case record with who withdrew them (the officer's id), when and the reason (one line, up to 300 characters, refused when it looks like a key). Withdrawn imports are left out of listings unless `?withdrawn=1`. Only a signed-in officer may withdraw (the demo caller gets 403), and only an import they may read (their browser's or their unit's, as for viewing; anything else is 404). A second withdrawal is 409 and keeps the first reason; a write that keeps meeting another (row version) is 409 after 3 tries. The statements route withdraws only bank and exchange imports, the CDR route only CDR summaries. Nothing reads saved imports for matching today (the browser matches the file it reads; CDR checks read the identifier register), so a withdrawn import cannot feed a match.
- The reason is not in the audit log (it is free text); the import's id is.
- CDR summaries share the `statement_imports` table (source `cdr`, currency empty): the same kind of record, what the officer confirmed from a file read in the browser, so no migration. Statement listings filter to bank and exchange.
- CDR has its own flag, `EXCHEQUER_CDR_IMPORT`, so statements can go live before CDR is tried on a real one.
- Saving a CDR summary (`POST /trace/{case_id}/cdr`) needs a signed-in officer, like saving statement rows; listing and the number check do not. Summaries share the statement imports' caps (security review, 14 Nov).
- What is saved: the CDR's own number, the contacts the officer ticks and the handsets they tick, with counts and first/last day; never a row of the CDR, a time, a cell or a duration per call. A `case_identifier` or `other_case` reason is checked by the server against the identifier register, never taken on trust.
- Numbers are normalised as `identifiers.phone` does (an Indian mobile however printed is `+91` and 10 digits), so a CDR's number and a recorded identifier compare as the same string. Short codes, landlines and SMS senders are kept as printed and cannot be checked.
- Pre-review (14 Nov): the browser now drops a trunk 0 after a country code as `identifiers.phone` does; a handset is its IMEI's first 14 digits (check digit and IMEISV software version ignored); a field no header names exactly takes a column whose header contains its word, never a circle, operator or address column; the contacts table scrolls in a focusable region and checks and saves are announced. Test numbers: no 6-9 Indian mobile (any could be a subscriber's); 10-digit numbers start with 5 (no mobile series, kept as printed) and a number the register must hold is in Ofcom's drama range +44 7700 900xxx, since the register takes a 10-digit number as Indian only when it starts 6 to 9.
- The CDR's own number is the one on the most rows (A or B party); the other party of a row is whichever is not it. A call type's MO/MT gives the direction; without one, A party = the subject means outgoing.
- A number is a lead, never a person: the panel says subscriber details come from the operator under a lawful request.
- Test numbers: India sets aside no mobile range for fiction, so the tests use a visibly patterned run (+91 90000 0000x); the foreign one is in Ofcom's drama range (+44 7700 900xxx); IMEIs start with zeros; IMSIs use the test network code 001 01.

## Next

1. Try the panel with real (redacted) statements, then turn the flag on in production (render.yaml and Render's environment), and remove the flag once it has shipped.
2. Migration heads: `g7_statements_2` revises `g7_statements_1`. If another migration (for example #122 `g7_tasks_1`, #124 `g7_tasks_2`) merges to main first, re-point `g7_statements_1`'s or this one's `down_revision` so there is one head.
3. CDR: try it on real (redacted) CDRs from Airtel, Jio, Vi and BSNL to add their header names and call-type spellings to `CDR_HEADERS` and `eventType`, then turn `EXCHEQUER_CDR_IMPORT` on. Reading an XLSX directly (today: save as CSV) would need a dependency, in its own PR.
4. IPDR is not started.

## Open questions

- Real CDR samples (redacted) from the operators officers see most. Owner to obtain.

- Real statements from the banks officers see most (SBI, HDFC, ICICI, Axis) and from WazirX/CoinDCX would show which header names and narration shapes to add. Owner to obtain redacted samples.

## Files mid-change (do not touch)

- none
