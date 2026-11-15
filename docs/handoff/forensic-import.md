# Handoff: forensic import (suite feature 2)

- **Feature**: an officer scans a phone or computer export (CSV, TSV, XML, JSON, HTML, text) in the browser for wallet addresses, transaction hashes and seed phrases
- **Issue**: #145
- **Branch**: `feat/forensic-import` (stacked: `feat/forensic-import-checks`, `feat/forensic-import-scan`, `feat/forensic-import-panel`, `feat/forensic-import-identifiers`)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: slice 1 (format-agnostic, in-browser scan) merged on 2026-11-15 in #147 (with #154, #155, #156 and #164), behind `EXCHEQUER_EXPORT_SCAN`, off

## Done

- Slice 1, in four stacked PRs (#147, #154, #155, #156), and #164 on top:
  1. Server: the flag `EXCHEQUER_EXPORT_SCAN` (off by default) and `routes/export_scan.py`:
     `GET /trace/{case_id}/export-scan` (404 while the flag is off, which hides the panel) and
     `POST /trace/{case_id}/export-scan`, which records in the audit trail that a scan ran and
     its counts only (lines, bytes, addresses, hashes, seed-phrase runs). Never the file, a value or a word.
  2. Checks in the browser: `keccak.js` (port of `backend/app/keccak.py`), `addressCheck.js`
     (EIP-55 and Tron Base58Check, the backend's `etherscan_client.py` rules), and the BIP-39
     English wordlist `bip39English.js` (bitcoin/bips at a pinned commit, SHA-256 pinned by a test).
  3. The scanner `exportScan.js`: reads the file in 1 MB pieces, yields between them, and
     keeps only line numbers and counts for seed-phrase runs.
  4. The panel `ExportScanPanel.jsx` on the case's Evidence tab: a summary, possible seed phrases
     ("12 BIP-39 words at line 40, hidden" and a note to secure the device), and tables of
     addresses and hashes with a "Trace" / "Trace from this payment" link (`find.js::findTarget`).
  5. Pre-review fixes (14 Nov): markup read through in a seed run, UTF-16 without a byte-order
     mark, 64-hex values named for what they may be, table captions and link names.
- Add as case identifier (#164, stacked on #156, branch `feat/forensic-import-identifiers`): a `wallet`
  kind in `identifiers.py` (feature 4), checked by the trace form's address rules; each address row
  in the panel has "Add as case identifier", which sends that one address (kind `wallet`, and the
  fixed note "Found by the export scan") to `POST /trace/{case_id}/identifiers`. The identifiers
  route audits the kind only. Already on the case shows as such (409).

## Decisions

- The file is read in the browser only; nothing in it is sent. The audit row holds counts.
- A seed-phrase run is reported as "N BIP-39 words at line L, hidden". The words are never
  kept in the results, rendered, stored, sent or logged. Same rule as `assets.py::_seed_phrase`:
  twelve or more list words in a row, digits between them ignored, any other word breaks the run.
- No BIP-39 checksum test: a run with a valid checksum would need a valid mnemonic in the tests.
- A 64-hex value is reported as what it may be, never as a transaction hash: a Tron or EVM
  transaction hash, a file's SHA-256 and a raw private key all have that shape.
- Markup is read through in a seed run (pre-review fix): a tag's or entity's name (`<br>`,
  `</td>`, `&nbsp;`) neither counts nor ends a run, so an HTML notes export still shows its
  phrase. A tag ends at `>` or the end of its line. UTF-16 without a byte-order mark is
  recognised by its NUL in every other byte instead of being called binary.
- An EVM address cannot say its chain; the trace link opens the trace form on Ethereum, which
  the officer can change (the console search box's `findTarget` rule).
- A found address is saved to the case only when the officer clicks "Add as case identifier" on
  its row, and only that address is sent. Hashes are not offered: there is no hash kind.

## Next

1. Vendor importers, once sample exports exist: Cellebrite UFDR (zip with `report.xml`),
   Magnet AXIOM (case.mfdb / CSV), MSAB XRY (XML), Oxygen, Autopsy. Each would map a hit to
   its artefact (chat, note, app) instead of a line number.
2. Turn `EXCHEQUER_EXPORT_SCAN` on in production once reviewed (render.yaml, a separate PR).

## Open questions

- none

## Files mid-change (do not touch)

- none
