// Demo mode. Exchequer has no accounts yet (R23 brings them), so there is
// nothing to sign in with: this remembers, for this browser tab, which view
// someone chose at the front door -- the investigator's console or the
// citizen's page -- so the app knows which to show. It grants nothing, and
// the backend never sees it. Live tracing on a public site is guarded by the
// demo code instead (demoCode.js, backend/app/access.py).

const KEY = 'exchequer-demo-session'
export const ROLES = ['investigator', 'citizen']

/** 'investigator', 'citizen', or null. */
export function role() {
  let value
  try { value = sessionStorage.getItem(KEY) } catch { return 'investigator' }
  if (value === '1') return 'investigator' // tabs that entered before there were two views
  return ROLES.includes(value) ? value : null
}

/** Choose a view for this tab. */
export function enterAs(asRole) {
  if (!ROLES.includes(asRole)) return false
  try { sessionStorage.setItem(KEY, asRole) } catch { /* private mode: still shown */ }
  return true
}

/** Back to the front door. */
export function leave() {
  try { sessionStorage.removeItem(KEY) } catch { /* nothing to remove */ }
}
