# Handoff: osint

- **Feature**: Suite feature 4. Record what the victim reported besides the wallet (scam domain, Telegram handle, phone number, UPI ID), look up public facts about a domain, and link the same identifier across cases.
- **Issue**: #104
- **Branch**: `feat/osint`
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-13
- **Status**: Slice 1 (case identifiers) built and pushed in #105; slices 2 and 3 not started.

## Done

- Claim: this file and a draft PR (#105).
- Slice 1, case identifiers (#105): `backend/app/identifiers.py`, `backend/app/routes/identifiers.py`, model `CaseIdentifier`, migration `g7_identifiers_1` (after `g7_exhibits_1`), 63 backend tests; `IdentifiersPanel` on the Evidence tab under the exhibits (one import, one JSX line), API calls in `frontend/src/api/osint.js`, 7 frontend tests.

## Decisions

- The slices follow the issue: (1) a per-case identifier register, (2) domain lookup over fixed RDAP and DNS endpoints, (3) links across cases.
- Results go in their own tables, never inside a trace result, so `docs/contracts/case.md` is not touched.
- Live lookups stay behind a flag (rule 6) until the whole slice is ready.
- Four kinds only: domain, telegram, phone, upi. Each is kept as typed (`entered`) and normalised (`value`): host name in lower case without scheme/path/port/www; phone as +<country><number> (a bare 10-digit number starting 6-9 is taken as Indian); Telegram username without @ or t.me link, lower case; UPI ID lower case.
- A domain refuses IP addresses, single-label and reserved names (localhost, .local, .internal, .test, .onion …), so slice 2 never looks up a private name.
- Nothing is deleted: a mistake is withdrawn with a reason. Kind and value never change.
- The audit log records the kind and fields changed, never the value (phone numbers and handles are personal data).

## Next

1. Get #105 reviewed and merged.
2. Slice 2, domain lookup: a client for fixed RDAP (via the IANA bootstrap file) and DNS-over-HTTPS endpoints, taking only a name that `identifiers.domain()` accepted; store each raw response with provider, fetch time and SHA-256 (as `evidence.py` does); behind a flag in `config.py` FLAGS; tests use recorded responses, refreshed only by a hand-run script.
3. Slice 3: show where the same `kind` + `value` appears in another case the viewer may read.

## Open questions

- How long are phone numbers and handles kept? (Team decides before any export.)

## Files mid-change (do not touch)

- none
