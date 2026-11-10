import { useSyncExternalStore } from 'react'
import { fetchMe } from './api/accounts'

// Two ways into the console. An officer signs in at the investigator's door
// (R23): the backend keeps the session in an HttpOnly cookie, and GET
// /auth/me names the officer, which the account store below holds for the
// app. Anyone else looks around as a demo: this remembers, for this browser
// tab, which view someone chose at the front door -- the investigator's
// console or the citizen's page -- so the app knows which to show. The demo
// view grants nothing, and the backend never sees it. Live tracing on a
// public site is guarded by the demo code instead (demoCode.js,
// backend/app/access.py).

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

// -- the officer signed in, if any --------------------------------------------
// status: 'unknown' before the first check, 'checking', 'officer' or 'none'.
let current = { status: 'unknown', officer: null }
const listeners = new Set()
function set(next) {
  current = next
  listeners.forEach((listener) => listener())
}

/** The account as it stands: { status, officer }. */
export const account = () => current

/** The account, kept current in a component. */
export function useAccount() {
  return useSyncExternalStore((listener) => {
    listeners.add(listener)
    return () => listeners.delete(listener)
  }, account)
}

/** Ask the backend who this browser is signed in as. No answer counts as
 * nobody: the demo still opens. */
export async function checkAccount() {
  set({ status: 'checking', officer: null })
  const me = await fetchMe().catch(() => null)
  set(me?.id ? { status: 'officer', officer: me } : { status: 'none', officer: null })
}

/** Ask again without the 'checking' blink, for an officer already in: a
 * session ended (12 idle hours, or an admin's reset or switch-off) signs
 * the app out, a changed role or unit is taken up, and no answer at all
 * changes nothing. */
export async function recheckAccount() {
  if (current.status !== 'officer') return
  let me
  try { me = await fetchMe() } catch (failed) { if (failed.status !== 401) return }
  set(me?.id ? { status: 'officer', officer: me } : { status: 'none', officer: null })
}

/** Look again each time the tab is shown; returns the way to stop. */
export function watchAccount() {
  const shown = () => { if (document.visibilityState !== 'hidden') recheckAccount() }
  document.addEventListener('visibilitychange', shown)
  return () => document.removeEventListener('visibilitychange', shown)
}

export const signedInAs = (officer) => set({ status: 'officer', officer })
export const signedOut = () => set({ status: 'none', officer: null })
/** Back to before the first check (each test starts here). */
export const resetAccount = () => set({ status: 'unknown', officer: null })

/** How each account role reads on screen. */
export const ROLE_NAMES = { officer: 'Officer', supervisor: 'Supervisor', admin: 'Admin' }
export const isAdmin = (officer) => ROLE_NAMES[officer?.role] === 'Admin'
