import { describe, expect, it } from 'vitest'
import { BIP39, SHA256, WORDS } from './bip39English'
import { Sha256 } from './sha256'

describe('the BIP-39 English wordlist', () => {
  it('is the bitcoin/bips file, word for word (SHA-256 pinned)', () => {
    const file = new TextEncoder().encode(`${WORDS.join('\n')}\n`)
    expect(new Sha256().update(file).hex()).toBe(SHA256)
    expect(SHA256).toBe('2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda')
  })

  it('has 2048 distinct lower-case words', () => {
    expect(WORDS).toHaveLength(2048)
    expect(BIP39.size).toBe(2048)
    expect(WORDS.every((w) => /^[a-z]{3,8}$/.test(w))).toBe(true)
  })
})
