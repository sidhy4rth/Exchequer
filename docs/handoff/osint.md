# Handoff: osint

- **Feature**: Suite feature 4. Record what the victim reported besides the wallet (scam domain, Telegram handle, phone number, UPI ID), look up public facts about a domain, and link the same identifier across cases.
- **Issue**: #104
- **Branch**: `feat/osint` (slice 1, merged), `feat/osint-domain-lookup` (slice 2), `feat/osint-case-links` (slice 3); `fix/osint-review` (fixes from Barenyam's review, #111)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-13
- **Status**: Slices 1-3 merged (#105, #106, #107) and live. Domain lookups switched ON in production on 2026-11-13 (`EXCHEQUER_OSINT_LOOKUPS=1` in Render, and in `render.yaml`). Review fixes from #111 in review.

## Done

- Claim: this file and a draft PR (#105).
- Slice 1, case identifiers (#105): `backend/app/identifiers.py`, `backend/app/routes/identifiers.py`, model `CaseIdentifier`, migration `g7_identifiers_1` (after `g7_exhibits_1`), 63 backend tests; `IdentifiersPanel` on the Evidence tab under the exhibits (one import, one JSX line), API calls in `frontend/src/api/osint.js`, 7 frontend tests. Merged as db51c23, live.
- Slice 2, domain lookup: `backend/app/domain_lookup.py`, `POST /identifiers/{id}/lookup` in `routes/identifiers.py`, model `DomainLookup`, migration `g7_domain_lookups_1`, flag `EXCHEQUER_OSINT_LOOKUPS` in `config.py` FLAGS, 23 backend tests replaying `tests/fixtures/osint/responses.json` (recorded live 2026-11-13 by `scripts/record_osint_fixtures.py`); the panel's "Look up public records" button and results (registrar, registered on, age when looked up, abuse contact, name servers, where it points, every source with its SHA-256), 4 more frontend tests.
- Slice 3, links across cases: `identifiers.also_in()`; `GET /trace/{case_id}/identifiers` gives each row `also_in` (the other cases with the same kind + normalised value, active on both sides). 8 backend tests, 2 frontend tests; the panel shows "Also in N other cases" with links to each case's Evidence tab.

- Review fixes (#111, Barenyam's review after the merge):
  1. A note added on its own is audited as `identifier.update` with `"changed": [], "noted": true`, never its words (rule 5), as #110 did for exhibits.
  2. Lookups are for a signed-in officer only: the demo caller gets 403 and the list says why (`lookups_note`); the panel shows that line instead of the button.
  3. Retention of raw lookup responses: decided below.
  4. An answer of the wrong shape (a JSON list, `events` that is not a list, …) from IANA, a registry or the resolver is a note or a reasoned 502, never a 500.
  5. One lookup ends within 30 seconds (`DEADLINE_S`), checked before each request and as bytes arrive; httpx's own timeout is per read.
  6. The 50-lookup cap is counted again just before a lookup is kept. Two finishing in the same instant on two workers can still both pass: it bounds use, it is not an exact count.
  7. The Telegram message says 4 to 32 characters, as the check allows.
  8. A trunk 0 typed after a two-digit country code is dropped (`+44 07700 …` is `+44 7700 …`), except Italy (+39), which keeps it. After a three-digit code it is left as typed. Rows recorded before this keep their old form.
  9. CodeQL's URL-substring alert in `test_domain_lookup.py` was fixed in #106 (f886bfe) and is closed.

## Decisions

- The slices follow the issue: (1) a per-case identifier register, (2) domain lookup over fixed RDAP and DNS endpoints, (3) links across cases.
- Results go in their own tables, never inside a trace result, so `docs/contracts/case.md` is not touched.
- Live lookups stay behind a flag (rule 6) until the whole slice is ready. Even with the flag on, only a signed-in officer can make one: each lookup makes the server ask outside services.
- Four kinds only: domain, telegram, phone, upi. Each is kept as typed (`entered`) and normalised (`value`): host name in lower case without scheme/path/port/www; phone as +<country><number> (a bare 10-digit number starting 6-9 is taken as Indian); Telegram username without @ or t.me link, lower case; UPI ID lower case.
- A domain refuses IP addresses, single-label and reserved names (localhost, .local, .internal, .test, .onion …), so slice 2 never looks up a private name.
- Nothing is deleted: a mistake is withdrawn with a reason. Kind and value never change.
- The audit log records the kind and fields changed, never the value (phone numbers and handles are personal data).
- Lookups ask only: IANA's RDAP bootstrap file, the https registry it names for the TLD, and Cloudflare's DNS-over-HTTPS resolver. Redirects are never followed; bodies over 512 kB are refused. The registry is asked for the name, then the name minus its first label (up to 4 tries), so `pay.shop.co.in` finds `shop.co.in`.
- Registrant details are not parsed or shown: usually redacted, and only the registrar can name its customer. Raw bodies are kept in the store (for re-checking), not sent to the screen.
- Retention (13 Nov, Sidhyarth): a raw RDAP body can name a registrant, so it is personal data. It is evidence, like every provider response `evidence.py` keeps: kept with the case for as long as the case is kept, never shown, never exported, read only by `parse_rdap`, which takes registrar facts alone. No case data is deleted today; when the team sets a retention period for cases, lookups follow it.
- Links across cases only look among identifiers the viewer may read (their browser's and their unit's): another unit's cases are never revealed, not even as a count. A withdrawn identifier links nothing. No new table or migration: it is a query on `case_identifiers.value` (indexed).
- The age shown is "N days old when looked up", not "before the case": the case has no reliable opened-on date for every reader.

## Next

1. Done: slices 1-3 merged; lookups on in production, tested end to end on the live site on 2026-11-13 (two test entries for example.com on Sidhyarth's own cases, then withdrawn).
2. Feature 4's first three slices are done. What comes next (e.g. lookups in the case report, links shown on the Cases list) is for the team to choose.

## Open questions

- Whether a lookup should go in the case report (not yet: it is shown on the Evidence tab only).

- How long are phone numbers and handles kept? (Team decides before any export.)

## Files mid-change (do not touch)

- none
