# Handoff: NCRP portal and 1930 links (feature 8)

- **Feature**: beside an NCRP number on the officers' complaint page, a link to the National Cybercrime Reporting Portal (cybercrime.gov.in) and the 1930 National Helpline
- **Issue**: #340
- **Branch**: `feat/ncrp-portal-links`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-16 (status after merge)
- **Status**: merged in #341 on 2026-11-16 (`daaf3b4c`); behind `EXCHEQUER_SOP_SUMMARY` (off)

## Done

- #341: `frontend/src/ncrp.js` holds the portal URL and helpline with their source. `frontend/src/components/NcrpPortalLinks.jsx` (+ CSS, test) shows both links. It is mounted in the header of one complaint (`routes/Complaints.jsx`, one import and one JSX line), under the NCRP number and its note.

## Decisions

- Source: I4C (MHA), "National Cybercrime Reporting Portal [NCRP]", https://i4c.mha.gov.in/ncrp.aspx, read 16.11.2026: "Report a Cybercrime on www.cybercrime.gov.in", "Complaints can be reported through helpline number 1930 or on National Cybercrime Reporting Portal." and "This helps citizens to report cyber financial frauds on National Helpline number 1930." I4C's FAQ (https://i4c.mha.gov.in/FAQ.aspx) says the same. https://cybercrime.gov.in/ answered 200 the same day.
- Only the portal's home page is linked. No published address opens a single complaint, so there is no deep link, and the component takes no number: the NCRP number never goes into a link or any outside request.
- The portal link opens in a new tab with `rel="noopener noreferrer"`, and its text says so. 1930 is a `tel:` link.
- Behind the feature 8 flag `EXCHEQUER_SOP_SUMMARY`, read from `GET /sop-summary` as the crypto summary does; no new flag or backend change.
- Not on the case page's finding bar (`TraceView.jsx`): that line is the trace's answer, and links there would crowd it. Not on the citizen site: its pages already name 1930 and cybercrime.gov.in in text, and the government-platforms handoff asks only for the officer app.
- `docs/suite-features.md` row 8 is left alone: PR #327 edits it, and this changes no feature status. Add a line when the flag goes on.

## Next

1. When `EXCHEQUER_SOP_SUMMARY` goes on (`docs/flag-rollout.md`), check the links on the live complaint page.

## Open questions

- Should the links also sit on the case page, next to the NCRP number in the finding bar? (team)

## Files mid-change (do not touch)

- none
