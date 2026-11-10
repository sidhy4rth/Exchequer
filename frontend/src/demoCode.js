// The demo access a visitor unlocked, if the site asks for a code (backend/app/access.py).
//
// The right code at /access/check returns a pass, and the pass is what this
// tab keeps and sends: a pass is never locked out by someone else's wrong
// guesses on the same connection, as the code itself can be. A code stored
// by an older build is still sent until the tab is closed.
//
// Kept in sessionStorage: one tab, gone when the window closes. On a shared
// computer at a police station the next person does not inherit it, as they
// would from localStorage; and unlike a cookie it is never sent unless our
// own code attaches it (api/client.js), so another site cannot make the
// browser spend it.

const KEY = 'exchequer-demo-code'
const PASS_KEY = 'exchequer-demo-pass'
// Where storage is refused (some private modes), it lasts until the page is
// reloaded instead of not at all.
const inMemory = { [KEY]: '', [PASS_KEY]: '' }

function read(key) {
  try { return sessionStorage.getItem(key) ?? '' } catch { return inMemory[key] }
}

function write(key, value) {
  try { sessionStorage.setItem(key, value) } catch { inMemory[key] = value }
}

function remove(key) {
  inMemory[key] = ''
  try { sessionStorage.removeItem(key) } catch { /* nothing to forget */ }
}

export function demoCode() { return read(KEY) }

export function demoPass() { return read(PASS_KEY) }

export function rememberDemoCode(code) { write(KEY, code) }

/** Keep the pass /access/check returned, and drop any raw code. */
export function rememberDemoPass(pass) {
  write(PASS_KEY, pass)
  remove(KEY)
}

export function forgetDemoPass() { remove(PASS_KEY) }

export function forgetDemoCode() {
  remove(KEY)
  remove(PASS_KEY)
}

/** Whether this tab has unlocked live tracing. */
export function hasDemoAccess() { return Boolean(demoPass() || demoCode()) }

/** What stands between this tab and live tracing, from GET /access
 * (backend/app/access.py): 'officer' when the owner has closed the console
 * to signed-in officers and this caller is not one (a demo code does not
 * help then), 'code' when the site wants the demo code and this tab has not
 * given it, else null. */
export function liveLock(access, unlocked) {
  if (access?.console === 'officers') return access.officer ? null : 'officer'
  return access?.demo_code_required && !unlocked ? 'code' : null
}
