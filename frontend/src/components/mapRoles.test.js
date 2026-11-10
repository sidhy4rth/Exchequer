import { describe, expect, it } from 'vitest'
import { flagCounts, isConfirmedRisk, roleOf } from './mapRoles'
import recordings from '../../../backend/data/recorded_demos.json'

describe('roleOf', () => {
  it('ranks the roles as both maps do', () => {
    expect(roleOf({ is_seed: true, risk_category: 'frozen', flags: ['frozen'] })).toBe('seed')
    expect(roleOf({ risk_category: 'gambling', flags: ['amount_split'] })).toBe('gambling')
    expect(roleOf({ risk_category: 'frozen', flags: ['amount_split', 'frozen'] })).toBe('risk')
    expect(roleOf({ exchange: 'Binance', label: 'Binance-Hot 7' })).toBe('exchange')
    expect(roleOf({ exchange: 'Binance', inferred_exchange: 'Binance' })).toBe('inferred')
    expect(roleOf({ is_router: true, flags: ['peel_chain'] })).toBe('service')
    expect(roleOf({ flags: ['amount_split'] })).toBe('flagged')
    expect(roleOf({ flags: [] })).toBe('node')
    expect(roleOf(null)).toBe('node')
  })
})

describe('flagCounts', () => {
  it('counts a pattern without a list as possible, and a list hit as confirmed', () => {
    const graph = {
      nodes: [
        { is_seed: true, risk_category: 'frozen' }, // the reported wallet, confirmed by a list
        { risk_category: 'sanctioned', flags: ['peel_chain'] }, // confirmed outranks the pattern
        { risk_category: 'gambling' }, // an attribution, not a risk
        { flags: ['amount_split'] },
        { flags: ['peel_chain'], exchange: 'Binance' }, // an exchange is not a flag
        { flags: [] },
      ],
    }
    expect(flagCounts(graph)).toEqual({ possible: 1, confirmed: 2 })
    expect(isConfirmedRisk({ risk_category: 'gambling' })).toBe(false)
    expect(flagCounts(undefined)).toEqual({ possible: 0, confirmed: 0 })
  })

  it('finds 8 possible flags and 2 confirmed in recorded case 11', () => {
    const { graph } = recordings.find((r) => r.demo === 11).result
    expect(flagCounts(graph)).toEqual({ possible: 8, confirmed: 2 })
  })
})
