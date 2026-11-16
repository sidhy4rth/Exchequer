# Switching on the flagged features

Seven features are built behind `config.py` flags, and all of them are now on
`main`, switched off (as of 2026-11-15): custody wallets (#129), statements and
call detail records (#146), the export scan (#147), Telegram lookups (#162),
the crypto summary for CFCFRMS (#218) and the SOP reminders on bank holds
(#230), each with the PRs merged with it. Every flag on `main` is listed first, below. Each flag is off until its environment variable
is `1` (`true`, `yes` and `on` also count; see `flag()` in `config.py`). This
file says, for each one: what it turns on, which PRs it came in, how
to switch it on and off, what to try on the live site before telling anyone,
and the decisions still open. One more, `EXCHEQUER_PRIVACY_CATEGORY`, is
already merged and was switched on in production on 15 Nov (last section).

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
| `EXCHEQUER_PRIVACY_CATEGORY` | #189: privacy protocols (Railgun, Aztec, Hinkal, Privacy Pools) shown on a trace as a note, never a risk hit or a stop | with #149 (#194, #195, #196, #198) | On: set in the Render dashboard on 15 Nov and in `render.yaml` since #232 (owner approved on 14 Nov) |
| `EXCHEQUER_CASE_BUNDLE` | Feature 6: one zip of a case's report, registers and audit trail, with a manifest | #187 (+#190) | Off in `render.yaml` |
| `EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT` | Trace engine: stop a `POST /trace` whose client hung up, at its next provider request | #227 (+#228) | On: set in the Render dashboard on 15 Nov and in `render.yaml` (owner approved on 15 Nov, after the flag-off Render-logs check; checked flag-on the same night; section below) |
| `EXCHEQUER_JOB_STOP_UNWATCHED` | #302: stop a background trace job no page has watched for 120 s after its last progress stream closed; nothing saved | #303 | Off in `render.yaml`; see its section below |
| `EXCHEQUER_STORE_EXCHANGE_ROWS` | #222: name the exchange from exchange rows in the label store (an exchange's own proof-of-reserves list; ADR-0011) | #223 (+#224) | Off in `render.yaml`; the store release `labels-2026-11-16` carries exchange rows (OKX 474,529 Tron; OKX Ethereum 162 own wallets and 4,938 deposit rows that state their basis, ADR-0012; Bitget 10 Ethereum). A sample suggests most of the OKX Tron rows are customer deposit addresses that sweep to OKX, yet they are still typed as OKX's own wallets, so it stays off until they are rebuilt as deposit and own-wallet rows (ADR-0012). Switching it on is its own PR, which also re-records demo 9 (five of its addresses are OKX rows) |
| `EXCHEQUER_CUSTODY_WALLETS` | Feature 9: custody wallet records and their signing log (never a key) | #129 (+#139, #140, #142) | Off in `render.yaml`; see its section below |
| `EXCHEQUER_CUSTODY_BALANCE_CHECK` | Feature 9 part 2: read each custody address's balance on chain against the asset register, with the provider evidence | #333 (+#344, #345; issue #332) | Off in `render.yaml`; see its section below |
| `EXCHEQUER_STATEMENT_IMPORT` | Feature 5: read a bank or exchange statement CSV against a case; save the rows the officer confirms | #146 (+#151, #152, #153, #183, #184) | Off in `render.yaml`; see its section below |
| `EXCHEQUER_CDR_IMPORT` | Feature 5: read a call detail record CSV against a case; save a summary the officer confirms | #168 (+#172, #173), merged with #146 | Off in `render.yaml`; see its section below |
| `EXCHEQUER_EXPORT_SCAN` | Feature 2: scan a phone or computer export in the browser for addresses, hashes and seed phrases | #147 (+#154, #155, #156, #164) | Off in `render.yaml`; see its section below |
| `EXCHEQUER_TELEGRAM_LOOKUPS` | Feature 4, OSINT slice 4: read a Telegram username's public t.me page (needs `EXCHEQUER_OSINT_LOOKUPS` too) | #162 (+#169, #170) | Off in `render.yaml`; see its section below |
| `EXCHEQUER_SOP_SUMMARY` | Feature 8: a copy-ready crypto summary of a case in the CFCFRMS SOP's 9.4 terms | #218 (+#219, #220) | Off in `render.yaml`; see its section below |
| `EXCHEQUER_SOP_DEADLINES` | Feature 8: the MHA CFCFRMS SOP's time limits, quoted, as reminders on bank holds in the asset register | #230 | Off in `render.yaml`; see its section below |
| `EXCHEQUER_SOP_STEPS` | Feature 8, #326: the CFCFRMS SOP's steps on a case's Letters tab, each quoted with its section and PDF page, beside what the case's own records show | #327 | Off in `render.yaml` |
| `EXCHEQUER_FREEZE_WORDING_V2` | Feature 7, #251: the bank-hold notice asks the bank to give effect to the Magistrate's order as it directs, not for a "debit freeze" | #252 | Off in `render.yaml`; awaits a lawyer; see its section below |
| `EXCHEQUER_FIU_IND_NOTE` | #290: FIU-IND's dated, sourced facts about the exchange (9 Mar 2026 registered list, notices, penalties) as a note on the report's FINDING and the exchange letters | #291 + #295 | On: set in the Render dashboard on 15 Nov and in `render.yaml` (owner approved on 15 Nov); see its section below |
| `EXCHEQUER_MORE_TASK_SUGGESTIONS` | Feature 6, #334: two more task suggestions, an exhibit handed over with no hash check since and unread alerts on the case's watches | #335 | Off in `render.yaml` |

That is all twenty-one flags in `FLAGS` on `main`.

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

## `EXCHEQUER_CUSTODY_BALANCE_CHECK`: custody balances on chain (feature 9, part 2)

**What it turns on.** A "Custody balances" panel on the Letters tab, under the
custody wallets. A signed-in officer presses "Check balances on chain now": for
each asset-register row still held in custody, the address it is held at (its
linked custody wallet, else its own held-at address and chain) is read through
that chain's provider (Etherscan, NodeReal or TronGrid; the daily allowance and
evidence log as for a trace), summed per address and asset, and shown as
"Matches the register", "Mismatch" (with both amounts and the gap in words) or
"Not checked" (with why). Each run is stored with the provider's evidence
(request without the key, SHA-256 of the answer, time). It moves no money.

**Try it** (test officer, test case, an address the unit itself controls): record
an asset-register row held in custody at that address, run the check, and compare
the panel's "On chain" figure with the explorer. Audit rows: `custody.balance.view`
and `custody.balance.check`, whose detail holds the check id and counts only.

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

## `EXCHEQUER_FIU_IND_NOTE`: FIU-IND's facts about the exchange (#290)

**What changes live.** When a trace's exchange is one of the 33 in
`backend/data/fiu_ind_status.json`, the report's FINDING gains a `FIU-IND :`
line and `FIU-IND source :` lines, and the exchange letters (request and urgent
freeze, and the instant-exchanger ones for ChangeNOW and FixedFloat) gain a
"FIU-IND NOTE (about the exchange, not any customer)" paragraph with its
sources, under the closure note if there is one. The note says whether the
exchange was on FIU-IND's list of registered VDA service providers as of
9 Mar 2026 (Lok Sabha USQ 5805, Annexure-I) and the notices, takedown
directions and penalties FIU-IND announced, each dated and in date order, each
clause naming its source, then the day Exchequer last checked the sources
(`_meta.checked_on`), e.g. "Kraken, in date order: on 28 Dec 2023 FIU-IND
announced a show-cause notice to it under section 13 of the PMLA and that it
had written to MeitY to block its URLs (PIB release 1991372); as of 9 Mar 2026
Kraken was not on FIU-IND's list of registered VDA service providers (Lok Sabha
USQ 5805, Annexure-I). Exchequer last checked the sources on 15 Nov 2026." When
nothing is older than the 9 Mar 2026 list, the note starts with the list, as
before ("OKX was not on FIU-IND's list ... as of 9 Mar 2026 ..."). Nothing else changes: not the attribution, the
labels, the addressee, the letter offers or what a letter asks. An exchange
with no entry gets no note. No migration; it contacts nothing outside Exchequer.

**Merged.** #291 and its stacked slice 2 (#295). With the flag off, every report and letter is byte
for byte what it was (`tests/test_fiu_ind_note_outputs.py`, from line 58).
A registered entry with no `listed_as` is skipped rather than printed as
"listed as None" (`tests/test_fiu_ind_status.py`).

**Checks after switching it on** (one test officer, on the test case):

1. Confirm in `/health/detail` that `EXCHEQUER_FIU_IND_NOTE` is on. The server
   restarts on the change, so no report kept from before is served.
2. Open the text report of a case that reached Binance (or any listed exchange):
   FINDING has the note and each source URL whole on its own line. Open the
   sources and check the dates and amounts against them.
3. Draft the request and urgent freeze letters for it: the note sits after the
   header, the letter is still addressed to the exchange.
4. A case that reached an exchange not in the file (for example FTX) shows no
   note anywhere.

**Switching it off.** Unset the variable and redeploy: the note goes from every
report and letter rendered after the restart. Reports already downloaded keep
it (they were signed with it).

**Owner decisions still open.** None on switching: the owner approved it on
15 Nov and it was set to `1` in the Render dashboard that day (deploy
`dep-dbsugv61egvs73eto9a0`) and in `render.yaml`. The registered list is
frozen at 9 Mar 2026 and FIU-IND publishes none (USQ 5805(f)): re-check the file
against the next Parliament answer or PIB release, and update `checked_on`.

**Re-checking the sources** (at least every 180 days, and whenever a new
Parliament answer, PIB release or FIU-IND order names a VDA service provider).
Every note prints "Exchequer last checked the sources on <checked_on>", so that
date must be true. `tests/test_fiu_ind_status.py::test_the_sources_were_checked_recently`
fails, saying what to do, once `checked_on` is more than 180 days
(`fiu_ind_status.STALE_AFTER_DAYS`) before the test's fixed `TODAY`. `TODAY`
never moves by itself, so CI does not start failing on its own: move it forward
when you re-check, or when you notice it is old.

The real date is checked by `backend/scripts/check_fiu_staleness.py`, which CI
runs after the backend tests on every pull request (`test.yml`) and every
Monday with no commit needed (`fiu-staleness.yml`, also runnable by hand from
the Actions tab). Once `checked_on` is more than 180 days old it prints
"WARNING: fiu_ind_status.json was last checked on ..., more than 180 days
before ...: re-check every entry ... (docs/flag-rollout.md,
EXCHEQUER_FIU_IND_NOTE), then update _meta.checked_on" and adds a warning
annotation to the run ("FIU-IND sources due a re-check"); it says the same if
the file is unusable. It always exits 0, so it never blocks a merge or turns a
run red: look for the annotation on the weekly run. When it appears, follow the
steps below.

A `checked_on`, `_meta.register.as_of` or fact date that is not a real day
(e.g. `2026-02-30`) is caught when the file is read: a bad `checked_on` or
`as_of` makes the file unusable (no note at all, error logged), as a missing
`checked_on` does, and a bad fact date skips that entry (warning logged).

1. Open every source the file cites (the URLs in its entries and in
   `_meta.register`) and check each entry's date, wording, source name and
   amount against it. A fact the source no longer supports is removed, not
   reworded.
2. Look for newer sources: Lok Sabha and Rajya Sabha answers on VDA service
   providers (sansad.in), PIB releases from the Ministry of Finance about
   FIU-IND, and FIU-IND's orders page (fiuindia.gov.in). Add only facts a
   source states, dated as `_meta.provenance` says, for exchanges the label
   files name (`_meta.rule`). A newer registered list replaces `_meta.register`
   (its date, source and URL) and every entry's `registered` and `listed_as`.
3. Record what you read in `_meta.provenance`, set `_meta.checked_on` to the
   day you finished, and update `TODAY` and the pinned dates in
   `tests/test_fiu_ind_status.py` and `tests/test_fiu_ind_note_outputs.py`.
4. Run the backend tests and open a PR that lists what changed per entry and
   the sources read. With the flag on, the new wording is live once merged.

## `EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT`: stop a trace whose client hung up (#227)

**What it turns on.** While a synchronous `POST /trace` runs, the server checks
every second whether the client is still connected. If it has hung up, the
trace stops at its next provider request, nothing is stored, and the audit log
gets `case.trace_abandoned` with `stopped_by: client_disconnected`,
`saved: false` (handoff `docs/handoff/trace-cancel-on-disconnect.md`). Background
jobs (`POST /trace/jobs`) and batches are not touched.

**Who it reaches.** Only a direct API caller of `POST /trace`. The web app
starts every trace as a background job (`runTrace` in
`frontend/src/api/trace.js`, `POST /trace/jobs`, called from
`routes/TraceView.jsx`); the app's `traceAddress`, the only caller of
`POST /trace`, is used by no page. So in the officer UI a closed tab does not
stop a trace: the job runs to the end and saves its case, with the flag on or
off. Of direct callers, the checks below show it works over HTTP/2 and does
nothing over HTTP/1.1 (HTTP/3 not tested).

**Merged.** #227 (with #228) on `main`. No migration. On in `render.yaml` since #296.

**The open question.** The flag only helps if a client's hang-up reaches
uvicorn through Render's chain: client → Cloudflare edge (Render's own account)
→ Render's load balancer → uvicorn. Neither Render nor Cloudflare documents
whether it does.

**What was measured** (15 Nov 2026, against https://exchequer.co.in, flag off;
the test does not depend on the flag). `GET /trace/jobs/{id}/events` allows 3
open progress streams per job (`MAX_STREAMS_PER_JOB` in `routes/jobs.py`); a 4th
gets 429. A stream's place is given back when the server sees its client gone
(`is_disconnected()`, polled every 0.3 s) or a write to it fails. So a 4th
stream turning from 429 to 200 shows from outside when the server saw a
hang-up. Each run started one background trace (`save: false`), kept stream A
open, opened B and C with `curl --max-time 5`, then retried a 4th stream D about
every 0.6 s; the job was stopped with DELETE at the end. Five runs; the first
three do not count, because the trace ended before or during the first round.
Times are seconds from the start of the run.

| Round | Hang-up | 4th stream | First progress write after the hang-up |
|---|---|---|---|
| run 4, HTTP/1.1 | 6.75 | 429 at 6.87, 7.52, 8.11, 8.72; admitted by about 9.2 | 9.05 |
| run 5, HTTP/1.1 #1 | 6.72 | 429 at 7 tries through 10.48; admitted 11.08 | 10.60 |
| run 5, HTTP/1.1 #2 | 30.07 | 429 at 8 tries through 34.42; admitted 35.03 | 34.64 |
| run 4, HTTP/2 | 18.77 | admitted at about 18.85 | 19.57 (after) |
| run 5, HTTP/2 #1 | 20.54 | admitted 20.61 | none from 17.51 to 22.01 |
| run 5, HTTP/2 #2 | 44.51 | admitted 44.60 | none from 41.24 to 46.65 |

- **HTTP/2:** the place was freed within about 0.1 s of the hang-up, with no
  write in between. (In the two run 5 rounds, a stale HTTP/1.1 stream from the
  round before held one of the 3 places, so only one test stream was open; the
  result rests on the windows with no writes.)
- **HTTP/1.1:** the place was freed only just after the next progress write,
  2.3–5.9 s after the hang-up, in all 3 rounds.

**What it implies (inferences, not measured).** Render's load balancer passes a
cancel on at once (the HTTP/2 rounds). The HTTP/1.1 delay looks like the
Cloudflare edge treating the client's close as a half-close and noticing only
when a write to the client fails. `POST /trace` writes nothing until the trace
ends, so:

- **Browsers and other HTTP/2 or HTTP/3 clients:** the flag is likely to work.
  (No page of the web app calls `POST /trace`, so this is about a protocol, not
  the officer UI; see "Who it reaches" above.)
  HTTP/3 was not tested; Cloudflare's 19 Jan 2026 changelog says it now ends
  cancelled HTTP/3 requests at once.
- **HTTP/1.1 scripts** (Python `urllib` and `requests`, `check_demos.py`, which
  uses `urllib`, `curl --http1.1`): the flag is likely to do nothing; the trace
  runs to the end as it does today. It does no harm either.

**What the probe did not measure.** The `POST /trace` phase itself, before any
byte is written (the probe saw only streams whose headers were already sent),
and whether the flag, once on, stops a trace. The owner-side checks below cover
both. Still not measured: HTTP/3, and any Cloudflare edge other than the one
these runs reached (`cf-ray` BLR).

**The owner-side check** (Render dashboard; flag stays off, nothing stored).
Run it twice, once with `--http1.1` and once with `--http2`, at least 3 minutes
apart. Not around 01:30 UTC (07:00 IST), when the Demo health Action runs, and
once each, not in a loop. Each run holds one trace slot for at most about 80 s.

```sh
cd ~/exchequer
BODY=$(python3 -c 'import json;d=json.load(open("backend/data/demo_expectations.json"))[0];print(json.dumps({k:d[k] for k in ("address","chain","asset","max_depth","direction")}|{"save":False,"time_budget_seconds":20}))')
curl -s https://exchequer.co.in/health; echo   # wake the instance first
date -u
curl -sS --http1.1 --max-time 3 -o /dev/null -w '%{http_code}\n' \
  -X POST https://exchequer.co.in/trace -H 'content-type: application/json' -d "$BODY"
echo "curl exit=$?"   # want 28 (timed out); a 200 means it was cached: retry with demo [1], [2] ...
```

For the second run, change `--http1.1` to `--http2`. Then open Render
dashboard → exchequer → Logs and search `POST /trace` from each `date -u` time.
`GET /health` lines from Render's health checker are the control (they prove
access logging is on). uvicorn 0.54.0 writes no access line for a request
whose client it saw leave before the response started (read in its code, not
tested here). The upstream leg is HTTP/1.1 in both runs, so the line always
reads `HTTP/1.1`.

