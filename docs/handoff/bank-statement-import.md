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
- The routes: `GET /trace/{case_id}/statements` (the saved rows this browser or unit may read, and the canonical exchange names; `enabled: false` with the flag off) and `POST /trace/{case_id}/statements` (403 with the flag off). Audited as `statement.list` and `statement.save` with counts only.

## Decisions

- The statement is read in the browser. Nothing leaves it until the officer saves the rows they confirmed; the server never sees the rest of the statement.
- Amounts are matched only within one currency: a rupee statement against rupee amounts the officer types from the complaint, an exchange's statement in the traced asset against the case's own payments (`intake.payments`). No exchange rates are used or guessed.
- An exchange is named only when a narration contains one of the repository's own canonical exchange names (the `exchange` field of the label files, as `ExchangeMatcher.exchanges` lists them), as a whole word. A few canonical names that are also ordinary words in Indian statements ("Liquid" as in a liquid fund) are not matched from narrations.
- The audit log records counts only (rows saved, by reason), never an account number, a reference or a narration.
- No real sample statements exist yet; every test row is synthetic and says so.
- Caps (security review, 14 Nov): at most 50 imports per case, 1,000 per unit, 200 per browser and 10,000 in all (statements and CDRs share the table). An import can be about 150 KB, so the old 100,000 total let one caller grow the table to about 15 GB.

## Next

1. Browser: `frontend/src/components/case/statement.js` (columns, Indian dates and amounts, UTR shapes, matching), with tests.
2. Panel: `frontend/src/components/case/StatementPanel.jsx` on the Evidence tab.

## Open questions

- Real statements from the banks officers see most (SBI, HDFC, ICICI, Axis) and from WazirX/CoinDCX would show which header names and narration shapes to add. Owner to obtain redacted samples.
- Withdrawing a saved import entered by mistake is not built yet.

## Files mid-change (do not touch)

- none
