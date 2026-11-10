import { describe, expect, it } from 'vitest'
import { plain, plainSentence } from './text'

describe('plain (r2-g2-frontend-intake-rendering-3-3)', () => {
  it('removes characters that print nothing', () => {
    expect(plain('Bin\u200Bance')).toBe('Binance')
    expect(plain('Bin\u00ADance\u2060')).toBe('Binance')
    expect(plain('\u202Eecnanib\u202C')).toBe('ecnanib') // an override cannot flip it on screen
    expect(plain('\u2066Binance\u2069 Hot')).toBe('Binance Hot')
  })

  it('keeps a name on one line', () => {
    expect(plain('Binance\nFINDING:\tfake')).toBe('Binance FINDING: fake')
    expect(plain('  OKX   Hot  ')).toBe('OKX Hot')
  })

  it('reads full-width and compatibility forms as the name they show', () => {
    expect(plain('\uFF22\uFF49\uFF4E\uFF41\uFF4E\uFF43\uFF45')).toBe('Binance')
  })

  it('leaves a clean name, a number and a missing value alone', () => {
    expect(plain('Binance 14')).toBe('Binance 14')
    expect(plain(3)).toBe('3')
    expect(plain(null)).toBe(null)
    expect(plain(undefined)).toBe(undefined)
  })
})

describe('plainSentence: Exchequer\'s own sentence that quotes an address', () => {
  it('removes what prints nothing and keeps the sentence on one line', () => {
    expect(plainSentence('Followed at TZ7L\u200B\u202E…9cNz.\nNext')).toBe('Followed at TZ7L…9cNz. Next')
  })

  it('keeps its own punctuation, which plain() would rewrite', () => {
    expect(plainSentence('at TZ7LmC…9cNz.')).toBe('at TZ7LmC…9cNz.')
    expect(plain('at TZ7LmC…9cNz.')).toBe('at TZ7LmC...9cNz.')
    expect(plainSentence(null)).toBe(null)
  })
})
