# Handoff: bank and exchange statement import (suite feature 5)

- **Feature**: suite feature 5, first slice. An officer reads a bank statement CSV, or a transaction CSV an exchange provided, against a case: the rows that match the victim's payments, the UPI/IMPS/NEFT/RTGS references in narrations, the narrations that name a known exchange, on a timeline beside the trace's own on-chain times. The officer may save the rows they confirm (never the whole statement) to the case.
- **Issue**: #144
- **Branch**: four stacked PRs: `feat/bank-statement-import` (#146, the record), `feat/bank-statement-import-routes` (#151, the routes), `feat/bank-statement-import-parse` (#152, reading and matching in the browser), `feat/bank-statement-import-panel` (#153, the panel on the Evidence tab)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: first slice built in four stacked PRs, behind the flag `EXCHEQUER_STATEMENT_IMPORT` (off by default); awaiting review

## Done

- Claimed: issue #144, this file, draft PR #146.
- The record (#146): table `statement_imports` (migration `g7_statements_1`, after `g7_domain_lookups_1`), `backend/app/statement_imports.py` (checks each saved row: date, debit or credit, amount, reference shape, an exchange name only when canonical and in the row's own text, free text refused when it looks like a key), flag `EXCHEQUER_STATEMENT_IMPORT`.
- The routes: `GET /trace/{case_id}/statements` (the saved rows this browser or unit may read, and the canonical exchange names; `enabled: false` with the flag off) and `POST /trace/{case_id}/statements` (403 with the flag off, and 403 for a caller who has not signed in as an officer: security review, 14 Nov). Audited as `statement.list` and `statement.save` with counts only.
- Reading and matching in the browser: `frontend/src/components/case/statement.js`. Header names (`HEADERS`), the account lines above the header skipped, day-first dates (dd/mm/yyyy, dd-MMM-yyyy, ISO for exchanges), amounts with lakh grouping, Dr/Cr suffixes, brackets and signs; NEFT (16), RTGS (22) and UPI/IMPS (12-digit RRN, only in a UPI or IMPS narration) references; canonical exchange names; hashes of the trace; a timeline beside the payments and the arrivals at the attributed exchange address, in India's time.
- The panel: `frontend/src/components/case/StatementPanel.jsx` on the Evidence tab, shown only when the server says the flag is on. Pick bank or exchange and the currency, choose a CSV, check the columns, add the rupee amounts the complaint reports, tick the rows to keep, save. Saved rows are listed with the case.

## Decisions

- The statement is read in the browser. Nothing leaves it until the officer saves the rows they confirmed; the server never sees the rest of the statement.
- Amounts are matched only within one currency: a rupee statement against rupee amounts the officer types from the complaint, an exchange's statement in the traced asset against the case's own payments (`intake.payments`). No exchange rates are used or guessed.
- An exchange is named only when a narration contains one of the repository's own canonical exchange names (the `exchange` field of the label files, as `ExchangeMatcher.exchanges` lists them), as a whole word. A few canonical names that are also ordinary words in Indian statements ("Liquid" as in a liquid fund) are not matched from narrations.
- The audit log records counts only (rows saved, by reason), never an account number, a reference or a narration.
- No real sample statements exist yet; every test row is synthetic and says so.
- An amount matches when it agrees to the places the statement prints (at least two) and its date is within 2 days (`WINDOW_DAYS`) of the payment's date in India. Direction is not required: a refund of the same amount is also worth a look.
- Caps (security review, 14 Nov): at most 50 imports per case, 1,000 per unit, 200 per browser and 10,000 in all (statements and CDRs share the table). An import can be about 150 KB, so the old 100,000 total let one caller grow the table to about 15 GB.

## Next

1. Try the panel with real (redacted) statements, then turn the flag on in production (render.yaml and Render's environment), and remove the flag once it has shipped.
2. Withdrawing a saved import entered by mistake, with a reason kept in its history, like the identifier register.
3. CDR and IPDR (the rest of feature 5) are not started.

## Open questions

- Real statements from the banks officers see most (SBI, HDFC, ICICI, Axis) and from WazirX/CoinDCX would show which header names and narration shapes to add. Owner to obtain redacted samples.

## Files mid-change (do not touch)

- none
