# Handoff: government platforms (feature 8)

- **Feature**: work alongside NCRP, the 1930 helpline and CFCFRMS without any access to them: check an NCRP number's usual shape, and give the officer a crypto summary in the SOP's own terms to enter on CFCFRMS or attach
- **Issue**: #214
- **Branch**: `feat/ncrp-number-check` (#218), `feat/cfcfrms-crypto-summary` (server, stacked on #218), `feat/cfcfrms-crypto-summary-page` (the case page, stacked on that)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16 (status after merge)
- **Status**: merged in #218 (with the summary server and page PRs, #219 and #220) on 2026-11-15; the summary is behind `EXCHEQUER_SOP_SUMMARY` (off). 16 Nov: the SOP steps checklist merged in #327 (`272dc620`, behind `EXCHEQUER_SOP_STEPS`, off) and the cybercrime.gov.in and 1930 links in #341 (`daaf3b4c`, behind `EXCHEQUER_SOP_SUMMARY`, off)

## Done

- #218: one rule for the usual shape of an NCRP acknowledgement number, 14 digits starting with 2 (portal) or 3 (1930), from SOP 6.1(d) and 6.2(c). A soft note only; nothing accepted before is refused. `backend/app/ncrp.py` (the officers' complaint page gets `ncrp_note`), `frontend/src/ncrp.js` (New trace), `citizen/src/api.js` `ncrpNote` (complaint pack and My case).
- Server PR: `backend/app/sop_summary.py` and `backend/app/routes/sop_summary.py`. `GET /sop-summary` says whether it is offered. `POST /trace/{case_id}/sop-summary` with `{"on_cfcfrms": "yes" | "no" | "unknown"}` returns the plain text and audits `case.sop_summary_copy` with only that word. Both answer 404 with the flag off.
- Page PR: `frontend/src/components/case/CryptoSummary.jsx`, mounted on the Letters tab. The officer picks the CFCFRMS answer, may type the NCRP number (filled in by the browser only, never sent), and copies.

## Decisions

- Warn, never refuse, on the NCRP shape: older complaints or other channels may use other formats, and nothing published rules them out.
- The summary holds only what the case holds. It quotes SOP 9.4(ii) (onboarded exchange) or 9.4(iv) (not onboarded: notice under s.106(1) BNSS "through available law enforcement channels or the Sahyog Portal"), or both when the answer is "not known". It never says a provision applies, and it says it is not a CFCFRMS export.
- The CFCFRMS answer is not stored: no per-case field for it exists, and Exchequer holds no list of onboarded exchanges. It lives only in the copied text and as one word in the audit row.
- The NCRP line is a blank in the server's text. The browser fills it with what the officer types, so the number never reaches the server, a log or the audit trail.

## What the research found (15 Nov 2026)

Sources: the MHA "Standard Operating Procedure for (NCRP)-(CFCFRMS), Custody, Restoration of Money and Grievance Redressal", read in a copy a bank publishes (https://www.zoroastrianbank.bank.in/download/SOP-NCRP.pdf; its cover carries no date). The Meghalaya High Court notified the same SOP on 28.04.2026. The quotes in `sop_summary.py` were also checked word for word against the copy at https://the420.in/wp-content/uploads/2026/01/sop.pdf, whose cover is dated 02.01.2026.

Quote check of 15 Nov 2026, against the rendered pages (the bank copy's text layer runs some text a page out, so a text dump gives wrong pages and, once, a wrong word):
- Bank copy (52 PDF pages, SHA-256 `65400b47…3bd42`, pages print no numbers): 6.1(d) on PDF page 12, 6.2(c) on page 13, all of 9.4 on page 19, Annexure I on page 34, Annexure II on page 35.
- the420.in copy (99 PDF pages, SHA-256 `75251166…a00a80d`, printed "Page N of 98" from the second page): 9.4 on printed pages 28 to 30, both quoted sentences on printed page 29 (PDF page 30). Its 9.4 ends with a list of P2P details for the VASP to update that the bank copy does not have, so the two copies are not the same text.
- Every quote in this stack matched both copies word for word. Fixed: `sop_summary.py`'s source line had put the 02.01.2026 cover date and "pages 28 to 30" on the bank copy; it now names each copy with its own page and date. The SOP title in the NCRP comments now follows the bank copy's cover. The other source is Lok Sabha Unstarred Q. 274, answered 21.07.2026. No portal was logged into or contacted.

- **NCRP and CFCFRMS**: MHA owns NCRP, including CFCFRMS, and NIC built it under I4C. State and UT police run the 1930 helpline. Every police station reports on CFCFRMS through an authorised officer.
- **The only documented API runs between the portal and banks or financial institutions** (as DFS and RBI suggest). Nothing is published for police-side or third-party tools: no API, no bulk export, no input-form field list.
- **Crypto (SOP 9.4)**:
  - An onboarded VASP holds the amount, liquidates on the police's lawful instruction, and updates CFCFRMS with KYC, bank accounts, "transaction ID or Hash, wallet ID, and liquidation details".
  - For an exchange not onboarded, the LEA may issue a s.106(1) BNSS notice, and may run a "VDA forensic analysis" to find which VASP controls the wallet. That analysis is what Exchequer does.
  - No public list of onboarded exchanges was found.
- **SOP Annexures I and II**:
  - Annexure I is a notice under s.168 read with s.94 BNSS, to hold money. Annexure II is a notice under s.106(1) BNSS, to seize.
  - Both are pushed to the bank through CFCFRMS.
  - Their fields are the only CFCFRMS-related field lists published.
- **Samanvaya**: an LEA-only data and coordination platform, with no public access route.
- **Sahyog**: notices to intermediaries under s.79(3)(b) of the IT Act. Since 15.11.2025, a police notice must come from a specially authorised officer of DIG rank or above. There is no role for a third-party tool.
- **CCTNS and ICJS**: APIs exist only between the pillars.
- **Official route for a third-party tool**: none published for any of these platforms. I4C's MoUs found are all with public bodies. The realistic route is a state police cyber cell pilot, then an introduction to I4C.

## Next

1. Owner: answer the questions below. The first one blocks a CFCFRMS notice draft (research option 2).
2. After a partner cell confirms its workflow, switch the flag on (`docs/flag-rollout.md`).
3. Later options from the research:
   - SOP deadlines in the asset register (90-day hold, 15-day grievance decision, 2-day bank reply, 1-week KYC update): done in #230 (`docs/handoff/sop-deadlines.md`), behind `EXCHEQUER_SOP_DEADLINES` (off)
   - reading an NCRP complaint PDF the officer already has (needs redacted samples)
   - links to cybercrime.gov.in and 1930: done, on the officers' complaint page, merged in #341 (`daaf3b4c`, `docs/handoff/ncrp-portal-links.md`), behind `EXCHEQUER_SOP_SUMMARY` (off). Source: I4C (MHA), https://i4c.mha.gov.in/ncrp.aspx, read 16.11.2026. Only the portal's home page: no published address opens one complaint, so no deep link.

## Open questions (owner)

- **Legal check (owner and an advocate)**: the SOP puts bank holds under s.168 read with s.94 BNSS (6.1(g), Annexure I). `notice_letters.py` refuses a bank-freeze draft without a Magistrate's order. Which rule should a CFCFRMS notice draft follow? No code changes until this is answered.
- **A partner state cyber cell** (SP Cyber, or the State Nodal Officer for NCRP):
  - a pilot letter
  - redacted samples of an NCRP acknowledgement, a complaint PDF and a CFCFRMS action screen
  - which exchanges they treat as onboarded on CFCFRMS
  - permission to describe their workflow
- **The I4C route (CEO I4C, or its research and innovation vertical), introduced by that state**:
  - whether a read-only or export route for LEA tools exists or is planned
  - whether exchanges' onboarding status could be shared with police tools
- **Lower priority**: NCRB or the State Crime Records Bureau, on whether CCTNS 2.0 lets an investigating officer attach a document. Sahyog: nothing to ask.

## Files mid-change (do not touch)

- none
