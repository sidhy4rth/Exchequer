# The investigation suite: nine features

Exchequer is growing from a tracer into a suite for crypto-fraud cases. Tracing
(blockchain analytics) is what Exchequer already is. These are the nine features
the team agreed to add around it, in the team's own numbering. Talk about work in
these terms: "feature 7", "the letter generator".

"Build" means we write it. "Integrate" means we import another tool's output.
"Link" means we point to the tool from the case and record what it produced.
Status is what exists in this repository as of 2026-11-12.

| # | Feature | What it does | Build, integrate or link | Status in the repo |
|---|---|---|---|---|
| 1 | Attribution data | Who owns an address | Build the India label set; import public lists (sanctions, Tether freezes, public tags) | Partly there: `label_store.py`, `label_rules.py`, `tron_tags.py`, `never_flag.py`, `risk_matcher.py`. Label store in parts is PR #91 (Sidhyarth). No India exchange label set yet |
| 2 | Mobile and computer forensics | Phones and PCs, including wallet apps and seed phrases | Integrate: import Cellebrite, Magnet AXIOM, MSAB XRY, Oxygen or Autopsy exports; search them for addresses, hashes and seed words | Not started |
| 3 | Memory and disk tools | RAM capture, encrypted volumes, password recovery | Link from the case; record the hashes of what they produced | Not started |
| 4 | OSINT | Handles, domains, phone numbers, app and site infrastructure | Build light lookups tied to the case (domain, Telegram handle); link to the rest | Not started |
| 5 | Telecom and bank analysis | CDR, IPDR, bank statements | Build an importer that joins bank and exchange records to the trace | Not started |
| 6 | Case management and evidence locker | Cases, tasks, deadlines, exhibits, chain of custody, audit trail | Build: the core of the suite | Partly there: `accounts.py`, `auth.py`, `audit.py`, `evidence.py` (hashes every provider response), `signing.py`, `pdf_verify.py`, `case_refs.py`, `batches.py`, `correlation.py`. No exhibits from outside the trace, tasks or deadlines yet |
| 7 | Request and letter generator | Notices to exchanges, banks, telecoms; foreign letters of request | Build | Partly there: `request_letters.py` (letters to exchanges), `freeze_requests.py` (tracks what was sent and what came of it). No bank, telecom or foreign letters yet |
| 8 | Government platforms | NCRP and 1930, CFCFRMS, Samanvaya, Sahyog, CCTNS | Link and import; we cannot write into them without an official integration | Partly there: NCRP numbers in complaints and case references (`complaints.py`, `case_refs.py`, `payment_intake.py`), and the citizen site's complaint intake. No imports from the other platforms |
| 9 | Custody wallet tooling | Government-controlled multisig wallets for seized crypto | Build the procedure and the records; never hold keys on our servers | Not started (the code only reads seizure labels on addresses) |

Background for each feature (what police use today, the legal powers involved,
and how an investigator moves through the suite) is in the team's report
"Exchequer Investigation Suite: tools, workflow and law". Ask your human for
the link.

When a feature is claimed, its handoff file in `docs/handoff/` names it by
number, and this table's status column is updated in the same pull request.
