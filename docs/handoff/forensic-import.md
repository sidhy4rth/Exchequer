# Handoff: forensic import (suite feature 2)

- **Feature**: an officer scans a phone or computer export (CSV, TSV, XML, JSON, HTML, text) in the browser for wallet addresses, transaction hashes and seed phrases
- **Issue**: #145
- **Branch**: `feat/forensic-import` (stacked: `feat/forensic-import-checks`, `feat/forensic-import-scan`, `feat/forensic-import-panel`)
- **Current**: Sidhyarth
- **Last worked on**: Sidhyarth, 2026-11-14
- **Status**: slice 1 (format-agnostic, in-browser scan) in review, behind `EXCHEQUER_EXPORT_SCAN`

## Done

- Slice 1, in four stacked PRs:
  1. Server: the flag `EXCHEQUER_EXPORT_SCAN` (off by default) and `routes/export_scan.py`:
     `GET /trace/{case_id}/export-scan` (404 while the flag is off, which hides the panel) and
     `POST /trace/{case_id}/export-scan`, which records in the audit trail that a scan ran and
     its counts only (lines, bytes, addresses, hashes, seed-phrase runs). Never the file, a value or a word.
  2. Checks in the browser: `keccak.js` (port of `backend/app/keccak.py`), `addressCheck.js`
     (EIP-55 and Tron Base58Check, the backend's `etherscan_client.py` rules), and the BIP-39
     English wordlist `bip39English.js` (bitcoin/bips at a pinned commit, SHA-256 pinned by a test).
  3. The scanner `exportScan.js`: reads the file in 1 MB pieces, yields between them, and
     keeps only line numbers and counts for seed-phrase runs.
  4. The panel `ExportScanPanel.jsx` on the case's Evidence tab.

## Decisions

- The file is read in the browser only; nothing in it is sent. The audit row holds counts.
- A seed-phrase run is reported as "N BIP-39 words at line L, hidden". The words are never
  kept in the results, rendered, stored, sent or logged. Same rule as `assets.py::_seed_phrase`:
  twelve or more list words in a row, digits between them ignored, any other word breaks the run.
- No BIP-39 checksum test: a run with a valid checksum would need a valid mnemonic in the tests.
- 64 hex without 0x is reported as "Tron transaction, or any SHA-256": file hashes look the same.
- An EVM address cannot say its chain; the trace link opens the trace form on Ethereum, which
  the officer can change (the console search box's `findTarget` rule).
- No "add as case identifier": `identifiers.py` has no wallet kind. Adding one is feature 4's call.

## Next

1. Vendor importers, once sample exports exist: Cellebrite UFDR (zip with `report.xml`),
   Magnet AXIOM (case.mfdb / CSV), MSAB XRY (XML), Oxygen, Autopsy. Each would map a hit to
   its artefact (chat, note, app) instead of a line number.
2. Optionally: a wallet kind in the identifier register so a found address can be saved to the case.
3. Turn `EXCHEQUER_EXPORT_SCAN` on in production once reviewed (render.yaml, a separate PR).

## Open questions

- Owner: should a found address be saved to the case (needs a wallet kind in identifiers, feature 4)?

## Files mid-change (do not touch)

- none
