# Handoff: bank and exchange statement import (suite feature 5)

- **Feature**: suite feature 5, first slice. An officer reads a bank statement CSV, or a transaction CSV an exchange provided, against a case: the rows that match the victim's payments, the UPI/IMPS/NEFT/RTGS references in narrations, the narrations that name a known exchange, on a timeline beside the trace's own on-chain times. The officer may save the rows they confirm (never the whole statement) to the case.
- **Issue**: #144
- **Branch**: four stacked PRs: `feat/bank-statement-import` (the record), `feat/bank-statement-import-routes` (the routes), `feat/bank-statement-import-parse` (reading and matching in the browser), `feat/bank-statement-import-panel` (the panel on the Evidence tab)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: in progress, behind the flag `EXCHEQUER_STATEMENT_IMPORT` (off by default)

## Done

- Claimed: issue #144, this file, draft PR #146.
- The record (#146): table `statement_imports` (migration `g7_statements_1`, after `g7_domain_lookups_1`), `backend/app/statement_imports.py` (checks each saved row: date, debit or credit, amount, reference shape, an exchange name only when canonical and in the row's own text, free text refused when it looks like a key), flag `EXCHEQUER_STATEMENT_IMPORT`.

## Decisions

- The statement is read in the browser. Nothing leaves it until the officer saves the rows they confirmed; the server never sees the rest of the statement.
- Amounts are matched only within one currency: a rupee statement against rupee amounts the officer types from the complaint, an exchange's statement in the traced asset against the case's own payments (`intake.payments`). No exchange rates are used or guessed.
- An exchange is named only when a narration contains one of the repository's own canonical exchange names (the `exchange` field of the label files, as `ExchangeMatcher.exchanges` lists them), as a whole word. A few canonical names that are also ordinary words in Indian statements ("Liquid" as in a liquid fund) are not matched from narrations.
- The audit log records counts only (rows saved, by reason), never an account number, a reference or a narration.
- No real sample statements exist yet; every test row is synthetic and says so.

## Next

1. Routes: `backend/app/routes/statements.py` (GET and POST `/trace/{case_id}/statements`).
2. Browser: `frontend/src/components/case/statement.js` (columns, Indian dates and amounts, UTR shapes, matching), with tests.
3. Panel: `frontend/src/components/case/StatementPanel.jsx` on the Evidence tab.

## Open questions

- Real statements from the banks officers see most (SBI, HDFC, ICICI, Axis) and from WazirX/CoinDCX would show which header names and narration shapes to add. Owner to obtain redacted samples.
- Withdrawing a saved import entered by mistake is not built yet.

## Files mid-change (do not touch)

- none
