// The demo code a visitor typed, if the site asks for one (backend/app/access.py).
//
// Kept in sessionStorage: one tab, gone when the window closes. On a shared
// computer at a police station the next person does not inherit it, as they
// would from localStorage; and unlike a cookie it is never sent unless our
// own code attaches it (api/client.js), so another site cannot make the
// browser spend it.

const KEY = 'exchequer-demo-code'
// Where storage is refused (some private modes), the code lasts until the
// page is reloaded instead of not at all.
let inMemory = ''

export function demoCode() {
  try { return sessionStorage.getItem(KEY) ?? '' } catch { return inMemory }
}

export function rememberDemoCode(code) {
  try { sessionStorage.setItem(KEY, code) } catch { inMemory = code }
}

export function forgetDemoCode() {
  inMemory = ''
  try { sessionStorage.removeItem(KEY) } catch { /* nothing to forget */ }
}
