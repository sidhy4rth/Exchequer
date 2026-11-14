// Call detail records read against a case (suite feature 5). The CDR is read in
// the browser; only the summary the officer confirms is sent, and only the
// numbers they choose are checked against other cases (in a POST body, never a URL).
import { BASE, apiFetch, jsonOrThrow } from './client'

const path = (caseId, rest = '') => `${BASE}/trace/${encodeURIComponent(caseId)}/cdr${rest}`
const post = (body) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export async function fetchCaseCdr(caseId) {
  return jsonOrThrow(await apiFetch(path(caseId)))
}

export async function checkCdrNumbers(caseId, numbers) {
  return jsonOrThrow(await apiFetch(path(caseId, '/check'), post({ numbers })))
}

export async function saveCdrSummary(caseId, body) {
  return jsonOrThrow(await apiFetch(path(caseId), post(body)))
}
