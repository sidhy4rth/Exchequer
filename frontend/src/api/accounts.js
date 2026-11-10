import { apiFetch, BASE } from './client'

// Officer accounts (backend/app/routes/accounts.py): signing in and out, the
// password change a temporary password needs first, and the admin's units
// and officers. The session is an HttpOnly cookie the browser keeps; nothing
// here stores it. Every call that changes something sends the header the
// backend checks (accounts.CSRF_HEADER), which a form on another site cannot.

const CHANGE = { 'Content-Type': 'application/json', 'X-Exchequer-Request': '1' }

// What a refusal says when the backend gives no words of its own.
const SAID = {
  401: 'Sign in first.',
  403: 'Only an admin can do this.',
  404: 'That account no longer exists.',
  429: 'Too many tries. Wait a little and try again.',
}

// A validation list (main.py passes Pydantic's own msg, such as "String
// should match pattern '^\s*[^@...'") said by field and kind of mistake.
const FIELDS = { email: 'the e-mail address', name: 'the name', unit_id: 'the unit', role: 'the role',
  current_password: 'the temporary password', new_password: 'the new password' }
function plainly({ loc = [], type = '', ctx }) {
  const key = String(loc[loc.length - 1] ?? '')
  const field = FIELDS[key] ?? (key.endsWith('password') ? 'the password' : null)
  if (!field) return 'Check what you entered and try again.'
  if (type === 'string_pattern_mismatch') return `Check ${field}.`
  if (type === 'string_too_long') return `${field[0].toUpperCase()}${field.slice(1)} is too long.`
  if (type === 'string_too_short' && field.includes('password')) return `Use at least ${ctx?.min_length ?? 12} characters.`
  if (type === 'string_too_short' || type === 'missing') return `Fill in ${field}.`
  return `Check ${field}.`
}

async function call(path, method = 'GET', body) {
  let response
  try {
    response = await apiFetch(`${BASE}${path}`, method === 'GET' ? {} : { method, headers: CHANGE, body: body && JSON.stringify(body) })
  } catch {
    throw new Error('Could not reach Exchequer. Check the connection and try again.')
  }
  let data = null
  try { data = await response.json() } catch { /* no body */ }
  if (response.ok) return data
  let detail = data?.detail
  if (Array.isArray(detail)) detail = [...new Set(detail.map(plainly))].join(' ')
  // status: a page tells an ended session (401) from other refusals.
  throw Object.assign(new Error(detail || SAID[response.status] || `Exchequer could not do that (${response.status}).`), { status: response.status })
}

/** The signed-in officer, or { demo: true } with no session. */
export const fetchMe = () => call('/auth/me')
export const signIn = (email, password) => call('/auth/login', 'POST', { email, password })
export const signOut = () => call('/auth/logout', 'POST')
export const changePassword = (current, next) => call('/auth/password', 'POST', { current_password: current, new_password: next })

export const fetchUnits = () => call('/admin/units')
export const createUnit = (name) => call('/admin/units', 'POST', { name })
export const fetchOfficers = () => call('/admin/officers')
/** { officer, temporary_password }: the password is shown this once. */
export const createOfficer = (fields) => call('/admin/officers', 'POST', fields)
/** Only the fields given change; { reset_password: true } returns a new temporary password. */
export const updateOfficer = (id, changes) => call(`/admin/officers/${id}`, 'PATCH', changes)
