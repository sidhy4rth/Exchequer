import { afterEach, describe, expect, it, vi } from 'vitest'
import { checkPayment, myCase, sendComplaint, sendMessage, signIn, signOut, waitText } from './api.js'
import { OFFLINE, fakeServer } from './test/server.js'

afterEach(() => vi.unstubAllGlobals())

describe('api', () => {
  it('asks only this site, with the header the functions require and the session cookie', async () => {
    const server = fakeServer({
      'POST /api/complaints': [201, { reference: 'EXQ-AAAA2222', tracking_code: 'ABCD-EFGH-JKMN' }],
      'POST /api/session': [200, { signed_in: true }],
      'GET /api/my-case': [200, { reference: 'EXQ-AAAA2222' }],
      'POST /api/messages': [201, { sent: true }],
      'POST /api/logout': [200, { signed_in: false }],
      'GET /api/payment': [200, { payment: { amount: '1' } }],
    })
    expect(await sendComplaint({ ncrp: '31234567890123' })).toEqual(
      { ok: true, status: 201, data: { reference: 'EXQ-AAAA2222', tracking_code: 'ABCD-EFGH-JKMN' } })
    await signIn('31234567890123', 'ABCD-EFGH-JKMN')
    await myCase()
    await sendMessage('Thank you')
    await signOut()
    await checkPayment('tron', 'ab'.repeat(32))
    expect(server.calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      'POST /api/complaints', 'POST /api/session', 'GET /api/my-case', 'POST /api/messages', 'POST /api/logout',
      `GET /api/payment?network=tron&hash=${'ab'.repeat(32)}`])
    for (const call of server.calls) {
      expect(call.headers['X-Citizen']).toBe('1')
      expect(call.credentials).toBe('same-origin')
      if (call.method === 'POST') expect(call.headers['Content-Type']).toBe('application/json')
    }
    expect(server.calls[1].body).toEqual({ ncrp: '31234567890123', code: 'ABCD-EFGH-JKMN' })
    expect(server.calls[3].body).toEqual({ body: 'Thank you' })
  })

  it('hands back the server\'s own words when it refuses, and how long to wait', async () => {
    fakeServer({
      'POST /api/session': [429, { error: 'Too many wrong tries. Please wait a little and try again.' },
        { 'Retry-After': '120' }],
      'GET /api/my-case': [401, { error: 'Please sign in again.' }],
    })
    expect(await signIn('31234567890123', 'X')).toEqual({ ok: false, status: 429, retryAfter: 120,
      error: 'Too many wrong tries. Please wait a little and try again.' })
    expect(await myCase()).toEqual({ ok: false, status: 401, error: 'Please sign in again.' })
  })

  it('says plainly when the site cannot be reached or answers with something unreadable', async () => {
    fakeServer({ 'GET /api/my-case': OFFLINE, 'POST /api/logout': [502, '<html>Bad gateway</html>'] })
    expect(await myCase()).toEqual({ ok: false, status: 0,
      error: 'We could not reach the site. Check your connection and try again.' })
    expect(await signOut()).toEqual({ ok: false, status: 502, error: 'Something went wrong. Please try again later.' })
  })

  it('says how long to wait in words', () => {
    expect(waitText(5)).toBe('in about a minute')
    expect(waitText(60)).toBe('in about a minute')
    expect(waitText(150)).toBe('in about 3 minutes')
    expect(waitText(3600)).toBe('in about an hour')
    expect(waitText(undefined)).toBe('a little later')
  })
})
