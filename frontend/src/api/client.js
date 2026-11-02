import { OWNER_HEADER, ownerKey } from '../owner'

// Shared by every lane's API file: the base URL, the owner key on every
// request, and the backend's own error messages. Lane C.

// Calls to the Exchequer backend.
//
// Requests are relative, so the frontend works unchanged whether it is served
// by the Vite dev server (which proxies /api to port 8000) or by FastAPI
// itself in the deployed image.

// In development the Vite dev server proxies /api to the backend on port
// 8000. In the deployed image FastAPI serves this bundle itself, so the API is
// same-origin at the root and VITE_API_BASE is built as an empty string.
// Either way the frontend never hardcodes a host.
export const BASE = import.meta.env.VITE_API_BASE ?? '/api'

/** fetch() with this browser's owner key attached (see owner.js). */
export function apiFetch(url, init = {}) {
  return fetch(url, { ...init, headers: { ...(init.headers || {}), [OWNER_HEADER]: ownerKey() } })
}

/** Turn a failed response into an Error carrying the backend's own message. */
export async function toError(response) {
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

export async function jsonOrThrow(response) {
  if (!response.ok) throw await toError(response)
  return response.json()
}
