import { OWNER_HEADER, ownerKey } from './owner'

// Calls to the Exchequer backend.
//
// Requests are relative, so the frontend works unchanged whether it is served
// by the Vite dev server (which proxies /api to port 8000) or by FastAPI
// itself in the deployed image.

// In development the Vite dev server proxies /api to the backend on port
// 8000. In the deployed image FastAPI serves this bundle itself, so the API is
// same-origin at the root and VITE_API_BASE is built as an empty string.
// Either way the frontend never hardcodes a host.
const BASE = import.meta.env.VITE_API_BASE ?? '/api'

/** fetch() with this browser's owner key attached (see owner.js). */
function apiFetch(url, init = {}) {
  return fetch(url, { ...init, headers: { ...(init.headers || {}), [OWNER_HEADER]: ownerKey() } })
}

/** Turn a failed response into an Error carrying the backend's own message. */
async function toError(response) {
  let detail
  try {
    const body = await response.json()
    detail = body.detail
  } catch {
    detail = null
  }
  if (Array.isArray(detail)) {
    // FastAPI validation errors arrive as a list of objects.
    detail = detail.map((d) => d.msg).join('; ')
  }
  const fallbacks = {
    400: 'That address does not look like a valid wallet address.',
    404: 'No stored case with that id.',
    429: 'The data provider is rate limiting us. Wait a few seconds and try again.',
    502: 'Could not reach the blockchain data provider.',
    503: 'The backend is not configured to trace that chain yet.',
  }
  return new Error(detail || fallbacks[response.status] || `Request failed (${response.status})`)
}

/**
 * Run a traversal.
 *
 * `direction` is 'outgoing' (where the reported address sent funds) or
 * 'incoming' (which addresses funded it). Omitted rather than defaulted here,
 * so the backend stays the single authority on what the default is.
 */
const inFlight = new Map()

export function traceAddress(address, maxDepth, chain, asset, direction, timeBudgetSeconds) {
  const body = JSON.stringify({
    address,
    ...(maxDepth ? { max_depth: maxDepth } : {}),
    ...(chain ? { chain } : {}),
    ...(asset ? { asset } : {}),
    ...(direction ? { direction } : {}),
    // Optional: stop expanding after this many seconds and return what was
    // reached, marked truncated. Omitted, the trace runs its full course.
    ...(timeBudgetSeconds ? { time_budget_seconds: timeBudgetSeconds } : {}),
  })
  // One trace per identical request at a time. React's development-mode
  // StrictMode mounts the trace view twice, and a user can double-click; the
  // backend cannot cancel a traversal it has started, so a second identical
  // POST would run the whole trace again -- twice the provider requests and a
  // duplicate stored case -- for an answer already on its way.
  const existing = inFlight.get(body)
  if (existing) return existing
  const request = (async () => {
    let response
    try {
      response = await apiFetch(`${BASE}/trace`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      })
    } catch {
      throw new Error('Cannot reach the Exchequer backend. Is it running on port 8000?')
    } finally {
      inFlight.delete(body)
    }
    if (!response.ok) throw await toError(response)
    return response.json()
  })()
  inFlight.set(body, request)
  return request
}

/**
 * A case exactly as it was traced, from the backend's own store.
 *
 * This is not the same as re-tracing the address: pattern rules are threshold
 * comparisons against live data, so a wallet that met the amount-split
 * threshold this morning may not meet it this afternoon once more funds have
 * arrived. A stored case is the evidence as it stood when it was taken.
 */
