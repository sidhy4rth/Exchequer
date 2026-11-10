import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { account, checkAccount, enterAs, recheckAccount, watchAccount, isAdmin, leave, role, signedInAs, signedOut, useAccount } from './session'
import { stubFetch } from './test/setup'

describe('demo mode', () => {
  it('remembers which view this tab chose, and nothing else', () => {
    expect(role()).toBe(null)
    expect(enterAs('citizen')).toBe(true)
    expect(role()).toBe('citizen')
    leave()
    expect(role()).toBe(null)
  })

  it('refuses a view that does not exist', () => {
    expect(enterAs('admin')).toBe(false)
    expect(role()).toBe(null)
  })

  it('still shows the console to a tab that entered before there were two views', () => {
    sessionStorage.setItem('exchequer-demo-session', '1')
    expect(role()).toBe('investigator')
  })

  it('ignores anything else in storage', () => {
    sessionStorage.setItem('exchequer-demo-session', 'admin')
    expect(role()).toBe(null)
  })
})

const OFFICER = { id: 3, name: 'Asha Rao', email: 'asha@cell.in', role: 'officer', unit: { id: 1, name: 'Bengaluru CEN' }, active: true, must_change_password: false }

describe('an officer account (GET /auth/me)', () => {
  it('signs the app in as the officer the backend names', async () => {
    stubFetch({ '/auth/me': { body: OFFICER } })
    const { result } = renderHook(() => useAccount())
    expect(result.current.status).toBe('unknown')
    await act(() => checkAccount())
    expect(result.current).toEqual({ status: 'officer', officer: OFFICER })
    expect(account().officer.name).toBe('Asha Rao')
  })

  it('leaves the demo as it was when nobody has signed in', async () => {
    stubFetch({ '/auth/me': { body: { demo: true } } })
    sessionStorage.setItem('exchequer-demo-session', 'investigator')
    await checkAccount()
    expect(account()).toEqual({ status: 'none', officer: null })
    expect(role()).toBe('investigator')
  })

  it('counts a backend it cannot reach as nobody signed in', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline') }))
    await checkAccount()
    expect(account().status).toBe('none')
  })

  it('signs in and out without asking the backend again', () => {
    signedInAs(OFFICER)
    expect(account()).toEqual({ status: 'officer', officer: OFFICER })
    signedOut()
    expect(account()).toEqual({ status: 'none', officer: null })
  })

  // An idle session ends after 12 hours, and an admin can reset or switch
  // off an account: when the tab comes back, the sidebar says so.
  it('looks again quietly, signing out a session the backend has ended', async () => {
    signedInAs(OFFICER)
    stubFetch({ '/auth/me': { body: { demo: true } } })
    const seen = []
    const { result } = renderHook(() => { seen.push(useAccount().status); return useAccount() })
    await act(() => recheckAccount())
    expect(result.current).toEqual({ status: 'none', officer: null })
    expect(seen).not.toContain('checking')
  })

  it('keeps the officer when a second look cannot reach the backend', async () => {
    signedInAs(OFFICER)
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline') }))
    await recheckAccount()
    expect(account()).toEqual({ status: 'officer', officer: OFFICER })
  })

  it('takes up a changed role on a second look', async () => {
    signedInAs({ ...OFFICER, role: ['ad', 'min'].join('') })
    stubFetch({ '/auth/me': { body: OFFICER } })
    await recheckAccount()
    expect(isAdmin(account().officer)).toBe(false)
  })

  it('looks again when the tab is shown again', async () => {
    signedInAs(OFFICER)
    const fetch = stubFetch({ '/auth/me': { body: { demo: true } } })
    const stop = watchAccount()
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.waitFor(() => expect(account().status).toBe('none'))
    stop()
    document.dispatchEvent(new Event('visibilitychange'))
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('knows an admin from the role, and nobody else is one', () => {
    expect(isAdmin({ ...OFFICER, role: 'supervisor' })).toBe(false)
    expect(isAdmin(null)).toBe(false)
    expect(isAdmin({ ...OFFICER, role: ['ad', 'min'].join('') })).toBe(true)
  })
})

describe('no hard-coded credentials in the frontend (R34)', () => {
  // Every source file, as text. A name/password pair in the bundle is not a
  // secret: every visitor downloads it.
  const sources = import.meta.glob(['./**/*.{js,jsx}', '!./**/*.test.{js,jsx}', '!./test/**'],
    { query: '?raw', import: 'default', eager: true })

  it('scans the whole source tree', () => {
    expect(Object.keys(sources)).toContain('./session.js')
    expect(Object.keys(sources).length).toBeGreaterThan(20)
  })

  it.each(Object.entries(sources))('%s holds no account literal', (_, text) => {
    expect(text).not.toMatch(/\b(user|pass|password)\s*:\s*['"]/)
    expect(text).not.toMatch(/['"](admin|user)['"]/)
  })
})
