// A demonstration front door, nothing more. The backend has no accounts:
// this remembers, for this browser tab, which of the two demo sign-ins
// someone passed, so the console has a threshold to cross on stage. It is not
// access control and the README does not call it that.
//
// Investigators get the tracing console. Citizens get their own space, which
// is empty for now.

const KEY = 'exchequer-demo-session'
const ACCOUNTS = {
  investigator: { user: 'admin', pass: 'admin' },
  citizen: { user: 'user', pass: 'user' },
}

export function demoAccount(role) {
  return ACCOUNTS[role]
}

/** 'investigator', 'citizen', or null. */
export function role() {
  let value
  try { value = sessionStorage.getItem(KEY) } catch { return 'investigator' }
  if (value === '1') return 'investigator' // tabs signed in before there were two doors
  return value === 'investigator' || value === 'citizen' ? value : null
}

export function signIn(asRole, user, pass) {
  const account = ACCOUNTS[asRole]
  if (!account || user.trim() !== account.user || pass !== account.pass) return false
  try { sessionStorage.setItem(KEY, asRole) } catch { /* private mode: still admitted */ }
  return true
}

export function signOut() {
  try { sessionStorage.removeItem(KEY) } catch { /* nothing to remove */ }
}