export async function fetchCase(caseId) {
  const response = await apiFetch(`${BASE}/trace/${caseId}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** Which DEMO.md traces have a recording, and when each was made. */
export async function fetchRecordedDemos() {
  const response = await apiFetch(`${BASE}/demos/recorded`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** A DEMO.md trace as recorded, served from a file: not a case, never re-traced. */
export async function fetchRecordedDemo(n) {
  const response = await apiFetch(`${BASE}/demos/recorded/${encodeURIComponent(n)}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

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

export async function fetchHealth() {
  const response = await apiFetch(`${BASE}/health`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

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

// ---------------------------------------------------------------------------
// Background traces (backend/app/routes/jobs.py)
//
// The trace runs on the server as a job; this watches its progress over
// server-sent events and resolves with the finished result. If the stream
// cannot be held (a proxy that buffers, a flaky network) it falls back to
// polling. The job id is remembered for the tab, so a reload while the trace
// runs re-attaches to it instead of starting a second, identical trace.
// ---------------------------------------------------------------------------
const JOB_KEY = 'exchequer-job:'
const jobsInFlight = new Map()

function rememberJob(key, jobId) {
  try { if (jobId) sessionStorage.setItem(JOB_KEY + key, jobId); else sessionStorage.removeItem(JOB_KEY + key) } catch { /* private mode */ }
}
function recalledJob(key) {
  try { return sessionStorage.getItem(JOB_KEY + key) } catch { return null }
}

async function jobSnapshot(jobId) {
  const response = await apiFetch(`${BASE}/trace/jobs/${encodeURIComponent(jobId)}`)
  if (response.status === 404) return null
  if (!response.ok) throw await toError(response)
  return response.json()
}

function settle(snapshot) {
  if (snapshot.status === 'done') return snapshot.result
  const err = new Error(snapshot.error?.detail || 'The trace failed.')
  err.status = snapshot.error?.status_code
  throw err
}

function watchJob(jobId, onProgress) {
  return new Promise((resolve, reject) => {
    let finished = false
    let failures = 0
    let source = null
    const finish = async () => {
      if (finished) return
      finished = true
      source?.close()
      try {
        const snap = await jobSnapshot(jobId)
        if (!snap) throw new Error('The trace job was lost (the server restarted). Run the trace again.')
        resolve(settle(snap))
      } catch (err) { reject(err) }
    }
    const poll = async () => {
      while (!finished) {
        try {
          const snap = await jobSnapshot(jobId)
          if (!snap) { finished = true; reject(new Error('The trace job was lost (the server restarted). Run the trace again.')); return }
          onProgress?.(snap)
          if (snap.status !== 'running') { finished = true; try { resolve(settle(snap)) } catch (err) { reject(err) } return }
        } catch { /* transient: try again */ }
        await new Promise((r) => setTimeout(r, 1500))
      }
    }
    if (typeof EventSource === 'undefined') { poll(); return }
    source = new EventSource(`${BASE}/trace/jobs/${encodeURIComponent(jobId)}/events`)
    source.addEventListener('progress', (e) => { failures = 0; try { onProgress?.(JSON.parse(e.data)) } catch { /* ignore */ } })
    source.addEventListener('done', finish)
    source.addEventListener('failed', finish)
    source.onerror = () => {
      failures += 1
      if (failures >= 3 && !finished) { source.close(); source = null; poll() }
    }
  })
}

/**
 * Run a trace as a background job and resolve with its result.
 * `onProgress(snapshot)` receives { status, progress: { stage, hop, max_depth,
 * level_size, level_read, addresses }, elapsed } as the trace moves.
 */
export function runTrace({ address, maxDepth, chain, asset, direction, timeBudgetSeconds }, onProgress) {
  const body = JSON.stringify({
    address,
    ...(maxDepth ? { max_depth: maxDepth } : {}),
    ...(chain ? { chain } : {}),
    ...(asset ? { asset } : {}),
    ...(direction ? { direction } : {}),
    ...(timeBudgetSeconds ? { time_budget_seconds: timeBudgetSeconds } : {}),
  })
  const existing = jobsInFlight.get(body)
  if (existing) { existing.listeners.add(onProgress); return existing.promise }
  const listeners = new Set([onProgress])
  const broadcast = (snap) => listeners.forEach((fn) => fn?.(snap))
  const promise = (async () => {
    try {
      let jobId = recalledJob(body)
      if (jobId && !(await jobSnapshot(jobId).catch(() => null))) jobId = null
      if (!jobId) {
        let response
        try {
          response = await apiFetch(`${BASE}/trace/jobs`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body,
          })
        } catch {
          throw new Error('Cannot reach the Exchequer backend. Is it running on port 8000?')
        }
        if (!response.ok) throw await toError(response)
        const started = await response.json()
        jobId = started.job_id
        broadcast(started)
        rememberJob(body, jobId)
      }
      return await watchJob(jobId, broadcast)
    } finally {
      rememberJob(body, null)
      jobsInFlight.delete(body)
    }
  })()
  jobsInFlight.set(body, { promise, listeners })
  return promise
}

/** The case's transfer graph as GraphML or CSV text. */
export async function fetchGraph(caseId, format = 'graphml') {
  const response = await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/graph?format=${format}`)
  if (!response.ok) throw await toError(response)
  return response.text()
}

// ---------------------------------------------------------------------------
// Watchlist (backend/app/routes/watches.py): this browser's watched addresses
// and the alerts raised when funds leave them.
// ---------------------------------------------------------------------------
async function jsonOrThrow(response) {
  if (!response.ok) throw await toError(response)
  return response.json()
}

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
