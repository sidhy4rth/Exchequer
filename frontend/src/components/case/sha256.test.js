import { createHash } from 'node:crypto'
import { describe, expect, it } from 'vitest'
import { Sha256, hashFile } from './sha256'

// The chunked SHA-256 must give exactly the hash any other tool gives: it is
// what a court compares with the forensic tool's own report.
const node = (bytes) => createHash('sha256').update(bytes).digest('hex')

// Fixed, varied test bytes (xorshift32 from a seed), the same on every run, so a
// failure can be reproduced. Not random numbers for any security use.
function bytesOf(n, seed = 0x9e3779b9) {
  const out = new Uint8Array(n)
  let x = seed >>> 0
  for (let i = 0; i < n; i++) {
    x ^= x << 13; x >>>= 0
    x ^= x >>> 17
    x ^= x << 5; x >>>= 0
    out[i] = x & 0xff
  }
  return out
}

describe('Sha256', () => {
  it('gives the standard answers for the textbook inputs', () => {
    expect(new Sha256().hex()).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
    expect(new Sha256().update(new TextEncoder().encode('abc')).hex())
      .toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
  })

  it('agrees with node at every padding boundary', () => {
    for (const n of [1, 55, 56, 57, 63, 64, 65, 119, 120, 127, 128, 129, 1000]) {
      const bytes = bytesOf(n)
      expect(new Sha256().update(bytes).hex(), `length ${n}`).toBe(node(bytes))
    }
  })

  it('gives the same hash however the bytes are split into updates', () => {
    const bytes = bytesOf(10_000)
    const whole = node(bytes)
    for (const cut of [1, 3, 63, 64, 65, 4096]) {
      const h = new Sha256()
      for (let at = 0; at < bytes.length; at += cut) h.update(bytes.subarray(at, at + cut))
      expect(h.hex(), `pieces of ${cut}`).toBe(whole)
    }
  })
})

describe('hashFile', () => {
  it('hashes a file in chunks, reports progress and matches node', async () => {
    const bytes = bytesOf(300_001)
    const seen = []
    const hex = await hashFile(new Blob([bytes]), { chunk: 65_536, onProgress: (p) => seen.push(p) })
    expect(hex).toBe(node(bytes))
    expect(seen.length).toBe(5)
    expect(seen.at(-1)).toBe(1)
  })

  it('stops when asked', async () => {
    const stop = new AbortController()
    stop.abort()
    await expect(hashFile(new Blob([bytesOf(10)]), { signal: stop.signal })).rejects.toThrow('Stopped')
  })
})
