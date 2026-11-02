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

/** Check a text report's content hash and signature (public; nothing stored). */
export async function verifyReport(text) {
  const response = await apiFetch(`${BASE}/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    body: text,
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

export async function deleteRequest(requestId) {
  return jsonOrThrow(await apiFetch(`${BASE}/requests/${encodeURIComponent(requestId)}`, { method: 'DELETE' }))
}
