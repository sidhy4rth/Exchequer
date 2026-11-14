// Call detail records read against a case (suite feature 5). The CDR is read in
// the browser; only the summary the officer confirms is sent, and only the
// numbers they choose are checked against other cases (in a POST body, never a URL).
import { BASE, apiFetch, jsonOrThrow } from './client'

const path = (caseId, rest = '') => `${BASE}/trace/${encodeURIComponent(caseId)}/cdr${rest}`
const post = (body) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

// withdrawn: true lists the withdrawn summaries too, with who withdrew them and why.
export async function fetchCaseCdr(caseId, { withdrawn = false } = {}) {
  return jsonOrThrow(await apiFetch(path(caseId, withdrawn ? '?withdrawn=1' : '')))
}

export async function withdrawCdrImport(caseId, importId, reason) {
  return jsonOrThrow(await apiFetch(path(caseId, `/${encodeURIComponent(importId)}/withdraw`), post({ reason })))
}

export async function checkCdrNumbers(caseId, numbers) {
  return jsonOrThrow(await apiFetch(path(caseId, '/check'), post({ numbers })))
}

export async function saveCdrSummary(caseId, body) {
  return jsonOrThrow(await apiFetch(path(caseId), post(body)))
}
