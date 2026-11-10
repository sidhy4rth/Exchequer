import { describe, expect, it, vi } from 'vitest'
import {
  changePassword, createOfficer, createUnit, fetchMe, fetchOfficers, fetchUnits, signIn, signOut, updateOfficer,
} from './accounts'

// Officer accounts (backend/app/routes/accounts.py). Every call that changes
// something carries the X-Exchequer-Request header the backend asks for, so a
// form on another site cannot drive it; errors come back in plain words.

function stub(status, body) {
  const fetch = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}
const sent = (fetch) => {
  const [url, init = {}] = fetch.mock.calls[0]
  return { url: String(url), method: init.method ?? 'GET', headers: init.headers ?? {}, body: init.body && JSON.parse(init.body) }
}

describe('account calls', () => {
  const changes = [
    ['signIn', () => signIn(' a@b.in ', 'pw'), 'POST', '/auth/login', { email: ' a@b.in ', password: 'pw' }],
    ['signOut', () => signOut(), 'POST', '/auth/logout', undefined],
    ['changePassword', () => changePassword('old', 'a-new-password'), 'POST', '/auth/password', { current_password: 'old', new_password: 'a-new-password' }],
    ['createUnit', () => createUnit('Cyber cell'), 'POST', '/admin/units', { name: 'Cyber cell' }],
    ['createOfficer', () => createOfficer({ email: 'a@b.in', name: 'A', unit_id: 1, role: 'officer' }), 'POST', '/admin/officers', { email: 'a@b.in', name: 'A', unit_id: 1, role: 'officer' }],
    ['updateOfficer', () => updateOfficer(7, { role: 'supervisor' }), 'PATCH', '/admin/officers/7', { role: 'supervisor' }],
  ]

  it.each(changes)('%s sends the request header the backend checks', async (_, call, method, path, body) => {
    const fetch = stub(200, {})
    await call()
    const req = sent(fetch)
    expect(req.method).toBe(method)
    expect(req.url.endsWith(path)).toBe(true)
    expect(req.headers['X-Exchequer-Request']).toBe('1')
    expect(req.body).toEqual(body)
  })

  it.each([['fetchMe', fetchMe, '/auth/me'], ['fetchUnits', fetchUnits, '/admin/units'], ['fetchOfficers', fetchOfficers, '/admin/officers']])(
    '%s reads with a plain GET', async (_, call, path) => {
      const fetch = stub(200, {})
      await call()
      expect(sent(fetch)).toMatchObject({ method: 'GET' })
      expect(sent(fetch).url.endsWith(path)).toBe(true)
    })

  it("passes on the backend's own words when it refuses", async () => {
    stub(401, { detail: 'That e-mail and password do not match an active account.' })
    await expect(signIn('a@b.in', 'x')).rejects.toThrow('That e-mail and password do not match an active account.')
  })

  it('says what went wrong in plain words when the backend gives none', async () => {
    stub(403, {})
    await expect(fetchUnits()).rejects.toThrow('Only an admin can do this.')
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    await expect(signIn('a@b.in', 'x')).rejects.toThrow('Could not reach Exchequer. Check the connection and try again.')
  })

  // main.py's handler passes Pydantic's own msg ("String should match
  // pattern '^\\s*[^@...'"); the field and the kind of mistake say it plainly.
  it.each([
    [[{ loc: ['body', 'email'], msg: "String should match pattern '^\\s*[^@\\s]+@'", type: 'string_pattern_mismatch' }], 'Check the e-mail address.'],
    [[{ loc: ['body', 'name'], msg: 'String should have at most 120 characters', type: 'string_too_long' }], 'The name is too long.'],
    [[{ loc: ['body', 'name'], msg: 'String should have at least 1 character', type: 'string_too_short' }], 'Fill in the name.'],
    [[{ loc: ['body', 'new_password'], msg: 'String should have at least 12 characters', type: 'string_too_short' }], 'Use at least 12 characters.'],
    [[{ loc: ['body', 'unit_id'], msg: 'Field required', type: 'missing' }, { loc: ['body', 'email'], msg: 'x', type: 'string_pattern_mismatch' }],
      'Fill in the unit. Check the e-mail address.'],
    [[{ loc: ['body'], msg: 'JSON decode error', type: 'json_invalid' }], 'Check what you entered and try again.'],
  ])('reads a validation list in plain words (%#)', async (detail, said) => {
    stub(422, { detail })
    const failed = await createOfficer({}).catch((e) => e)
    expect(failed.message).toBe(said)
    expect(failed.message).not.toMatch(/String should|pattern/)
  })

  it('says which refusal it was, so a page can tell an ended session', async () => {
    stub(401, { detail: 'Sign in first.' })
    await expect(fetchOfficers()).rejects.toMatchObject({ status: 401, message: 'Sign in first.' })
  })
})
