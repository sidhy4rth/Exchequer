import { describe, expect, it } from 'vitest'
import { NCRP_NOTE, ncrpNote } from './ncrp'

describe('ncrpNote (SOP for NCRP-CFCFRMS 6.1(d), 6.2(c))', () => {
  it('says nothing for a 14-digit portal or 1930 number', () => {
    for (const n of ['21234567890123', '31234567890123', '2123 4567 8901 23', '3123-4567-8901-23']) expect(ncrpNote(n)).toBe('')
  })
  it('notes 13 digits, a 5 at the start, and other shapes', () => {
    for (const n of ['2123456789012', '51234567890123', '212345678901234', '1234567890', 'ABC12345']) expect(ncrpNote(n)).toBe(NCRP_NOTE)
  })
  it('says nothing when nothing is given, and never repeats the number', () => {
    expect(ncrpNote('')).toBe('')
    expect(ncrpNote(undefined)).toBe('')
    expect(ncrpNote('51234567890123')).not.toContain('51234567890123')
  })
})