- **A `"POST /trace HTTP/1.1" 200` line about 20–80 s after the hang-up:** the
  hang-up never reached uvicorn. Expected for the `--http1.1` run.
- **No such line:** it did. Expected for the `--http2` run.
- **The line in both runs:** the flag would do nothing in production. Keep it off.
- **No line in either run:** both protocols get through, and the HTTP/1.1 delay
  above is specific to a stream that has already started.

While the flag is off, the audit log cannot tell these apart: the trace
finishes and `case.trace` is recorded either way. Use the access line.

**Flag-off check: done, 15 Nov 2026, 17:05–17:11 UTC.** Three `POST /trace`
runs as above (demos 0 and 1, `save: false`, `time_budget_seconds: 20`), read
in Render → exchequer → Logs:

| Run | Client | `case.trace` (trace finished) | `"POST /trace HTTP/1.1" 200` line |
|---|---|---|---|
| `--http1.1`, demo 0 | hung up after 3 s, 0 bytes | 7 s after the hang-up | yes, 7 s after the hang-up: the hang-up never reached uvicorn |
| `--http2`, demo 0 (control) | 200 in 1.3 s (cached, no hang-up) | at once | yes (proves access logging is on) |
| `--http2`, demo 1 | hung up after 3 s, 0 bytes | 6 s after the hang-up | none: the hang-up reached uvicorn |

