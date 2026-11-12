// What a case is exported as and how it is checked: reports, the graph,
// letters, signatures, and the freeze requests sent about it. Lane B.
import { BASE, apiFetch, jsonOrThrow, toError } from './client'

/** URL of the downloadable report, used directly by the export button. */
export function reportUrl(caseId, format = 'text') {
  return `${BASE}/trace/${caseId}/report?format=${format}`
}

export async function fetchReport(caseId, format = 'text') {
  const response = await apiFetch(reportUrl(caseId, format))
  if (!response.ok) throw await toError(response)
  if (format === 'pdf') return response.blob()
  return format === 'text' ? response.text() : response.json()
}

export async function fetchLetters(caseId) {
  const response = await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/letters`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

export async function fetchLetter(caseId, to) {
  const response = await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/letter?to=${encodeURIComponent(to)}`)
  if (!response.ok) throw await toError(response)
  return response.text()
}

/** A draft notice to a bank or a telecom operator (backend notice_letters.py),
 * from the case and the officer's details. The details go in the body, never
 * the URL: account and phone numbers are personal data. */
export async function draftNotice(caseId, to, details) {
  const response = await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/notice`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to, ...details }),
  })
  if (!response.ok) throw await toError(response)
  return response.text()
}

/** A recorded example's letters (routes/demos.py): listed and drafted from
 * the recording as a case's are, though none can be logged as sent. */
export async function fetchRecordedLetters(demo) {
  return jsonOrThrow(await apiFetch(`${BASE}/demos/recorded/${encodeURIComponent(demo)}/letters`))
}

export async function fetchRecordedLetter(demo, to) {
  const response = await apiFetch(`${BASE}/demos/recorded/${encodeURIComponent(demo)}/letter?to=${encodeURIComponent(to)}`)
  if (!response.ok) throw await toError(response)
  return response.text()
}

/**
 * Check a report's content hash and signature (public; nothing stored): a
 * text report as a string, or an Exchequer PDF as its bytes, whose attached
 * report is checked and whose pages are compared with it.
 */
export async function verifyReport(body, { pdf = false } = {}) {
  const response = await apiFetch(`${BASE}/verify`, {
    method: 'POST',
    headers: { 'Content-Type': pdf ? 'application/pdf' : 'text/plain; charset=utf-8' },
    body,
  })
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** The public key this server signs reports with. */
export async function fetchSigningKey() {
  const response = await apiFetch(`${BASE}/signing-key`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** The case's transfer graph as GraphML or CSV text. */
export async function fetchGraph(caseId, format = 'graphml') {
  const response = await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/graph?format=${format}`)
  if (!response.ok) throw await toError(response)
  return response.text()
}

// ---------------------------------------------------------------------------
// Freeze requests (backend/app/routes/requests.py)
// ---------------------------------------------------------------------------
export async function fetchCaseRequests(caseId) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/requests`))
}

export async function fetchOpenRequests() {
  return jsonOrThrow(await apiFetch(`${BASE}/requests?open=true`))
}

export async function logRequest(body) {
  return jsonOrThrow(await apiFetch(`${BASE}/requests`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))
}

export async function updateRequest(requestId, changes) {
  return jsonOrThrow(await apiFetch(`${BASE}/requests/${encodeURIComponent(requestId)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
  }))
}

/** A second signed-in officer of the drafter's unit approves an urgent freeze
 * letter. The header shows the server the app sent it, not a cross-site form. */
export async function signOffRequest(requestId) {
  return jsonOrThrow(await apiFetch(`${BASE}/requests/${encodeURIComponent(requestId)}/signoff`, {
    method: 'POST', headers: { 'X-Exchequer-Request': '1' },
  }))
}

export async function deleteRequest(requestId) {
  return jsonOrThrow(await apiFetch(`${BASE}/requests/${encodeURIComponent(requestId)}`, { method: 'DELETE' }))
}

// ---------------------------------------------------------------------------
// Second-provider recheck (backend/app/routes/recheck.py): the transfers a
// case cites, reread from a provider the trace did not use. `id` is a case
// id, or "demo-<n>" for a recorded example. A server without the endpoints
// answers 404 (GET) or 405 (POST): null, and the page shows no recheck.
// ---------------------------------------------------------------------------
async function recheckOrNull(response) {
  if (response.status !== 404 && response.status !== 405) return jsonOrThrow(response)
  await response.text().catch(() => {}) // read to the end: a body left unread keeps the request open
  return null
}

/** The case's last recheck; `checked_at` is null before the first. */
export async function fetchRecheck(id) {
  return recheckOrNull(await apiFetch(`${BASE}/trace/${encodeURIComponent(id)}/recheck`))
}

/** Reread the case's cited transfers now (gated and rate-limited like a trace). */
export async function runRecheck(id, caseRef = null) {
  // A signed-in officer's case reference, in the body only (case_refs.py).
  const body = caseRef ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ case_ref: caseRef }) } : {}
  return recheckOrNull(await apiFetch(`${BASE}/trace/${encodeURIComponent(id)}/recheck`, { method: 'POST', ...body }))
}

/** The asset register (backend assets.py): what was frozen or seized in a
 * case, where it is held, its court deadline and its outcome. */
export async function fetchCaseAssets(caseId) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/assets`))
}

export async function addAsset(caseId, body) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/assets`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))
}

export async function updateAsset(assetId, changes) {
  return jsonOrThrow(await apiFetch(`${BASE}/assets/${encodeURIComponent(assetId)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
  }))
}

/** Held assets whose court deadline is within `days` days or past, soonest first. */
export async function fetchDueAssets(days = 7) {
  return jsonOrThrow(await apiFetch(`${BASE}/assets/due?days=${encodeURIComponent(days)}`))
}
