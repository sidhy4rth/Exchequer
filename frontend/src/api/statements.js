// Bank and exchange statements read against a case (suite feature 5). The
// statement is read in the browser; only the rows the officer confirms are sent.
import { BASE, apiFetch, jsonOrThrow } from './client'

export async function fetchCaseStatements(caseId) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/statements`))
}

export async function saveStatementRows(caseId, body) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/statements`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))
}
