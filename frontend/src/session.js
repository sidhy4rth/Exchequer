// A demonstration front door, nothing more. The backend has no accounts:
// this remembers, for this browser tab, that someone typed the demo
// credentials on the sign-in page, so the console has a threshold to cross
// on stage. It is not access control and the README does not call it that.

const KEY = 'exchequer-demo-session'
export const DEMO_USER = 'admin'
export const DEMO_PASS = 'admin'

export function signedIn() {
  try { return sessionStorage.getItem(KEY) === '1' } catch { return true }
}

export function signIn(user, pass) {
  if (user.trim() !== DEMO_USER || pass !== DEMO_PASS) return false
  try { sessionStorage.setItem(KEY, '1') } catch { /* private mode: still admitted */ }
  return true
}

export function signOut() {
  try { sessionStorage.removeItem(KEY) } catch { /* nothing to remove */ }
}
