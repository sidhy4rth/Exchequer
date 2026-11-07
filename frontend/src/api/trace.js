// Tracing: run a trace, follow its job, read a stored case or a recorded
// demo. Lane A.
import { BASE, apiFetch, toError } from './client'

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

/** What the trace form may offer: { payments: bool, lookup_limit: int } (R1). */
export async function fetchTraceIntake() {
  const response = await apiFetch(`${BASE}/trace/intake`)
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
  if (snapshot.status === 'done') {
    // A finished job holds a stored case's result only briefly; the store has it by id.
    if (snapshot.result) return snapshot.result
    if (snapshot.case_id) return fetchCase(snapshot.case_id)
    throw new Error('The trace finished, but its result was not saved and is no longer held. Run the trace again.')
  }
  const err = new Error(snapshot.error?.detail || 'The trace failed.')
  err.status = snapshot.error?.status_code
  throw err
}

// A stream silent this long is treated as lost: while a trace runs the server
// sends a heartbeat event every 15 s (routes/jobs.py).
const STREAM_SILENCE_MS = 45_000

function watchJob(jobId, onProgress) {
  return new Promise((resolve, reject) => {
    let finished = false
    let failures = 0
    let source = null
    let watchdog = null
    const finish = async () => {
      if (finished) return
      finished = true
      clearTimeout(watchdog)
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
    // Poll instead of the stream. poll() then sees a lost job's 404 and says
    // so, rather than leaving the progress bar spinning forever.
    const fallBack = () => {
      clearTimeout(watchdog)
      if (finished || !source) return
      source.close(); source = null
      poll()
    }
    const alive = () => { failures = 0; clearTimeout(watchdog); watchdog = setTimeout(fallBack, STREAM_SILENCE_MS) }
    if (typeof EventSource === 'undefined') { poll(); return }
    source = new EventSource(`${BASE}/trace/jobs/${encodeURIComponent(jobId)}/events`)
    alive()
    source.addEventListener('progress', (e) => { alive(); try { onProgress?.(JSON.parse(e.data)) } catch { /* ignore */ } })
    source.addEventListener('heartbeat', alive)
    source.addEventListener('done', finish)
    source.addEventListener('failed', finish)
    source.onerror = () => {
      failures += 1
      // A reconnect that is refused (the new instance's 404 after a restart,
      // a 502 while it comes back) closes the source for good, with no third
      // error to wait for.
      if (source && (source.readyState === EventSource.CLOSED || failures >= 3)) fallBack()
    }
  })
}

/** Ask the server to stop a running trace job. Only the browser that started
 * it may (the owner key goes with every request); the job then ends as failed
 * with a "stopped" error, which runTrace's promise rejects with. */
export async function stopTraceJob(jobId) {
  const response = await apiFetch(`${BASE}/trace/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' })
  if (!response.ok) throw await toError(response)
  return response.json()
}

// The trace a job runs, without the complaint's particulars: what a running
// job is remembered under for the tab, and in sessionStorage across a reload.
function jobTrace({ address, maxDepth, chain, asset, direction, timeBudgetSeconds, payments }) {
  return {
    address,
    ...(maxDepth ? { max_depth: maxDepth } : {}),
    ...(chain ? { chain } : {}),
    ...(asset ? { asset } : {}),
    ...(direction ? { direction } : {}),
    ...(timeBudgetSeconds ? { time_budget_seconds: timeBudgetSeconds } : {}),
    // R1: start from the victim's payments. The backend checks each one is an
    // incoming transfer to `address`, and reads the wallet from the first.
    ...(payments?.length ? { payments: payments.map((h) => ({ tx_hash: h })) } : {}),
  }
}

// What identifies the trace in this tab: everything but the complaint's
// particulars (the NCRP number and the victim's own wallet), which go to the
// server in the POST body only and are never kept in sessionStorage.
function jobKey(params) {
  return JSON.stringify(jobTrace(params))
}

function jobBody(params) {
  const { payments, ncrpAck, victimAddress } = params
  return JSON.stringify({
    ...jobTrace(params),
    ...(ncrpAck ? { ncrp_ack: ncrpAck } : {}),
    // The victim's own wallet: the backend compares each payment's sender with it.
    ...(victimAddress && payments?.length ? { victim_address: victimAddress } : {}),
  })
}

/** Whether this tab already runs (or ran until a reload) this exact trace, so
 * opening its page again re-attaches to the job instead of asking first. */
export function traceJobRemembered(params) {
  const key = jobKey(params)
  return jobsInFlight.has(key) || Boolean(recalledJob(key))
}

/**
 * Run a trace as a background job and resolve with its result.
 * `onProgress(snapshot)` receives { status, progress: { stage, hop, max_depth,
 * level_size, level_read, addresses }, elapsed } as the trace moves.
 */
export function runTrace(params, onProgress) {
  const body = jobBody(params)
  const key = jobKey(params)
  const existing = jobsInFlight.get(key)
  if (existing) { existing.listeners.add(onProgress); return existing.promise }
  const listeners = new Set([onProgress])
  const broadcast = (snap) => listeners.forEach((fn) => fn?.(snap))
  const promise = (async () => {
    try {
      let jobId = recalledJob(key)
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
        rememberJob(key, jobId)
      }
      return await watchJob(jobId, broadcast)
    } finally {
      rememberJob(key, null)
      jobsInFlight.delete(key)
    }
  })()
  jobsInFlight.set(key, { promise, listeners })
  return promise
}
