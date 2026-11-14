// Bank and exchange statements read against a case (suite feature 5). The
// statement is read in the browser; only the rows the officer confirms are sent.
import { BASE, apiFetch, jsonOrThrow } from './client'

// withdrawn: true lists the withdrawn imports too, with who withdrew them and why.
export async function fetchCaseStatements(caseId, { withdrawn = false } = {}) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/statements${withdrawn ? '?withdrawn=1' : ''}`))
}

export async function withdrawStatementImport(caseId, importId, reason) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/statements/${encodeURIComponent(importId)}/withdraw`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason }),
  }))
}

export async function saveStatementRows(caseId, body) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/statements`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))
}
