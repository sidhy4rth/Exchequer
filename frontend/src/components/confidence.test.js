import { describe, expect, it } from 'vitest'
import { bandLabel, bandOf, validationLine } from './confidence'

describe('bandOf', () => {
  it('uses the same thresholds as backend/app/scoring.py', () => {
    expect(bandOf(1)).toBe('high')
    expect(bandOf(0.75)).toBe('high')
    expect(bandOf(0.7499)).toBe('moderate')
    expect(bandOf(0.5)).toBe('moderate')
    expect(bandOf(0.25)).toBe('low')
    expect(bandOf(0.1)).toBe('very low')
    expect(bandOf(null)).toBeNull()
  })

  it('labels a band for display', () => {
    expect(bandLabel('very low')).toBe('Very low')
    expect(bandLabel(null)).toBe('')
  })
})

describe('validationLine', () => {
  it('states both hit rates for a measured pattern', () => {
    expect(validationLine('peel_chain')).toMatch(/2 of 32 documented fraud wallets and 2 of 47 ordinary ones/)
  })

  it('says nothing for a pattern nobody measured', () => {
    expect(validationLine('something_new')).toBeNull()
  })
})
