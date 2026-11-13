# Handoff: osint

- **Feature**: Suite feature 4. Record what the victim reported besides the wallet (scam domain, Telegram handle, phone number, UPI ID), look up public facts about a domain, and link the same identifier across cases.
- **Issue**: #104
- **Branch**: `feat/osint` (slice 1, merged), `feat/osint-domain-lookup` (slice 2)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-13
- **Status**: Slice 1 merged (#105, live). Slice 2 (domain lookup) built on `feat/osint-domain-lookup`, behind `EXCHEQUER_OSINT_LOOKUPS`. Slice 3 not started.

## Done

- Claim: this file and a draft PR (#105).
- Slice 1, case identifiers (#105): `backend/app/identifiers.py`, `backend/app/routes/identifiers.py`, model `CaseIdentifier`, migration `g7_identifiers_1` (after `g7_exhibits_1`), 63 backend tests; `IdentifiersPanel` on the Evidence tab under the exhibits (one import, one JSX line), API calls in `frontend/src/api/osint.js`, 7 frontend tests. Merged as db51c23, live.
- Slice 2, domain lookup: `backend/app/domain_lookup.py`, `POST /identifiers/{id}/lookup` in `routes/identifiers.py`, model `DomainLookup`, migration `g7_domain_lookups_1`, flag `EXCHEQUER_OSINT_LOOKUPS` in `config.py` FLAGS, 23 backend tests replaying `tests/fixtures/osint/responses.json` (recorded live 2026-11-13 by `scripts/record_osint_fixtures.py`); the panel's "Look up public records" button and results (registrar, registered on, age when looked up, abuse contact, name servers, where it points, every source with its SHA-256), 4 more frontend tests.

## Decisions

- The slices follow the issue: (1) a per-case identifier register, (2) domain lookup over fixed RDAP and DNS endpoints, (3) links across cases.
- Results go in their own tables, never inside a trace result, so `docs/contracts/case.md` is not touched.
- Live lookups stay behind a flag (rule 6) until the whole slice is ready.
- Four kinds only: domain, telegram, phone, upi. Each is kept as typed (`entered`) and normalised (`value`): host name in lower case without scheme/path/port/www; phone as +<country><number> (a bare 10-digit number starting 6-9 is taken as Indian); Telegram username without @ or t.me link, lower case; UPI ID lower case.
- A domain refuses IP addresses, single-label and reserved names (localhost, .local, .internal, .test, .onion …), so slice 2 never looks up a private name.
- Nothing is deleted: a mistake is withdrawn with a reason. Kind and value never change.
- The audit log records the kind and fields changed, never the value (phone numbers and handles are personal data).
- Lookups ask only: IANA's RDAP bootstrap file, the https registry it names for the TLD, and Cloudflare's DNS-over-HTTPS resolver. Redirects are never followed; bodies over 512 kB are refused. The registry is asked for the name, then the name minus its first label (up to 4 tries), so `pay.shop.co.in` finds `shop.co.in`.
- Registrant details are not parsed or shown: usually redacted, and only the registrar can name its customer. Raw bodies are kept in the store (for re-checking), not sent to the screen.
- The age shown is "N days old when looked up", not "before the case": the case has no reliable opened-on date for every reader.

## Next

1. Get the slice 2 PR reviewed and merged; then switch `EXCHEQUER_OSINT_LOOKUPS` on in Render once the team agrees.
2. Slice 3: show where the same `kind` + `value` appears in another case the viewer may read.

## Open questions

- When to switch lookups on in production (Render env var), and whether a lookup should go in the case report.

- How long are phone numbers and handles kept? (Team decides before any export.)

## Files mid-change (do not touch)

- none
