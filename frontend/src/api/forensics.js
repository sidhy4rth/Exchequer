// Phone and computer forensics tied to a case (suite feature 2). The export
// itself is scanned in the browser (components/case/exportScan.js); the server
// only says whether the scan is offered and records that one ran, by its counts.
import { BASE, apiFetch, jsonOrThrow } from './client'

/** { enabled: true }, or throws (404) while the server's flag is off. */
export async function fetchExportScan(caseId) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/export-scan`))
}

/** Record that a scan ran: counts only, never a value or a word. */
export async function recordExportScan(caseId, { lines, bytes, addresses, txHashes, seedRuns }) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/export-scan`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lines, bytes, addresses, tx_hashes: txHashes, seed_runs: seedRuns }),
  }))
}
