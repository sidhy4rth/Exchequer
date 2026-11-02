import { describe, expect, it } from 'vitest'
import { enterAs, leave, role } from './session'

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