So for HTTP/2 (browsers) the hang-up reaches uvicorn before the first byte too,
and with the flag off the trace still ran to the end. For HTTP/1.1 clients the
flag can do nothing, and does no harm.

**Switched on, 15 Nov.** After that check the owner approved switching it on:
it was set to `1` in the Render dashboard (deploy `dep-dbsugv61egvs73eto9a0`,
17:16 UTC) and in `render.yaml`.

**Flag-on check: done, 15 Nov 2026, 17:18–17:20 UTC.** One `--http2` run with
demo 2 (not cached), same body and hang-up after 3 s (curl exit 28, 0 bytes).
Render logs: `case.trace_start` at 17:18:46, `case.trace_abandoned` at 17:18:51
(about 2 s after the hang-up), and **no `case.trace` and no `POST /trace` access
line** when checked again 95 s after the hang-up, past the trace's 20 s walk and
60 s post-walk cap. The trace stopped and nothing was saved:
`case.trace_abandoned` is written only on the path that raises 409 before the
result is stored. Its detail (`stopped_by: client_disconnected, saved: false`)
shows in the log only as a hash. `GET /health` kept answering 200.

**Switching it off.** The common steps above. Off, a hang-up changes nothing:
the trace runs to the end as before.

## `EXCHEQUER_JOB_STOP_UNWATCHED`: stop a background trace no page is watching (#302)

