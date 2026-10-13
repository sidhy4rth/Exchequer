// This browser's owner key: a random value made once and sent with every API
// request, so the backend can list the cases this browser traced and nobody
// else's (backend/app/ownership.py). It is not a password and not an
// account -- clearing site data starts a fresh, empty history, and a case
// link still opens the case anywhere.

const KEY = 'exchequer-owner-key'
let memory = null // private mode: one key for the life of the tab

function fresh() {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  // base64url, no padding: 43 characters the backend accepts as-is.
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function ownerKey() {
  try {
    let key = localStorage.getItem(KEY)
    if (!key || !/^[A-Za-z0-9_-]{22,128}$/.test(key)) {
      key = fresh()
      localStorage.setItem(KEY, key)
    }
    return key
  } catch {
    if (!memory) memory = fresh()
    return memory
  }
}

export const OWNER_HEADER = 'X-Exchequer-Owner'
