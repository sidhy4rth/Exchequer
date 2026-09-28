import { describe, expect, it } from 'vitest'
import { role, signIn, signOut } from './session'

describe('demo sign-in', () => {
  it('admits each door only with its own account', () => {
    expect(signIn('investigator', 'user', 'user')).toBe(false)
    expect(signIn('citizen', 'user', 'user')).toBe(true)
    expect(role()).toBe('citizen')
  })

  it('tolerates stray spaces in the name but not in the password', () => {
    expect(signIn('investigator', '  admin ', 'admin')).toBe(true)
    signOut()
    expect(signIn('investigator', 'admin', 'admin ')).toBe(false)
    expect(role()).toBe(null)
  })

  it('still admits a tab signed in before there were two doors', () => {
    sessionStorage.setItem('exchequer-demo-session', '1')
    expect(role()).toBe('investigator')
  })

  it('ignores anything else in storage', () => {
    sessionStorage.setItem('exchequer-demo-session', 'admin')
    expect(role()).toBe(null)
  })
})
