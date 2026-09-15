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

export function traceAddress(address, maxDepth, chain, asset, direction) {
  const body = JSON.stringify({
    address,
    ...(maxDepth ? { max_depth: maxDepth } : {}),
    ...(chain ? { chain } : {}),
    ...(asset ? { asset } : {}),
    ...(direction ? { direction } : {}),
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
      response = await fetch(`${BASE}/trace`, {
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
  const response = await fetch(`${BASE}/trace/${caseId}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

export async function fetchCases(limit = 20) {
  const response = await fetch(`${BASE}/cases?limit=${limit}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/**
 * Stored cases whose traced funds passed through the same intermediary as
 * `caseId`. A query over the case store, so it never touches the chain.
 */
export async function fetchRelatedCases(caseId) {
  const response = await fetch(`${BASE}/cases/correlate?case_id=${encodeURIComponent(caseId)}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** What the attribution database covers on one chain. */
export async function fetchExchanges(chain) {
  const response = await fetch(`${BASE}/exchanges?chain=${encodeURIComponent(chain)}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** What sanctions and mixer screening covers on one chain. */
export async function fetchRiskLabels(chain) {
  const response = await fetch(`${BASE}/risk-labels?chain=${encodeURIComponent(chain)}`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

export async function fetchHealth() {
  const response = await fetch(`${BASE}/health`)
  if (!response.ok) throw await toError(response)
  return response.json()
}

/** URL of the downloadable report, used directly by the export button. */
export function reportUrl(caseId, format = 'text') {
  return `${BASE}/trace/${caseId}/report?format=${format}`
}

export async function fetchReport(caseId, format = 'text') {
  const response = await fetch(reportUrl(caseId, format))
  if (!response.ok) throw await toError(response)
  return format === 'text' ? response.text() : response.json()
}
