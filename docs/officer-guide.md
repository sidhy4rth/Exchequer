# Exchequer: a guide for investigating officers

This guide is for the officer working a crypto-fraud case, not for developers.
It is organised by what you are trying to do. For each task it says where the
feature is in the app, the steps, what Exchequer records (and what it never
records), and the limits you should know before you rely on it.

Each section is marked:

- **Live**: on the site today.
- **Merged, switched off**: reviewed and merged, but its switch is off until
  the team has tried it on the live site and turns it on
  (`docs/flag-rollout.md`).
- **Coming: behind a switch until reviewed**: built and in review. Once merged
  it stays switched off until the team has tried it and turns it on.
- **Coming: in review**: built and in review, with no switch. It appears on
  the site once it is merged.

Status is as of 16 November 2026, when the site ran the code merged up to
#308 (build c9f723b); anything merged after it reaches the site with the
next deploy. A switch counts as on only where the site's settings
(`render.yaml`) turn it on. `docs/suite-features.md`
tracks status for the team.

## Rules that hold everywhere

- **Never type, paste or photograph a seed phrase or private key** into any
  field. Every free-text field refuses text shaped like one (twelve or more
  seed words in a row, a raw key, an extended private key).
- **An attribution names an exchange address, not a person.** Only the
  exchange can say which customer owns it, and only on a lawful request.
- **Every draft is a draft.** Letters, notices and certificates are filled with
  what the case holds and what you typed. You check them, fill the marked
  blanks, and sign them. Nothing Exchequer produces is "certified".
- **Who sees your records.** Registers (exhibits, identifiers, frozen funds and
  the rest) can be read by the browser that made them and by your unit.
  Another unit's records are never shown to you, not even as a count.
- **Mistakes are withdrawn, not deleted.** Registers keep every change in a
  dated history: who, when, what changed and why.
- **The audit trail records who did what, never what you typed.** It holds the
  action, the case and which fields changed. It never holds a note, an account
  number, a phone number, a handle, a reason or a seed phrase.
- **A recorded example is not a case.** The verified examples on the New trace
  page open without tracing. To draft letters or keep records, press **Trace
  live**: it traces the address again and stores it as a case.

## Contents

