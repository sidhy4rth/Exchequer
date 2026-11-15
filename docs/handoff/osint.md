# Handoff: osint

- **Feature**: Suite feature 4. Record what the victim reported besides the wallet (scam domain, Telegram handle, phone number, UPI ID), look up public facts about a domain, and link the same identifier across cases.
- **Issue**: #104; Telegram lookup #161
- **Branch**: `feat/osint` (slice 1, merged), `feat/osint-domain-lookup` (slice 2), `feat/osint-case-links` (slice 3); `fix/osint-review` (fixes from Barenyam's review, #111); `feat/osint-telegram` (slice 4, Telegram public-page lookup, #161)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: Slices 1-3 merged (#105, #106, #107) and live. Domain lookups switched ON in production on 2026-11-13 (`EXCHEQUER_OSINT_LOOKUPS=1` in Render, and in `render.yaml`). Review fixes from #111 merged (#115). Slice 4, a Telegram username's public t.me page (#161), in review as three stacked PRs (#162, #169, #170), off behind `EXCHEQUER_TELEGRAM_LOOKUPS`.

## Done

- Claim: this file and a draft PR (#105).
- Slice 1, case identifiers (#105): `backend/app/identifiers.py`, `backend/app/routes/identifiers.py`, model `CaseIdentifier`, migration `g7_identifiers_1` (after `g7_exhibits_1`), 63 backend tests; `IdentifiersPanel` on the Evidence tab under the exhibits (one import, one JSX line), API calls in `frontend/src/api/osint.js`, 7 frontend tests. Merged as db51c23, live.
- Slice 2, domain lookup: `backend/app/domain_lookup.py`, `POST /identifiers/{id}/lookup` in `routes/identifiers.py`, model `DomainLookup`, migration `g7_domain_lookups_1`, flag `EXCHEQUER_OSINT_LOOKUPS` in `config.py` FLAGS, 23 backend tests replaying `tests/fixtures/osint/responses.json` (recorded live 2026-11-13 by `scripts/record_osint_fixtures.py`); the panel's "Look up public records" button and results (registrar, registered on, age when looked up, abuse contact, name servers, where it points, every source with its SHA-256), 4 more frontend tests.
- Slice 3, links across cases: `identifiers.also_in()`; `GET /trace/{case_id}/identifiers` gives each row `also_in` (the other cases with the same kind + normalised value, active on both sides). 8 backend tests, 2 frontend tests; the panel shows "Also in N other cases" with links to each case's Evidence tab.

- Slice 4, Telegram public page (#161): `backend/app/telegram_lookup.py` (fetch and parse, part 1, #162); `POST /identifiers/{id}/lookup` takes a Telegram username when `EXCHEQUER_TELEGRAM_LOOKUPS` is on too, kept in `domain_lookups`, audited by ids and yes/no (part 2); `TelegramPage` in the identifiers panel (part 3). Tests run on hand-written synthetic pages in `backend/tests/fixtures/osint/telegram/`.

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
- Wallet kind (#164, with feature 2 #145; branch `feat/forensic-import-identifiers`): `wallet` in `KINDS`,
  normalised by `identifiers.wallet()` with the trace form's own checks from `etherscan_client.py`
  (`is_evm_address` + `evm_checksum_ok`, `is_tron_address`): EVM kept in lower case, Tron as typed.
  A mixed-case EVM address with a wrong EIP-55 checksum, a wrong length or a Tron checksum typo is
  refused. Links across cases work for it unchanged (same kind + normalised value). No migration:
  `kind` is a plain String(16) with no check constraint. The panel names it "Wallet address"; no
  lookup is offered for it.

## Decisions

- Telegram (slice 4): the server asks only `https://t.me/<username>`, the public preview page anyone sees without Telegram. No login, no API key, no Telegram API, no messages, no link on the page followed, no redirect followed, at most 256 kB, within 15 s. It keeps what the page shows: whether it shows an account, the title, the type the page's words give (channel, group, user, bot, or not said), the count line as written, the description, and a verified / scam / fake badge when the title's markup has one. The page body is kept as evidence with its SHA-256, under the same retention rule as RDAP bodies.
- A username is looked up only if t.me can have a page for it: 5 to 32 of a-z, 0-9, _, starting with a letter, not ending with _, and not one of t.me's own paths (joinchat, share, proxy …). The register still keeps 4-character usernames; they are not looked up.
- Telegram lookups have their own flag, `EXCHEQUER_TELEGRAM_LOOKUPS` (with `EXCHEQUER_OSINT_LOOKUPS`), off by default: domain lookups are already on in production, and t.me's page markup has not yet been checked end to end from the live site. They share the `domain_lookups` table and its 50-lookup cap (no migration).
- The page's scam and fake badges are read from class names in the title that contain "scam" or "fake"; their exact markup on t.me was not seen (no example to hand), so the test page for them is an assumption, marked as such.

- The slices follow the issue: (1) a per-case identifier register, (2) domain lookup over fixed RDAP and DNS endpoints, (3) links across cases.
- Results go in their own tables, never inside a trace result, so `docs/contracts/case.md` is not touched.
- Live lookups stay behind a flag (rule 6) until the whole slice is ready. Even with the flag on, only a signed-in officer can make one: each lookup makes the server ask outside services.
- Four kinds at first (domain, telegram, phone, upi); a fifth, wallet, added for the export scan (feature 2). Each is kept as typed (`entered`) and normalised (`value`): host name in lower case without scheme/path/port/www; phone as +<country><number> (a bare 10-digit number starting 6-9 is taken as Indian); Telegram username without @ or t.me link, lower case; UPI ID lower case.
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

- Switch on `EXCHEQUER_TELEGRAM_LOOKUPS` in production? First read one public channel's page from the live site by hand and check the fields shown (Sidhyarth).

- Whether a lookup should go in the case report (not yet: it is shown on the Evidence tab only).

- How long are phone numbers and handles kept? (Team decides before any export.)

## Files mid-change (do not touch)

- none (slice 4 is complete in its three PRs, awaiting review)
