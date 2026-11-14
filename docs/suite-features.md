# The investigation suite: nine features

Exchequer is growing from a tracer into a suite for crypto-fraud cases. Tracing
(blockchain analytics) is what Exchequer already is. These are the nine features
the team agreed to add around it, in the team's own numbering. Talk about work in
these terms: "feature 7", "the letter generator".

"Build" means we write it. "Integrate" means we import another tool's output.
"Link" means we point to the tool from the case and record what it produced.
Status is what exists in this repository as of 2026-11-14.

| # | Feature | What it does | Build, integrate or link | Status in the repo |
|---|---|---|---|---|
| 1 | Attribution data | Who owns an address | Build the India label set; import public lists (sanctions, Tether freezes, public tags) | Live: 65.3 million flagged addresses in the label store (release `labels-2026-11-14`, #116), read by `label_store.py`, `label_rules.py`, `tron_tags.py`, `never_flag.py`, `risk_matcher.py`. Left: keep adding lists; no India exchange label set yet |
| 2 | Mobile and computer forensics | Phones and PCs, including wallet apps and seed phrases | Integrate: import Cellebrite, Magnet AXIOM, MSAB XRY, Oxygen or Autopsy exports; search them for addresses, hashes and seed words | Not started |
| 3 | Memory and disk tools | RAM capture, encrypted volumes, password recovery | Link from the case; record the hashes of what they produced | Live: the exhibit register on the Evidence tab (`exhibits.py`, #103) records each file by its hashes, checks a file against them in the browser, and keeps the chain of custody |
| 4 | OSINT | Handles, domains, phone numbers, app and site infrastructure | Build light lookups tied to the case (domain, Telegram handle); link to the rest | Live: case identifiers (`identifiers.py`, #105), domain lookup (`domain_lookup.py`, #106, flag `EXCHEQUER_OSINT_LOOKUPS`, on in production since #108), links across cases (#107); review fixes for #111 in #115 (domain lookups for signed-in officers only) |
| 5 | Telecom and bank analysis | CDR, IPDR, bank statements | Build an importer that joins bank and exchange records to the trace | Not started |
| 6 | Case management and evidence locker | Cases, tasks, deadlines, exhibits, chain of custody, audit trail | Build: the core of the suite | Partly there: `accounts.py`, `auth.py`, `audit.py`, `evidence.py` (hashes every provider response), `signing.py`, `pdf_verify.py`, `case_refs.py`, `batches.py`, `correlation.py`. Since 13 Nov also the exhibit register (`exhibits.py`, #103) and the asset register's court deadlines (`assets.py`, #101). Since 13 Nov the s.63(4) certificate draft too, filled from the exhibit register (`certificates.py`, #113; form on the Evidence tab, #114). No task list per case, and no certificate for Exchequer's own signed report, yet |
| 7 | Request and letter generator | Notices to exchanges, banks, telecoms; foreign letters of request | Build | Partly there: `request_letters.py` (letters to exchanges), `freeze_requests.py` (tracks what was sent and what came of it). Bank and telecom notices since #99 (`notice_letters.py`). No foreign letters of request yet |
| 8 | Government platforms | NCRP and 1930, CFCFRMS, Samanvaya, Sahyog, CCTNS | Link and import; we cannot write into them without an official integration | Partly there: NCRP numbers in complaints and case references (`complaints.py`, `case_refs.py`, `payment_intake.py`), and the citizen site's complaint intake. No imports from the other platforms |
| 9 | Custody wallet tooling | Government-controlled multisig wallets for seized crypto | Build the procedure and the records; never hold keys on our servers | Live: the asset register (`assets.py`, #101) records what was frozen or seized, who holds the keys (names only) and the 45-day court deadline, with a warning on the home page. No multisig procedure yet |

Background for each feature (what police use today, the legal powers involved,
and how an investigator moves through the suite) is in the team's report
"Exchequer Investigation Suite: tools, workflow and law". Ask your human for
the link.

When a feature is claimed, its handoff file in `docs/handoff/` names it by
number, and this table's status column is updated in the same pull request.