**Why.** A background trace (`POST /trace/jobs`, what the app uses) whose tab
was closed ran to the end and saved a case nobody saw: only the Stop button
(`DELETE /trace/jobs/{id}`) ended it, and the page sends that from nowhere
else. It held one of the 4 trace slots (`TRACE_MAX_RUNNING`) for up to about
4 minutes (180 s walk + 60 s after it) and its provider calls.
`EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT` does not cover it: that flag watches
only `POST /trace`, and a job is meant to outlive the request that started it.

**What it turns on** (`routes/jobs.py`). When a job's last progress stream
(`GET /trace/jobs/{id}/events`) closes, a clock starts. A new stream (a reload
re-attaches in about 2 s) keeps the job going, and a status poll
(`GET /trace/jobs/{id}`, the page's fallback, every 1.5 s) starts the clock
again. A job still unwatched after `JOB_UNWATCHED_GRACE_SECONDS` (120 s,
`config.py` trace-engine section; 120 rather than 30 so a phone that sleeps
or switches apps for a while keeps its trace, while a closed tab still frees
its slot well before a trace's ~4 minutes end) is stopped the way a Stop stops it: at its
next provider request or backoff. It stores no case (even if its trace returns
after the stop), frees its slot, ends as failed with 409 "The trace was stopped
because the client disconnected; nothing was saved.", and is audited as
`case.trace_abandoned` (`stopped_by: client_disconnected`, `saved: false`, the
same record a hung-up `POST /trace` gets), not `case.trace_stopped`.

- A job whose client never opened a stream (a script that only polls, or
  only waits) never starts the clock and runs as before.
- The hourly trace allowance is not given back, as for a Stop and a hung-up
  `POST /trace`: the trace was started and its provider calls spent, and a
  refund would let a client start and close traces to get round the limit.
- A phone that sleeps with the tab open drops its stream; after 120 s its
  trace stops, and on waking the page shows the 409, as after a Stop.
- Jobs live in one process's memory; the clock is a timer on its event loop.

**Pull request.** Merged in #303 (15 Nov, `039b917c`). No migration. Off in `render.yaml`.

**Checks after switching it on** (the common steps above; one trace each).

1. Start a trace in the app on a wallet busy enough to run past 2 minutes
   (a long time budget), wait until progress shows, then close the tab. In
   Render → exchequer → Logs, within about 125 s (120 s grace plus the next
   provider request) there should be
   `case.trace_abandoned`, and no `case.trace` for it afterwards. The case
   history shows no new case.
2. Start another, reload the page within a few seconds. It should re-attach,
   finish, and save a case (`case.trace` in the logs).
3. Start another and press Stop: `case.trace_stopped` as before, no
   `case.trace_abandoned`.
4. `GET /health` keeps answering 200; `/health/detail` → `flags` shows it on.

**Switching it off.** The common steps above. Off, a closed tab changes
nothing: the job runs to the end and saves its case, as before.

## `EXCHEQUER_PRIVACY_CATEGORY`: privacy protocols as a note (#189)

Unlike the flags above, this one is already merged: the whole stack (#194,
#195, #196, #198) reached `main` inside #149. The owner approved the category
on 14 Nov and said yes to switching it on; it was set to `1` in the Render
dashboard on 15 Nov, and the PR that adds it to `render.yaml` follows.

**What it changes on the live site.** Nothing is contacted that was not before:
the server only reads `backend/data/privacy_protocols*.json` (27 contracts of
Railgun, Aztec, Hinkal and Privacy Pools on Ethereum, BNB Chain, Polygon,
Arbitrum and Tron, each with its source; handoff
`docs/handoff/privacy-protocol-category.md`).

- **Privacy Pools moves from a mixer stop to a privacy note.** With the flag off
  its two Ethereum contracts are mixers from `threat_labels.json`: a risk hit,
  and the trail stops there. With it on, that mixer tag gives way to the privacy
  entry, the trace walks on, and the hit is gone from every risk count. Only the
  mixer tag gives way: a sanctions listing, a freeze or a theft tag on a privacy
  contract still stands, and then no note is shown for it.
- **The 27 contracts show as a grey note**, never the red alert: a dotted
  "privacy protocol on the route · a note, not an accusation" box under the risk
  alert (`PrivacyNotes.jsx`), a grey dotted halo on both maps, and a `privacy`
  role on the Entities card. It counts toward nothing.
- **The signed report gains a section** "PRIVACY PROTOCOLS ON THE PATH (A NOTE,
  NOT AN ACCUSATION)" after the screening, only when the case has a match (#198,
  on `main`); the JSON report gains `privacy_protocols` under the same rule, and
  PDF page 1 a grey block. With no match the report bytes are unchanged. Letters
  never mention privacy protocols.

**Switching it on.** The common steps above: set `EXCHEQUER_PRIVACY_CATEGORY` to
`1` in the Render dashboard and redeploy, then merge the `render.yaml` PR.

**Check it after switching on** (a test officer and the test case, as above):

1. `/health/detail` → `flags`: `EXCHEQUER_PRIVACY_CATEGORY` is on.
2. Open the recorded demos: they look exactly as before. No recorded demo passes
   a privacy contract (handoff, PR 1), so a change there is a bug.
3. As the test officer, trace the Privacy Pools ETH pool
   `0xf241d57c6debae225c0f2e6ea1529373c9a9c9fb` (Ethereum; in
   `privacy_protocols.json` and, as a mixer, in `threat_labels.json`). Before the
   switch it is a mixer risk hit; after it, the grey note says "the reported
   address itself", the red alert does not name it, and the trace carries on.
   This was not run for this doc; it is a busy contract, so watch the provider
   quota and stop if it runs long.
4. Download the signed report: the privacy section is there, and `/verify`
   still accepts the file.
5. No new audit event: the note is part of the trace's own output.

**Switching it off.** The common steps above. Off, a new trace treats Privacy
Pools as a mixer stop again and carries no notes. A case traced while the flag
was on keeps the notes stored in its result, and the case page still shows them
(`PrivacyNotes.jsx` does not read the flag) until it is traced again; its report
drops the privacy section, because `report.py` reads the flag when it writes one.
