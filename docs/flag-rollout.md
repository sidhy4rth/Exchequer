# Switching on the flagged features

Seven features are built behind `config.py` flags, and all of them are now on
`main`, switched off (as of 2026-11-15): custody wallets (#129), statements and
call detail records (#146), the export scan (#147), Telegram lookups (#162),
the crypto summary for CFCFRMS (#218) and the SOP reminders on bank holds
(#230), each with the PRs merged with it. Every flag on `main` is listed first, below. Each flag is off until its environment variable
is `1` (`true`, `yes` and `on` also count; see `flag()` in `config.py`). This
file says, for each one: what it turns on, which PRs it came in, how
to switch it on and off, what to try on the live site before telling anyone,
and the decisions still open.

Everything here comes from the PR descriptions, the handoff files and the flag definitions. Where something was not checked, it says so.
Button names are taken from the PRs' tests and may differ slightly on screen.

## Flags already on `main`

Every flag in `config.py` `FLAGS` on `main` (2026-11-15). "Off in `render.yaml`"
means the Blueprint does not set it; whether the dashboard sets it is not
checked here, so read `/health/detail` → `flags` to be sure.

| Flag | What it turns on | Merged in | Status |
|---|---|---|---|
| `EXCHEQUER_TX_INTAKE` | Lane A, R1: start a trace from the victim's payment transaction hash | #49 | Off in `render.yaml` |
| `EXCHEQUER_TRACING_METHODS` | Lane A, R4: FIFO and LIBR beside pro-rata (one more read per hop) | #49 | Off in `render.yaml` |
| `EXCHEQUER_TAINT_EXPANSION` | Lane A, R5: follow every branch carrying a share of the funds, not the top ten | #49 | Off in `render.yaml` |
| `EXCHEQUER_OSINT_LOOKUPS` | Feature 4: live RDAP and DNS lookups of a case's scam domains, for signed-in officers | #106 | **On** in production since 13 Nov, and `"1"` in `render.yaml` (#108) |
| `EXCHEQUER_PRIVACY_CATEGORY` | #189: privacy protocols (Railgun, Aztec, Hinkal, Privacy Pools) shown on a trace as a note, never a risk hit or a stop | with #149 (#194, #195, #196, #198) | Off in `render.yaml`. Its handoff records the owner's approval on 14 Nov to switch it on after merge; not switched on yet as far as `main` shows |
| `EXCHEQUER_CASE_BUNDLE` | Feature 6: one zip of a case's report, registers and audit trail, with a manifest | #187 (+#190) | Off in `render.yaml` |
| `EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT` | Trace engine: stop a `POST /trace` whose client hung up, at its next provider request | #227 (+#228) | Off in `render.yaml`; awaits the owner |
| `EXCHEQUER_STORE_EXCHANGE_ROWS` | #222: name the exchange from exchange rows in the label store (an exchange's own proof-of-reserves list; ADR-0011) | #223 (+#224) | Off in `render.yaml`; the deployed store (`labels-2026-11-14b`) has no exchange rows yet |
| `EXCHEQUER_CUSTODY_WALLETS` | Feature 9: custody wallet records and their signing log (never a key) | #129 (+#139, #140, #142) | Off in `render.yaml`; see its section below |
| `EXCHEQUER_STATEMENT_IMPORT` | Feature 5: read a bank or exchange statement CSV against a case; save the rows the officer confirms | #146 (+#151, #152, #153, #183, #184) | Off in `render.yaml`; see its section below |
| `EXCHEQUER_CDR_IMPORT` | Feature 5: read a call detail record CSV against a case; save a summary the officer confirms | #168 (+#172, #173), merged with #146 | Off in `render.yaml`; see its section below |
| `EXCHEQUER_EXPORT_SCAN` | Feature 2: scan a phone or computer export in the browser for addresses, hashes and seed phrases | #147 (+#154, #155, #156, #164) | Off in `render.yaml`; see its section below |
| `EXCHEQUER_TELEGRAM_LOOKUPS` | Feature 4, OSINT slice 4: read a Telegram username's public t.me page (needs `EXCHEQUER_OSINT_LOOKUPS` too) | #162 (+#169, #170) | Off in `render.yaml`; see its section below |
| `EXCHEQUER_SOP_SUMMARY` | Feature 8: a copy-ready crypto summary of a case in the CFCFRMS SOP's 9.4 terms | #218 (+#219, #220) | Off in `render.yaml`; see its section below |
| `EXCHEQUER_SOP_DEADLINES` | Feature 8: the MHA CFCFRMS SOP's time limits, quoted, as reminders on bank holds in the asset register | #230 | Off in `render.yaml`; see its section below |
| `EXCHEQUER_FREEZE_WORDING_V2` | Feature 7, #251: the bank-hold notice asks the bank to give effect to the Magistrate's order as it directs, not for a "debit freeze" | #252 | Off in `render.yaml`; awaits a lawyer; see its section below |

That is all sixteen flags in `FLAGS` on `main`.

The rest of this file is about the seven features named at the top. The steps
below for switching on, checking and switching off apply to every flag above.

## The same steps for every flag

### Before: merged and deployed

1. Every stack named here is merged (each section lists its PRs), and Render
   deploys every push to `main`. A merged stack changes nothing a user sees
   while its flag is off, but any migration in it runs at start-up
   (`models.init_db()`), so its tables are already there.
2. The migrations run in one line on `main`: `g7_tasks_2` → `g7_custody_1` →
   `g7_custody_2` → `g7_statements_1` → `g7_statements_2`, so the head on
   `main` is `g7_statements_2` and the `down_revision` re-points are done. The
   Telegram, SOP summary and SOP reminder stacks add no migration. Never edit a
   migration that is already on `main`.

### Switching it on (as #108 did for `EXCHEQUER_OSINT_LOOKUPS`)

1. Render dashboard → the `exchequer` service → Environment → add the variable
   with value `1` → save and deploy. Flags are read once at start-up, so the
   value takes effect only after the restart.
2. Check that it took: `GET /health/detail` with the bearer token
   `EXCHEQUER_HEALTH_TOKEN` lists every flag under `flags` with `"on": true|false`.
   Never paste the token into an issue, PR or chat.
3. Do the checklist in the flag's section, on the live site, as a **test
   officer**. Do not use the public demo cases or any real case.
4. Then open a small PR that adds the same key to `render.yaml`, after
   `EXCHEQUER_OSINT_LOOKUPS`, with a comment saying what it turns on and what it
   contacts, if anything. Copy #108. That way the setting survives if the service
   is ever re-created from the Blueprint. A value only in `render.yaml` does not
   reach the running service on its own: it needs a Blueprint sync or the
   dashboard change above (`docs/operations.md`, Deploying).
5. Update the feature's row in `docs/suite-features.md` and its handoff file in that PR.

### The test officer and test case

- In `/admin`, make a unit for testing (for example "Test unit") and the officer
  accounts the checklist needs in it. Custody needs **two** officers in the same unit.
- Sign in at `/signin/investigator` as that officer, open New trace and trace one
  of the addresses in `DEMO.md`. A new trace of a demo address belongs to whoever
  ran it (`ownership.py`), so this makes a stored case of the test unit's own, and
  the public demo case is left alone.
- Use only synthetic data: the files each section names, which the PRs' own tests use.
  Never use a real statement, CDR, phone export, phone number or seized wallet.
- Nothing in these registers can be deleted. A wallet record stays on the test
  case for good. A movement can be cancelled, an identifier withdrawn, and a
  saved statement or CDR import withdrawn (#183, #184), each with a reason; a
  withdrawn one is kept and marked so. Put "TEST" in notes and titles.

### Watching it afterwards

- **Render logs.** Each audited action writes a line `audit <event> case=<id>
  detail=sha256:…`. Look for HTTP 500s on the new routes, and for `Audit event …
  could not be stored`, which means an action happened but its audit row was not
  kept.
- **Audit rows.** `GET /audit?case_id=<id>` while signed in as the test officer
  gives the case's events. Each section names the events to look for. The detail
  must be ids and counts only: never a name, number, address or text. With the
  health token, `GET /audit/verify` should still answer `ok: true`.
- **The flag itself.** `/health/detail` → `flags` after every deploy. A service
  re-created from `render.yaml` before the `render.yaml` PR merges would start
  with the flag off.

### Switching it off

Set the variable to `0` (or delete it) in Render → save and deploy. Then open a PR
setting it to `"0"` in `render.yaml`, if it was added there. Turning a flag off
hides the screen and refuses the writes. **It deletes nothing:** tables and saved
rows stay, and come back when the flag is turned on again. Never downgrade a
migration to turn a feature off.

## `EXCHEQUER_CUSTODY_WALLETS`: custody wallets and their signing log (feature 9)

**What it turns on.** A "Custody wallets" panel on the Letters tab, under the
asset register. An officer records each multisig wallet that holds a case's
seized crypto: chain, address, threshold m of n (at least 2), and the signers by
name, role and unit. It then keeps a signing log of every deposit and release:
proposed → approved by distinct signers → broadcast (with the transaction hash)
→ confirmed, or cancelled with a reason. The server never receives, stores or
generates a key, seed phrase or signature, and Exchequer moves no funds.

**Merged.** #129, with #139, #140 and #142, on `main`. Migrations `g7_custody_1`
and `g7_custody_2` (see the migration note above). Have the unit read
`docs/custody-procedure.md` (#142) before the flag goes on. The handoff asks for this.

**Try it on the live site** (two test officers, A and B, in the test unit; on the test case):

1. As A, open the Letters tab: the Custody wallets panel shows under the asset register.
2. Try to record a wallet with threshold 1: refused. Put the BIP-39 list's first
   twelve words (what the tests use; not a valid mnemonic) in a signer's name or
   in the notes: refused.
3. Record a wallet, 2 of 2, signers A and B. Use an address the unit itself
   controls, such as the test Safe from the procedure's small-amount step, and
   never one from a case. If the case has an asset-register row held in custody,
   link it.
4. Propose a release without a court order reference: refused. Propose a deposit instead.
5. As A, record A's approval. Try a second approval from A's account: refused
   (one approval per account).
6. Sign in as B in another browser and record B's approval: the movement shows
   as approved.
7. Cancel it with the reason "TEST". Do not record a broadcast: that needs a
   real transaction hash, and a recorded one cannot be removed.
8. Audit rows: `custody.list`, `custody.add`, `custody.movement.propose`,
   `custody.movement.approve` (twice), `custody.movement.cancel`. Each detail
   holds ids, step, status and approval count, and no signer name, order
   reference or reason.

**Owner decisions still open** (handoff `docs/handoff/custody-wallets.md`):

- Signer rotation (replacing an owner of the same Safe) is not modelled. Today
  it means a new record. Is that enough?
- Must the officer who enters an approval be someone other than the officer who
  entered the proposal? Today one account may propose and enter one approval.

## `EXCHEQUER_STATEMENT_IMPORT`: bank and exchange statements (feature 5, first slice)

**What it turns on.** A statement panel on the Evidence tab. The officer picks a
bank statement CSV, or a transaction CSV an exchange provided. It is read **in
the browser** and lined up with the case: rows matching the victim's payments
(same currency, same amount, within 2 days), NEFT/RTGS/UPI/IMPS references, and
narrations that name a known exchange. They are shown on a timeline beside the
trace. Only the rows the officer ticks are sent and saved, never the whole
statement. The audit log holds counts only.

**Merged.** #146, with #151, #152, #153, and the withdrawal PRs #183 and #184, on
`main`. Migrations `g7_statements_1` and `g7_statements_2` (see the migration note above).

**Try it on the live site** (one test officer, on the test case):

1. Make `statement.csv` from the five `CSV` lines in
   `frontend/src/components/case/StatementPanel.test.jsx`. It is synthetic: a test account number
   and invented references.
2. Evidence tab: the statement panel shows. Choose bank, INR, and the file.
3. With the browser's Network tab open: reading the file sends nothing. Two
   rows are worth a look, the grocery row is not, and one says it names CoinDCX.
4. Add "Rupees paid, from the complaint" 2,50,000 on 2026-03-12: the NEFT row
   now says amount and date match.
5. Untick the CoinDCX row and save. The one POST carries only the ticked row.
   Reload: the saved row is listed.
6. Withdraw the saved import with the reason "TEST". It drops out of the list,
   and shows again, struck through, with "show withdrawn".
7. Audit rows: `statement.list`, `statement.save`, `statement.withdraw`, with
   counts by reason or the import's id, and no account number, reference,
   narration or reason.

**Owner decisions still open** (handoff `docs/handoff/bank-statement-import.md`, #153):

- **Real redacted samples are needed before switching on.** Statements from the
  banks officers see most (SBI, HDFC, ICICI, Axis) and from WazirX and CoinDCX
  would show which header names and narration shapes to add. Every test row so
  far is synthetic. The handoff's own next step is "try the panel with real
  (redacted) statements, then turn the flag on".

## `EXCHEQUER_CDR_IMPORT`: call detail records (feature 5, second slice)

**What it turns on.** A CDR panel on the Evidence tab. A call detail record CSV
is read in the browser (an XLSX must be saved as CSV first). It shows the CDR's
own number, the top contacts by calls or call time, handsets (IMEI) and SIMs
(IMSI) and how often they changed, the most used cells, and which numbers are
on this case's phone identifiers. For numbers the officer ticks, it shows which
of their other cases have them. Only a summary the officer ticks is saved: never
a row of the CDR. A number is a lead, not a person.

**Merged.** #168, #172 and #173, with the statements stack in #146 (CDR
summaries are kept in the same `statement_imports` table). No migration of its
own. It has its own flag, so statements can go live first.

**Try it on the live site** (one test officer, on the test case):

1. In the identifiers panel, add the phone identifier `+44 7700 900003`. It is in
   Ofcom's range for drama, so no subscriber holds it.
2. Make `cdr.csv` from the four `CSV` lines in
   `frontend/src/components/case/CdrPanel.test.jsx`.
   Never use a 10-digit number starting 6 to 9 in a test file: any of them could
   be a real subscriber's.
3. Evidence tab → CDR panel → choose the file. Reading sends nothing. The CDR's
   own number is `+447700900001`, and `+447700900003` is marked as on the case's
   identifiers.
4. Tick one number and check it: only that number is sent, and only cases the
   officer can already read are searched.
5. Tick a contact and the handset, then save. The POST carries the summary rows
   only.
6. Audit rows: `cdr.list`, `cdr.check`, `cdr.save`, counts only. Search the
   Render log for `7700900`: it must not appear.
7. Withdraw the saved CDR summary and the test phone identifier, each with the
   reason "TEST". The summary's withdrawal is audited as `cdr.withdraw`.

**Owner decisions still open** (handoff, #173):

- **Real redacted CDRs are needed before switching on**, from Airtel, Jio, Vi
  and BSNL. They would show the header names and call-type spellings to add to
  `CDR_HEADERS` and `eventType`. All test data is synthetic.
- Reading XLSX directly would need a new dependency, in its own PR. Today it is CSV only.
- IPDR is not started.
- `docs/handoff/osint.md` still asks how long phone numbers and handles are kept.
  A saved CDR summary keeps phone numbers too, so that answer probably covers it
  (not decided anywhere yet).

## `EXCHEQUER_EXPORT_SCAN`: scanning a phone or computer export (feature 2)

**What it turns on.** An "Export scan" section on the Evidence tab of a stored
case. The officer picks a text export (CSV, TSV, XML, JSON, HTML, text) and it is
read **in the browser**, in 1 MB pieces, with a Stop button. It finds addresses of
the chains Exchequer traces (EIP-55 and Tron Base58Check checks), 64-hex values
(which may be transaction hashes), and runs of 12 or more BIP-39 words. A seed
run is shown only as "N BIP-39 words at line L, hidden": the words are never
kept, shown or sent. Each address gets a Trace link, which waits for a click.
The server records only that a scan ran, with five counts.

**Merged.** #147, with #154, #155, #156 and #164, on `main`. #164 adds "Add as
case identifier" to each address row. No migration.

**Note on #164.** It adds a `wallet` kind to the identifier register. That kind
is **not behind any flag**: since #164 merged, "Wallet address" can be typed by
hand in the identifiers panel, even while `EXCHEQUER_EXPORT_SCAN` is off. Only
the export scan's "Add as case identifier" button waits for the flag.

**Try it on the live site** (one test officer, on the test case):

1. Make a text file holding one EVM address, one Tron address and one transaction
   hash, all copied from `DEMO.md`. Add a line with the BIP-39 list's first twelve
   words (what the tests use; not a valid mnemonic) and some ordinary sentences.
2. Evidence tab → Export scan → pick the file. The summary counts lines, size,
   addresses, 64-hex values and seed runs. The seed run reads "12 BIP-39 words at
   line N, hidden", and none of the twelve words appears anywhere on the page.
3. Network tab: after picking the file, the only request is `POST /trace/{case_id}/export-scan`, with
   exactly `lines, bytes, addresses, tx_hashes, seed_runs`. No value, word or file
   name is sent.
4. The Trace link opens the trace form filled in and waits. Do not run it unless
   you mean to.
5. Pick a binary file (an image): it says to export it as text.
6. "Add as case identifier" on one address. It appears in the
   identifiers panel without a reload, and a second click says "Already on the
   case". Withdraw it afterwards with the reason "TEST".
7. Audit rows: `export_scan.open`, `export_scan.run` (the five counts), and
   `identifier.add` with the kind only, no address.

**Owner decisions still open:**

- **Chain on wallet identifiers (#164).** The chain is inferred from the address
  and not stored: an EVM address is the same on Ethereum, BNB Chain, Polygon and
  Arbitrum, so two cases naming it are linked whichever chain each traced. Is that
  right, or should the officer record a chain?
- The `wallet` kind went live with #164 before the export scan is switched on
  (see the note above). Keep it that way, or put it behind the flag?
- Vendor importers (Cellebrite UFDR, Magnet AXIOM, MSAB XRY, Oxygen, Autopsy)
  need sample exports. None exist yet. The handoff (`docs/handoff/forensic-import.md`)
  lists no other open question.

## `EXCHEQUER_TELEGRAM_LOOKUPS`: a Telegram username's public page (feature 4, slice 4)

**What it turns on.** On the Evidence tab, an active Telegram username in the
identifiers panel gets "Read the public t.me page". The server fetches
`https://t.me/<username>` once: the preview anyone sees without Telegram. There
is no login, no API key, no redirect and no link followed, at most 256 kB within
15 s. It shows what that page shows (title, the type the page's words give,
count line, description, a verified/scam/fake badge) and keeps the body with its
SHA-256. Every result says a page is not an identity. It needs
`EXCHEQUER_OSINT_LOOKUPS` on too: `render.yaml` on `main` sets that to `1`, and
the OSINT handoff records it on in production since 13 Nov. Lookups are for
signed-in officers only, never the demo caller.

**Merged.** #162, with #169 and #170, on `main`. No migration (pages are kept in
`domain_lookups`, under its 50-lookups-per-identifier cap).

**Try it on the live site** (one test officer, on the test case):

1. Confirm in `/health/detail` that `EXCHEQUER_OSINT_LOOKUPS` and
   `EXCHEQUER_TELEGRAM_LOOKUPS` are both on.
2. Pick a well-known public channel that has nothing to do with any case. For
   example, Telegram's own channel `telegram` is a suggestion that was not checked
   here, so first open `https://t.me/telegram` in a normal browser to confirm it
   shows a channel. Note its title, type, count line, description and any badge.
3. Add that username as a Telegram identifier on the test case. Press "Read the
   public t.me page". Compare every field with step 2, check the not-an-identity
   line, and check the source (t.me, HTTP status, time, SHA-256).
4. Signed out (or in a private window), the button does not show.
5. A 4-character username is kept in the register but offered no lookup.
6. Audit row: `identifier.lookup` with `kind: telegram`, `page` and
   `shows_account` as yes/no. There must be no username and none of the page's words.
7. Withdraw the test identifier with the reason "TEST", as the domain-lookup
   live test did.

**Owner decisions still open** (#170, handoff `docs/handoff/osint.md`):

- **Read one public channel's page from the live site by hand first** (step 3
  above) and check the fields. #170 leaves the switch-on to Sidhyarth after that.
- The scam and fake badge markup was never seen on a live page. The parser
  looks for "scam" or "fake" in the title's class names, and the test page for
  it is an assumption, marked as such. Is that good enough to ship, or wait for a
  real example?
- Whether a lookup should go into the case report. Today, like domain lookups,
  it is shown on the Evidence tab only.
- With the flag off, the button goes, but earlier Telegram lookups are still
  listed with their identifiers (the list route and panel do not check the flag
  when showing a kept lookup).

## `EXCHEQUER_SOP_SUMMARY`: a crypto summary for CFCFRMS (feature 8)

**What it turns on.** On a stored case's Letters tab, a "Crypto summary for
CFCFRMS" panel. The officer answers "Is this exchange on CFCFRMS?" (yes, no or
not known), may type the NCRP number, and copies a plain-text summary in the
SOP's para 9.4 terms. The summary covers the exchange reached, its address and
how it was attributed, and the amounts and hashes, with the SOP paragraph
quoted for that answer. It contacts nothing outside Exchequer. The answer is
not stored. The NCRP number is filled in by the browser and never sent.

**Merged.** #218, with the server PR (#219) and the page PR (#220), on `main`. No migration.

**Try it on the live site** (one test officer, on the test case):

1. Confirm in `/health/detail` that `EXCHEQUER_SOP_SUMMARY` is on.
2. On the test case's Letters tab, open the panel. Pick each answer in turn
   and copy. "Yes" quotes SOP 9.4(ii), "No" quotes 9.4(iv), and "Not known"
   quotes both.
3. Check the exchange, address, label and hashes against the case report.
4. Type a test number such as `51234567890123`. The unusual-shape note shows.
   The copied text has the number; the server's requests do not (browser
   developer tools, Network).
5. Audit row: `case.sop_summary_copy` with only `{"on_cfcfrms": ...}`.
6. With the flag off, the panel does not show and both routes answer 404.

**Owner decisions still open** (handoff `docs/handoff/government-platforms.md`):
the legal check on SOP holds under s.168 read with s.94 BNSS versus
`notice_letters.py`'s Magistrate's-order rule (before any CFCFRMS notice
draft), and a partner cyber cell to confirm the layout is useful.

## `EXCHEQUER_SOP_DEADLINES`: SOP reminders on a bank hold (feature 8)

**What it turns on.** In the asset register on the Letters tab, a collapsed
list under a bank row that is still held: "SOP reminders, if this hold went
through CFCFRMS". Each reminder quotes the MHA SOP for NCRP-CFCFRMS word for
word, with its section, PDF page, source URL and copy date
(`backend/app/sop_reminders.py`). Only the Annexure I 90-day limit runs from a
date the register holds (the date seized); the rest are shown without a date.
They are reminders only: nothing is refused, blocked or reordered, and the
register's 45-day court deadline is unchanged. No reminder for exchange, issuer
or custody rows, or once a hold has ended. It contacts nothing outside Exchequer.

**Merged.** #230 on `main`. No migration. With the flag off, the register's
rows are unchanged.

**Try it on the live site** (one test officer, on the test case):

1. Confirm in `/health/detail` that `EXCHEQUER_SOP_DEADLINES` is on.
2. On the test case's Letters tab, add a TEST row held by a bank, status held,
   in the asset register. The reminders list shows under it, collapsed.
3. Check each quote, section and page against the SOP copy the handoff names
   (`docs/handoff/sop-deadlines.md`, with its SHA-256).
4. An exchange or issuer row shows no reminders. Change the TEST row's status
   from held (for example, to released): the reminders go.

**Owner decisions still open** (handoff `docs/handoff/sop-deadlines.md`): whether
to turn the flag on once the reviewer has checked the quotes against the PDF,
and a re-check of each quote if a newer official copy of the SOP is found.

## `EXCHEQUER_FREEZE_WORDING_V2`: bank-hold wording that rests on the order (feature 7)

**What it turns on.** A different wording for the urgent bank-hold notice
(`backend/app/notice_letters.py`). Off, the letter asks for "a debit freeze ...
up to the amount below", exactly as before. On, it asks the bank to "give
effect, now, to the attached order of the Magistrate ... as that order directs
and for no more than the amount below", with a bracketed suggestion of s.107
BNSS for the officer to confirm. Nothing else changes: the order is still
required, the provision is still a blank, the sign-off and its fingerprint are
the same. It contacts nothing outside Exchequer. No migration.

**Merged.** #252 (not yet).

**Try it on the live site** (one test officer, on the test case):

1. Confirm in `/health/detail` that `EXCHEQUER_FREEZE_WORDING_V2` is on.
2. On the test case's Letters tab, Notice to: Bank, Urgent hold. Without an
   order it is refused; with a TEST order it drafts the new wording.
3. With the flag off, the same details give the old wording.

**Owner decisions still open.** Switch it on only after a lawyer has answered
the questions in `docs/legal/freeze-wording-review.md`; the wording itself may
change with their answer.
