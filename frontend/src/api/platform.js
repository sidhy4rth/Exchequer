// The platform around tracing: the case book, health and coverage, the
// watchlist and bulk intake. Lane C.
import { BASE, apiFetch, jsonOrThrow, toError } from './client'

export async function fetchCases(limit = 20) {
  const response = await apiFetch(`${BASE}/cases?limit=${limit}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/**
 * Stored cases whose traced funds passed through the same intermediary as
 * `caseId`. A query over the case store, so it never touches the chain.
 */
export async function fetchRelatedCases(caseId) {
  const response = await apiFetch(`${BASE}/cases/correlate?case_id=${encodeURIComponent(caseId)}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** What the attribution database covers on one chain. */
export async function fetchExchanges(chain) {
  const response = await apiFetch(`${BASE}/exchanges?chain=${encodeURIComponent(chain)}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** What sanctions and mixer screening covers on one chain. */
export async function fetchRiskLabels(chain) {
  const response = await apiFetch(`${BASE}/risk-labels?chain=${encodeURIComponent(chain)}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** The addresses the tool knows -- real, labelled -- for the sign-in backdrop. */
export async function fetchLedger(limit = 1400) {
  const response = await apiFetch(`${BASE}/ledger?limit=${limit}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** Each chain the site can trace: its assets, readiness and label counts. */
export async function fetchChains() {
  const response = await apiFetch(`${BASE}/chains`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** Up or not, and nothing else (the operator's detail is behind a token). */
export async function fetchHealth() {
  const response = await apiFetch(`${BASE}/health`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

// ---------------------------------------------------------------------------
// Watchlist (backend/app/routes/watches.py): this browser's watched addresses
// and the alerts raised when funds leave them.
// ---------------------------------------------------------------------------

export async function fetchWatches() {
  return jsonOrThrow(await apiFetch(`${BASE}/watches`))
}

export async function addWatch({ address, chain, asset, note, caseId, webhookUrl }) {
  return jsonOrThrow(await apiFetch(`${BASE}/watches`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      address, chain, asset, note: note ?? '', case_id: caseId ?? null,
      ...(webhookUrl ? { webhook_url: webhookUrl } : {}),
    }),
  }))
}

export async function removeWatch(watchId) {
  return jsonOrThrow(await apiFetch(`${BASE}/watches/${encodeURIComponent(watchId)}`, { method: 'DELETE' }))
}

export async function removeWatchHook(watchId) {
  return jsonOrThrow(await apiFetch(`${BASE}/watches/${encodeURIComponent(watchId)}/webhook`, { method: 'DELETE' }))
}

export async function checkWatchNow(watchId) {
  return jsonOrThrow(await apiFetch(`${BASE}/watches/${encodeURIComponent(watchId)}/check`, { method: 'POST' }))
}

export async function fetchAlerts(unread = false) {
  return jsonOrThrow(await apiFetch(`${BASE}/alerts?unread=${unread ? 'true' : 'false'}`))
}

export async function markAlertsRead(alertIds = null) {
  return jsonOrThrow(await apiFetch(`${BASE}/alerts/read`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ alert_ids: alertIds }),
  }))
}

// ---------------------------------------------------------------------------
// Bulk intake (backend/app/routes/batches.py)
// ---------------------------------------------------------------------------
export async function startBatch(name, rows) {
  const response = await apiFetch(`${BASE}/batches`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, rows }),
  })
  if (response.status === 400) {
    const body = await response.json().catch(() => ({}))
    const err = new Error(body.detail || 'Some rows cannot be traced.')
    err.rowErrors = body.row_errors ?? []
    throw err
  }
  return jsonOrThrow(response)
}

export async function fetchBatch(batchId) {
  return jsonOrThrow(await apiFetch(`${BASE}/batches/${encodeURIComponent(batchId)}`))
}

export async function fetchBatches() {
  return jsonOrThrow(await apiFetch(`${BASE}/batches`))
}

// ---------------------------------------------------------------------------
// The demo code (backend/app/access.py)
// ---------------------------------------------------------------------------

/** Whether this site asks for a demo code before live tracing. */
export async function fetchAccess() {
  const response = await apiFetch(`${BASE}/access`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** Check a code before remembering it: resolves if right, throws the backend's reason if not.
 * Plain fetch, not apiFetch: that would add any code already stored, over this one. */
export async function checkDemoCode(code) {
  const response = await fetch(`${BASE}/access/check`, { method: 'POST', headers: { 'X-Exchequer-Demo-Code': code } })
  if (!response.ok) throw await toError(response)
  return response.json()
}