1. [Trace the money](#1-trace-the-money)
2. [Record evidence and keep its chain of custody](#2-record-evidence-and-keep-its-chain-of-custody)
3. [Draft notices and letters](#3-draft-notices-and-letters)
4. [Track tasks and deadlines](#4-track-tasks-and-deadlines)
5. [Check an export from a seized phone or computer](#5-check-an-export-from-a-seized-phone-or-computer)
6. [Import a bank statement or call records](#6-import-a-bank-statement-or-call-records)
7. [Look up a domain or Telegram username](#7-look-up-a-domain-or-telegram-username)
8. [Keep seized crypto in a multisig wallet](#8-keep-seized-crypto-in-a-multisig-wallet)
9. [Download the case bundle](#9-download-the-case-bundle)
10. [Work alongside NCRP and CFCFRMS](#10-work-alongside-ncrp-and-cfcfrms)

---

## 1. Trace the money

**Live.**

**Where:** **New trace** in the side menu. The case then opens with five tabs:
Flow, Timeline, Entities, Evidence and Letters. **Cases** lists your stored
cases; **Bulk intake** traces a CSV of complaints as one batch.

**Steps**

1. Paste the wallet the victim paid into (0x… on Ethereum-family chains,
   T… on Tron) and choose the chain and asset.
2. If the victim gave you payment hashes, open **Victim's payments** and paste
   them, one per line. Where tracing from a payment hash is switched off, the
   form says so and asks for the wallet instead.
3. Add the NCRP acknowledgement number if you have it. It is never put in
   links or logs. A number that is not the usual shape gets a note, never a
   refusal (section 10).
4. Choose how far to follow, and the direction: **where the money went**, or
   **Trace who paid in** to find the addresses that funded it.
5. Press **Start trace**. The Flow tab shows where the money went; the
   Evidence tab lists the route transfer by transfer, each with its hash and a
   link to the block explorer.
6. On the Evidence tab, **Re-read from a second provider** checks the cited
   transfers against another data source.
7. Under **Signed report**, download the report as PDF or text, or the graph
   file. Anyone can check a copy of the report on the **Verify a report** page.

**Who the report names as its issuer** (live, #240): a report downloaded now
names https://exchequer.co.in under "Issued by", and letters and certificate
drafts say to check the report at https://exchequer.co.in/verify. The signing
key is the same as before (fingerprint beginning `f9427acc`). A report
downloaded earlier names https://exchequer-6gnl.onrender.com and still checks
as genuine on the Verify page (#239).

**What it records:** the case, every provider response it read (each hashed,
listed in the report's evidence manifest), and the signed report.

**Limits**

- A match names the exchange address where the funds arrived, and how sure the
  trace is (a labelled deposit address, an inferred one, a wallet the exchange
  runs, or an explorer's tag). It does not name the account holder.
- A trace stops at a mixer. A privacy protocol is not a mixer stop (see
  "Privacy protocols on the route" below). It follows one asset, and one swap
  into USDT or USDC at a known router; other swaps and bridges end the trail.
- A trace reads each wallet's 200 newest transfers. For a very busy wallet the
  result can change from one hour to the next (the wallet example 3 used
  until 15 November, below).
- The walk follows the ten largest counterparties of each address, so money
  split into many small parts can be missed. The Evidence tab's **Scope and
  evidence** section says what was left out.
- Screening is only as complete as its lists. An address on no list is not
  thereby clean; a foreign sanctions listing is a lead, not a finding.

The full list is in the README's Limitations section and in every report.

### What the lists behind a match now hold

**Live** (merged 14 and 15 November):

- **India exchanges** (#135, #247): 175 wallets of WazirX, CoinDCX, CoinSwitch
  and Unocoin on Ethereum, Polygon, BNB Smart Chain, Arbitrum and Tron. Each
  comes from an explorer's public name tag or a wallet list the exchange
  published itself (CoinSwitch's posts, WazirX's proof-of-reserves page and
  CoinDCX's wallet list as the Internet Archive kept them, Unocoin's June 2023
  proof-of-reserves post), and each is listed with its source in
  `data/india_exchanges.json`. There is still no public source for ZebPay,
  Bitbns, Giottus, Mudrex or BuyUcoin wallets.
- **Exchange labels cleaned** (#212): token contracts and infrastructure
  addresses were removed, so a trace no longer "ends at an exchange" there.
  Accounts a firm holds at an exchange are labelled as that exchange's, and the
  letter names the firm as the account holder.
- **Closed and closing exchanges** (#213): 16 exchanges that have closed or
  announced a closing date, each with a cited source, read "(defunct)" or
  "(winding down)" on their labels. Letters to them change (section 3).
- **Lifted Tether freezes dropped** (#206): 28 Tron addresses Tether has since
  released no longer read "Frozen by Tether". A freeze is treated as lifted
  only when two public endpoints both say so.
- **Sanctions, mixers and forfeitures** (#149): 21 more OFAC addresses (from
  the SDN list of 13 November 2026), 93 Tron wallets under Israeli NBCTF orders
  in force (each re-checked on the NBCTF site's own records), wallets named in
  U.S. court forfeiture orders (each re-read in its notice), and 36 more mixer
  pools and entry points. Polygon and Arbitrum now have their own lists.
- **Tron exchange wallets from proof of reserves** (#221): 52 Tron wallets
  that Binance, Bybit, HTX and KuCoin published as their own reserves.
- **Exchange labels on contracts** (#234, with #238): 26 Ethereum exchange
  labels that sit on a proxy or forwarder contract now read as a contract
  wallet. What a trace concludes does not change.
- **The label store** (#261): release `labels-2026-11-15` screens **69,410,610
  flagged addresses** (69.4 million, up 993,748 on the day before), counted
  once per chain: an address flagged on two chains counts twice, so the store
  holds 68,527,888 distinct addresses. Nearly all
  the new rows are address-poisoning wallets from scans of Polygon, BNB Smart
  Chain and Tron; 40 are issuer freezes.
- **Bitget reserve wallets** (#258): 21 wallets Bitget lists on its own
  proof-of-reserves page (12 on Ethereum, 4 on BNB Smart Chain, 5 on Tron).
  Labels read "Bitget: Reserve Wallet N", or on Tron "Bitget: Reserves Wallet"
  with the month of the list. Each cites the Bitget list it came from.
- **Hot wallets held in a contract** (#268): three Ethereum contract wallets,
  Kraken 5, Coinbase 10 and Gemini 2, now carry a hot-wallet role, measured on
  chain from a sample of the addresses that pay into them (#254's rule).
  An unlabelled address that sent two or more transfers to one of them and
  nowhere else is now inferred as that exchange's deposit address, scored like
  any other inference. A match on one of the three reads "hot wallet held in a
  contract".

**Limits**

- Contract wallets that already carry a role from their source (an exchange,
  hot or cold wallet role, such as Gemini's cold wallet or OKX Reserve Wallet
  215) are treated the same way: a deposit into them can be inferred. A
  contract wallet with no role is matched only directly, and a deposit into it
  is not inferred. The 12 Ethereum Bitget wallets were measured and none met
  the rule (#270); on Arbitrum, Polygon and BNB Smart Chain none could be
  measured.
- A proof-of-reserves list does not say whether a wallet is a hot wallet or a
  customer's deposit address. These rows are the exchange's own wallets, so
  the letter asks for the accounts behind the listed transactions only.
- A freeze lifted after the last re-check (run by hand on 15 November; the
  nightly refresh is off until the team turns it on) still reads as frozen.
- 5 of the 16 closed exchanges rest only on exchange-listing sites, the
  weakest source. Check the source the letter cites before relying on it.
- A U.S. forfeiture order is filed as "seized": a foreign court's act, a lead
  for your case, not a finding in it.

### Privacy protocols on the route

**Live** (#232; switch `EXCHEQUER_PRIVACY_CATEGORY`, on since 15 November).

A trace that passes through Railgun, Aztec, Hinkal or Privacy Pools (27
contracts on 5 chains, each with its source) shows a grey note under the risk
alert: "a note, not an accusation". The trace is not stopped by it and it is not
counted as a risk hit. The maps mark the contract with a grey dotted ring, and
the signed report adds a section "PRIVACY PROTOCOLS ON THE PATH (A NOTE, NOT AN
ACCUSATION)" when the case has such a contract. Letters never mention it.

**Privacy Pools is no longer a mixer stop.** Before 15 November its two
Ethereum contracts read as mixers and a trace stopped there. Now they get the
note instead, and drop out of every risk count.

**Limits**

- Funds passing through a privacy protocol lose their visible link, so what
  leaves it is not shown on chain to be the same money.
- A pool that pays out to many addresses is treated like any such contract: it
  is read, but its payouts are not followed, and the scope notes say so. A
  shielded pool usually does, so the trail often goes no further there even
  though the privacy note did not stop it. The note says so (#279, live since
  15 November): "Being a privacy protocol did not stop the trace here, but its
  payouts were not followed: it is a contract that pays out to many addresses,
  so no single payout can be tied to these funds." A note on a contract whose
  payouts were followed still says "The trace did not stop here." The section's
  opening line, on screen, in the text report and on page 1 of the PDF, says
  being a privacy protocol never stops the trace, though the trace may not go
  past a contract that pays out to, or is paid by, many addresses (#288). In a
  reverse trace, the note on such a contract says its senders were not
  followed back. PDFs issued with an earlier opening line still verify.
- A note is written when the trace runs. A case traced before #279 went live
  keeps the old wording, "The trace did not stop here", even where the
  payouts were not followed; run the trace again for the new wording.
- A government listing, freeze or theft tag on such a contract still stands as
  a risk hit, and then no note is shown for it.

### Bybit and OKX wallets; OKX's full list

**Live** (#226): Bybit's wallets on Ethereum (125), BNB Smart
Chain (31), Polygon (13) and Arbitrum (24), and OKX's on Polygon (95) and
Arbitrum (119), from each exchange's own proof-of-reserves file. Labels read
"Bybit: Reserve Wallet N" or "OKX: Reserve Wallet N". An address another list
already claims is left out, never overwritten. Since #248, also the two
Ethereum wallets OKX sweeps USDT and USDC into, from the same proof-of-reserves
file; their role rests on on-chain reads, which each label records. Since
#304 and #308, also 15 of OKX's own Tron wallets ("OKX: Reserve Wallet 264"
to "278"), from OKX's proof-of-reserves file, each with the on-chain reads
that show it is one of OKX's operating wallets.

**Merged, switched off** (#223, with #224; switch
`EXCHEQUER_STORE_EXCHANGE_ROWS`): OKX lists far more wallets (474,530 on Tron,
17,046 on Ethereum) than the label files can carry, so they go into the label
store. A match from the store says what it rests on (its attribution basis).
The live store, `labels-2026-11-16` (70,895,553 labels counted once per
chain; 69,973,340 distinct addresses), carries these rows: 474,529 OKX on
Tron; on Ethereum, 162 OKX own wallets, 4,938 OKX deposit addresses that each
state the OKX wallet it swept to, and 10 Bitget wallets. They name no
exchange while the switch is off.

### Stopping a trace

**Live:** a trace that runs in the background shows **Stop this trace** while
it runs. A stopped trace is never saved, even if its last reads come back
after you stopped it (#228). Trace again if you still need it.

**Closing the page does not stop a trace.** A trace you start in the app runs
in the background, and keeps running on the server if you close its tab or
leave the page: it finishes and is saved as a case, as if you had stayed, and
it counts toward the traces you may start in an hour. Reloading the page in
the same tab while it runs picks the same trace up again rather than starting
a second one. To stop a trace, press **Stop this trace**.

The switch `EXCHEQUER_TRACE_CANCEL_ON_DISCONNECT` (#227, on since
15 November, #296) does not change this. It covers only a trace asked for
directly over the API, by a program that waits for the whole answer in one
request: if that program hangs up over HTTP/2, the trace stops and nothing is
saved (tested on the live site on 15 November). A hang-up over HTTP/1.1 does
not reach the server, so that trace runs to the end. The app never traces in
one request.

### Verified example 3: a deposit address behind an intermediary

**Live** (#286). Since 15 November, example 3 is a different wallet:
`0x0067b43c…` (Ethereum, ETH, 3 hops), a wallet Etherscan labels as a
reported phishing wallet. It reaches a **probable HitBTC deposit address
(inferred)**, `0x4a126587…`, through one intermediary, at **0.67, moderate**,
and pro-rata counts about 0.74 of the 1.0626 ETH that left the wallet on that
path as the reported funds. Its recording is from the same day (15 November,
21:14 IST). The wallet and the intermediary have been quiet since November
2021, so a trace reads their whole history, and the answer is expected to stay
the same. HitBTC still operated on
15 November and the letters go to HitBTC itself.

The wallet example 3 used before (`0x536c4921…`, still example 4) now makes
about 700 to 800 transactions a day, so the 200 newest no longer reach the
transfers earlier traces followed, and on 15 November it reached no exchange
within 3 hops. No rule changed. `DEMO.md` keeps its history.

---

## 2. Record evidence and keep its chain of custody

**Live.**

**Where:** the case's **Evidence** tab, the **Exhibits** panel ("forensic
files, by their hashes"), and under it **Draft the s.63(4) certificate**.

**Steps: record a file**

1. Press **Record a forensic file**. Choose the kind (phone extraction, disk
   image, memory capture, tool report, video, document, other).
2. Enter what it is, the tool and version, the date made, who made it, who
   holds it and where it is kept.
3. Enter the SHA-256 the tool printed (SHA-1 and MD5 too, if the tool gave
   them), or use **Fill the SHA-256 from the file**: the browser computes the
   hash on your computer. The file is never uploaded; only the hashes are sent.
4. Press **Add to the exhibits**.

**Steps: custody and checks**

- **Hand over**: record to whom, when and why. Each hand-over is added to the
  exhibit's history; nothing is overwritten.
- **Check a file against this exhibit**: pick the file and the browser hashes
  it and says whether it matches the recorded SHA-256. A large disk image
  takes time (about 20 minutes for 64 GB).
- **Release or destroy** ends the exhibit's custody, with a reason.
  **Add a note** records something like "seal checked, intact".

**Steps: the s.63(4) certificate**

1. Press **Draft the s.63(4) certificate** and choose what it covers:
   **Forensic files from the register**, or **Exchequer's report of this
   case**.
2. For files, tick the exhibits and describe the source device for Part A.
   For the report, pick the report file you downloaded: it must be a genuine,
   unchanged report of this case, checked the way the Verify page checks it.
3. Press **Download the draft (PDF)**.

The wording is the certificate in the Schedule of the Bharatiya Sakshya
Adhiniyam, 2023 (s.63(4)(c)), copied by script from the official text on India
Code. Part A is filled from the register and what you typed; **Part B is left
blank for the expert**, who fills it from their own check. Names, date, time
and place are written by hand when signing.

**What it records:** each exhibit with its hashes and a dated history of every
hand-over, check and note. The device details you type for a certificate go
into the PDF and are kept nowhere.

**Limits**

- The register records the hash you give it. It proves a file is unchanged
  since that hash was recorded, not that the extraction was done properly.
- The certificate is a draft until it is signed. It is not valid on its own.

---

## 3. Draft notices and letters

**Where:** the case's **Letters** tab. Freeze requests and the requests log
need a stored case.

### Letters to an exchange, Tether or an instant exchanger

**Live.**

**Steps**

1. Open the Letters tab. Exchequer offers the letters the case supports:
   urgent freeze letters first, then information requests, to the exchange,
   to Tether (where USDT is involved), or to an instant exchanger.
2. Read the draft. **Checked for you** lists what Exchequer checked against the
   case; **For you to fill** lists every blank: who is writing, the FIR or
   complaint reference, the victim's payments, the legal provision and the
   exchange's law-enforcement channel. The provision is left blank with a
   bracketed suggestion for you to confirm or replace.
3. **PDF** prints the letter or saves it as a PDF; **Copy text** copies it.
4. An **urgent freeze letter** needs a second officer: press **Ask for
   sign-off**, and another signed-in officer or supervisor of your unit
   presses **Sign off**. You cannot sign off your own letter. Until then it
   cannot be marked as sent.
5. After sending it by the exchange's own channel, press **Mark as sent**. It
   then appears in **Freeze requests** below, and on the **Requests** page,
   where you record what came back: acknowledged, frozen (with the amount),
   declined or closed. A sent request with no reply is flagged for follow-up
   after 7 days.

**What the letter asks** depends on what the case holds about the address: the
customer behind a labelled deposit address; whether an inferred address is the
exchange's, then the customer; for a wallet the exchange runs itself, the
accounts behind the listed transactions only; for an explorer's tag, only
whether the address is theirs. Where the address is a firm's account at the
exchange, the letter names that firm as the account holder.

**A closed or closing exchange** (live, #213): for an exchange that has closed,
the letter is addressed to "The administrator, liquidator or successor of" the
exchange, with a blank for you to identify who now holds its records. Its note
says the exchange "cannot answer this letter itself", gives the source, and
says: "If no one does, do not send it." For an exchange that is closing, the
note gives its closing date and asks you to send the letter before then and
confirm the channel still answers.

**The FIU-IND note** (live since 15 November, #291 and #295; switch
`EXCHEQUER_FIU_IND_NOTE`): for 33 exchanges, the request and urgent freeze
letters (and an instant exchanger's) carry a paragraph headed "FIU-IND NOTE
(about the exchange, not any customer)" with a "Sources:" line, and the signed
report's FINDING carries the same note. It says whether the exchange was on
FIU-IND's list of registered VDA service providers as of 9 March 2026 (Lok
Sabha USQ 5805, Annexure-I) and the notices, takedown directions and penalties
FIU-IND announced, each with its date and source. It is a dated, sourced fact
about the exchange, never about any customer or the account holder, and it
draws no conclusion: it does not say the exchange is unregistered today or
acting unlawfully. Nothing else changes: the letter is still addressed to the
exchange and asks the same thing. An exchange with no entry gets no note.
FIU-IND does not publish its register, so the 9 March 2026 list (given in
Parliament) is the latest Exchequer has; open the sources before you rely on
it. The note is in the signed text report and in these letters; the trace
screens, the PDF report's first page and a letter of request do not carry it.

### Notices to a bank or a phone company

**Live.**

**Steps**

1. On the Letters tab, under **Notice to**, choose **Bank** or **Phone
   company**.
2. Bank: choose **Information** (who holds the account, its statement for a
   period, what is linked to it, login records) or **Urgent hold**. Enter the
   bank, account number, IFSC and where you got them. A hold needs the
   Magistrate's order (number, date, court); the draft is refused without it.
   Courts differ on whether police may direct a bank to hold money without a
   Magistrate's order; follow your unit's legal advice.
3. Phone company: the operator, the number, where you got it, and the period.
4. Press **Draft the letter**. Changing a detail asks for a fresh draft. An
   urgent hold needs a second officer's sign-off, as above.

**What it records:** which notice was drafted, and the request once you log
it. The account number, IFSC and phone number go into the letter and nowhere
else: not the URL, not the audit trail, not the store.

**A hold's sign-off covers the exact details approved** (live, #133). The
second officer's sign-off is tied to the details the letter prints: bank,
account, IFSC, amount, source and the Magistrate's order. The **Second
officer** card shows the fingerprint it covers ("Approved for the details with
fingerprint … only"). Typing differences the letter erases (spaces in the
account, a lower-case IFSC, "2,50,000" for 250000) still match; any printed
difference needs a fresh sign-off. A signed-off hold is marked as sent from
the Letters tab, with its details, not from the Requests page. A hold signed
off before this change shows as still awaiting approval: close that request
and ask again.

Only the fingerprint is kept with the request. The audit trail records the
request, never the account number or any part of the fingerprint.

### A letter of request to a foreign country

**Live** (#126, with #127, #130, #136 and #158; it has no switch).

When the exchange holding the money is abroad and will not answer a notice,
its records can come only through a letter of request: a Criminal Court issues
it on the investigating officer's application, and the Central Government
transmits it.

**Where:** the Letters tab, a **Letter of request abroad** card under the frozen
and seized funds. It shows only when the case supports a letter to an exchange
or instant exchanger.

**Steps**

1. Fill the form: the basis (a treaty or convention, or an assurance of
   reciprocity; Exchequer never chooses it for you), the treaty if any, the
   requested country, the Court and presiding officer, the FIR, your agency,
   the offences, limitation, what happened, the exchange's registered office,
   urgency and the liaison officer.
2. Press **Draft the letter of request**, then read, download (.txt) or copy
   it. Nothing you type is kept.
3. **Log it in the requests log** to track it (drafted, sent, acknowledged,
   declined, closed). A sent letter of request is flagged for follow-up after
   30 days, an internal reminder the team chose, not a legal or MHA deadline.

**What the draft holds:** the sections and order of the MHA's format
(Guidelines, F. No. 25016/52/2019-LC, 4 December 2019, Figure 3.5), the MHA's
fixed wording, and the facts of the case: the payments, each hop, the claim
about the exchange address, and any request already sent to that exchange.
Notes for you come first, marked to be removed: the MHA's route, the checklist
of what goes with the draft, and whether the MHA's 2019 list of treaty
countries names the country you typed.

**Limits**

- It is not a letter of request until the Court issues it under its seal.
- The guidelines name CrPC s.166A as the power; its successor is BNSS s.112.
  The draft says so and asks you to confirm the provision with the Director of
  Prosecution.
- No offence or treaty is suggested. The treaty list is the MHA's as of 4
  December 2019 and may have changed: confirm with the MHA (IS-II Division).

---

## 4. Track tasks and deadlines

### Court deadlines and follow-ups

**Live.**

- **Court deadlines** on the Console (home page) lists frozen or seized funds
  whose court order on custody falls due this week (see section 8). The
  deadline is 45 days from seizure, as the asset register explains (BNSS
  s.497, as the Karnataka High Court has read it).
- **Requests** (side menu) and each case's **Freeze requests** panel show
  requests waiting for a reply and flag those sent 7 or more days ago.

### A task list per case

**Live** (#122, with #123 and #124).

**Where:** the Evidence tab, a **Tasks** panel first among the registers, and a
**Tasks due** card on the Console under the court deadlines.

**Steps**

1. **Add a task**: a title, who it is assigned to (a name), an optional due
   date and notes.
2. **Mark done** takes one click. **Drop…** and **Open again…** ask why.
3. **Suggested from this case's records**: Exchequer suggests tasks from what
   the case already says: follow up a request with no reply, get a second
   officer's sign-off, send an approved freeze letter, record funds an
   exchange froze in the asset register, and get the court's order on custody
   of held funds (due on the register's own deadline). **Add as a task** takes
   it; **Not needed…** declines it with a reason, so it does not come back.

**What it records:** each task with a dated history of every change. The audit
trail records which fields changed and the new status, never the text.

**Limits:** suggestions come only from the records you can read. A task nobody
recorded will not be suggested. Tasks go into the case bundle (#244), which is
still switched off (section 9).

### SOP reminders on a bank hold

**Merged, switched off** (#230). See section 10.

---

## 5. Check an export from a seized phone or computer

**Merged, switched off** (#147, with #154, #155, #156 and #164; switch
`EXCHEQUER_EXPORT_SCAN`). Adding a wallet address by hand under **Reported
identifiers** (section 7) has no switch and is live.

**Where:** the Evidence tab, an **Export scan** panel ("addresses, hashes and
seed phrases in a phone or computer export").

**Steps**

1. Export the extraction from your forensic tool as text (CSV, TSV, XML, JSON,
   HTML or plain text). A binary file is detected and you are asked for a text
   export instead.
2. Pick the file. It is read on your computer, with progress and a **Stop**
   button. Nothing in it is sent.
3. Read the results:
   - **Possible seed phrases**: shown as, for example, "12 BIP-39 words at line
     40, hidden". The words are never shown or kept. Whoever holds them
     controls the wallet: secure the device and follow your procedure for
     seized wallets.
   - **Addresses**: each with its chain family and line numbers, a **Trace**
     link, and **Add as case identifier**.
   - **Transaction hashes**: with **Trace from this payment**.

**What it records:** only that a scan ran, with counts (lines, size, addresses,
hashes, seed-phrase runs). Never a value, a word or the file name. An address
you add as an identifier is recorded on the case; the audit trail holds its
kind, not the address.

**Limits**

- An Ethereum-style address is the same on every EVM chain; the address alone
  does not say which chain was used.
- A 64-character hash without 0x may be a Tron transaction or any SHA-256 (a
  file hash, for example).
- Seed-phrase detection looks for twelve or more list words in a row. A phrase
  split up or written differently may be missed.

---

## 6. Import a bank statement or call records

**Merged, switched off** (#146 stack). Statements: #146, #151, #152, #153,
switch `EXCHEQUER_STATEMENT_IMPORT`. Call detail records: #168, #172, #173,
switch `EXCHEQUER_CDR_IMPORT`. Withdrawing an import: #183, #184, under the
same two switches.

### Bank or exchange statement

**Where:** the Evidence tab, **Bank and exchange statements** ("rows lined up
with the trace").

**Steps**

1. Choose bank or exchange and the currency, then pick the statement as a CSV.
   It is read in your browser.
2. Check the columns Exchequer guessed (date, narration, reference, debit,
   credit and so on), and add the rupee amounts the complaint reports.
3. Exchequer shows the rows worth a look and why: same amount within 2 days of
   a payment, a UTR or RRN, a narration naming a known exchange, or a hash that
   appears in the trace. A timeline puts them beside the trace.
4. Untick any row you do not want, and **Save**. Only the ticked rows are sent.

### Call detail records

**Where:** the Evidence tab, **Call detail records** ("contacts and handsets,
read in this browser").

**Steps**

1. Pick the CDR as a CSV (save an XLSX as CSV first) and check the columns.
2. Read the summary: the CDR's own number, top contacts by calls and SMS or by
   call time, handsets (IMEI) and SIMs (IMSI) and how often they changed, and
   the most used first cells. Numbers already on this case's phone identifiers
   are marked.
3. Tick numbers to check against your other cases: only the ticked numbers are
   sent, and only cases you can already read are searched.
4. Tick the contacts and handsets to keep and save the summary. The CDR's rows
   are never sent.

**Withdraw an import entered by mistake:** **Withdraw…** with a reason. It is
kept, marked withdrawn with who, when and why, and hidden unless you choose
**Show withdrawn**.

**What it records:** only the rows or summary you ticked. The audit trail holds
counts only: never an account number, reference, narration, phone number or
IMEI.

**Limits**

- A matched row is a lead for a notice to the bank or exchange, not a finding.
- A phone number is a lead, not a person: subscriber details come from the
  operator under a lawful request.
- No exchange rates are used: a payment matches a statement row only in the
  same currency.

---

## 7. Look up a domain or Telegram username

### Reported identifiers and domain lookups

**Live.**

**Where:** the Evidence tab, **Reported identifiers** ("sites, usernames,
phones, UPI IDs").

**Steps**

1. **Add a reported identifier**: a scam site's domain, a Telegram username, a
   phone number, a UPI ID or a wallet address the victim reported (0x… on
   Ethereum-family chains, T… on Tron; the chain is not stored, since an
   Ethereum-style address is the same on every EVM chain). It is kept as typed and in a
   standard form, so the same one matches across cases.
2. **Also in N other cases** shows where the same identifier was reported in
   other cases you can read, with links to them.
3. For a domain, **Look up public records** (signed-in officers only) shows the
   registrar, when it was registered and its age when looked up, the abuse
   contact, name servers, where it points, and every source with its SHA-256.
4. **Withdraw** a wrong entry with a reason; **Add a note** at any time.

**What it records:** each identifier with its history, and each lookup's raw
responses as evidence (kept with the case, not shown). The audit trail holds
the kind of identifier, never its value.

**Limits**

- Lookups read only public records: IANA's registry list, the registry it
  names, and a public DNS resolver. Registrant details are not shown; they are
  usually redacted, and only the registrar can name its customer.
- A domain's age is its age when looked up, not before the case.

### Telegram usernames

**Merged, switched off** (#162, with #169 and #170; switch
`EXCHEQUER_TELEGRAM_LOOKUPS`, which also needs domain lookups on).

**Where:** on an active Telegram username in **Reported identifiers**, **Read
the public t.me page** (signed-in officers only).

**What it shows:** what the public t.me page showed when read: the title, any
verified, scam or fake badge, what kind of account the page says it is
(channel, group, bot or a user's own account, or "The page does not say"), the
count line, the description, and the kept response with its time and SHA-256.

**Limits**

- It reads one public page anyone can see without logging in. No Telegram
  login, API or messages are used, and no link on the page is followed.
- A page is not an identity: anyone can name an account anything, and only
  Telegram can say who runs it.
- Usernames shorter than 5 characters have no t.me page and are refused.

---

## 8. Keep seized crypto in a multisig wallet

### Frozen and seized funds

**Live.**

**Where:** the Letters tab, **Frozen and seized**, under the freeze requests.

**Steps**

1. **Record frozen or seized funds**, or add one in a click from a request
   marked Frozen. Say where it is held (the unit's custody wallet, an exchange,
   a bank, or frozen by the token's issuer), the asset and exact amount, the
   seizure date, who holds the keys (names only), and for custody the
   transaction into it.
2. Record the court's order when it comes, and the outcome (released to the
   victim, returned to its owner, confiscated or sold) with its transaction or
   order.

**What it records:** each amount as exact text (never rounded), with a dated
history. Never a key or seed phrase.

### Custody wallets and the signing log

**Merged, switched off** (#129, with #139, #140 and #142; switch
`EXCHEQUER_CUSTODY_WALLETS`).

**Where:** the Letters tab, **Custody wallets**, directly under the frozen and
seized funds. The step-by-step checklist is `docs/custody-procedure.md`.

**Steps**

1. **Record a custody wallet**: the chain, the multisig address, the scheme,
   the threshold (m of n, at least 2), each signer by name, role and unit,
   whether a proposer may also sign, who set it up and when. Link the asset
   register rows moved into it.
2. **Propose a deposit or release**. A release needs the destination and the
   court order reference before anyone signs.
3. Each signer approves on their own hardware wallet, then the approval is
   recorded. Each signer counts once; the proposer counts only if the scheme
   allows it.
4. Once the threshold is reached, broadcast, record the transaction hash, and
   mark it confirmed on chain. Or **Cancel** with a reason.

**What it records:** the wallet, every movement and who approved it. Never a
key, seed phrase or signature: signing happens on the hardware wallets, and
every field refuses secret-shaped text. The audit trail holds ids, steps and
counts, never names, order references or reasons.

**Limits:** Exchequer keeps the record. It does not hold, sign or move funds,
and it cannot see a device's screen: each signer checks the amount and
destination on their own device. The procedure is a working checklist, not
legal advice; follow the court's order and your unit's instructions.

---

## 9. Download the case bundle

**Merged, switched off** (#187, with #190, and #244; switch `EXCHEQUER_CASE_BUNDLE`).

Until then, download the signed report from the Evidence tab (section 1).

**Where:** the Evidence tab, **Case bundle**, beside the PDF, Text and Graph
file buttons of the signed report.

**What is in it:** one zip with the signed report (text and PDF, exactly as the
report download gives them), the exhibits, frozen and seized funds, requests
and identifiers registers, each with its history, the task list (#244), and,
where their switches are on, the custody wallets and signing log, the statement
rows and the CDR summaries (#244), the case's audit trail, and
`MANIFEST.txt`. The manifest lists each file's size and SHA-256, who downloaded
it and when, and how to check the report on the Verify page.

**Who can download it:** the browser or unit that traced the case. Anyone else
holding the link is refused.

**Limits**

- The hashes show the files are unchanged since download. They say nothing
  about whether the records are right.
- The manifest itself is not signed; the report is.
- Certificate drafts are not included: they are drafts you complete.
- Not yet in it: letters of request.

---

## 10. Work alongside NCRP and CFCFRMS

Exchequer has no access to NCRP, the 1930 helpline or CFCFRMS, and contacts
none of them. These features help you prepare what you enter there yourself.
The quotes come from the MHA's "SOP for NCRP-CFCFRMS, Custody, Restoration of
Money & Grievance Redressal", read in a copy a bank publishes; the source is
linked from each screen.

### A note on an unusual NCRP number

**Live** (#218).

On New trace, the officers' complaint page and the citizen site, a number
that is not the usual shape gets a note: "NCRP acknowledgement numbers are
usually 14 digits starting with 2 or 3 — check the number." (SOP 6.1(d) and
6.2(c): 2 for the portal, 3 for the 1930 helpline.) It is a note only: no
number is refused or changed, since older complaints or other channels may use
other formats.

### A crypto summary for CFCFRMS

**Merged, switched off** (#218, with #219 and #220; switch
`EXCHEQUER_SOP_SUMMARY`).

**Where:** a stored case's Letters tab, **Crypto summary for CFCFRMS**.

**Steps**

1. Answer "Is this exchange on CFCFRMS?": yes, no or not known.
2. Type the NCRP acknowledgement number if you want it in the text (optional).
3. Press **Copy the summary**, and enter or attach it on CFCFRMS yourself.

**What it holds:** the exchange the trace reached, its address and how it was
attributed, and the amounts and hashes, in the words of SOP para 9.4. "Yes"
quotes 9.4(ii) (an onboarded exchange), "No" quotes 9.4(iv) (an exchange not
onboarded), and "Not known" quotes both.

**What it records:** one audit row with your answer (yes, no or not known)
and nothing else. The answer is not stored with the case. The NCRP number is
filled in by your browser and never sent to the server.

**Limits**

- It is not a CFCFRMS export and gives no legal advice. It never says that a
  provision applies.
- Exchequer holds no list of exchanges onboarded on CFCFRMS: the answer is
  yours.

### SOP reminders on a bank hold

**Merged, switched off** (#230; switch
`EXCHEQUER_SOP_DEADLINES`).

**Where:** the Letters tab, **Frozen and seized**: under a bank row that is
still held, a folded list "SOP reminders, if this hold went through CFCFRMS".

**What it shows:** five time limits from the SOP, each quoted word for word
with its section, PDF page and a link to the source. Only the Annexure I
90-day limit runs from a date the register holds (the date seized), so only it
shows a date.

**What it records:** nothing new. It adds no field to the register.

**Limits**

- Reminders only: the screen says "Not a deadline Exchequer enforces". Nothing
  is refused or reordered, and the register's 45-day court deadline is
  unchanged.
- Bank holds only: the SOP sets no time limit for exchange or issuer holds.
- The register does not record whether a hold went through CFCFRMS, so the
  reminders show on every bank hold still held.
- Courts cite other versions of the SOP (02.01.2026, 10.04.2026). Check a
  quote against the version your unit follows.

---

## Not covered here

Features not yet built or not described above: imports from government
platforms (NCRP, CFCFRMS and others: Exchequer has no access to them), and
IPDR. See `docs/suite-features.md`.
