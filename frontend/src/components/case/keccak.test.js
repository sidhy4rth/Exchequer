import { describe, expect, it } from 'vitest'
import { keccak256Hex } from './keccak'

// The vectors backend/tests/test_address_checksum.py holds keccak.py to.
describe('keccak256Hex', () => {
  it('matches the known vectors', () => {
    expect(keccak256Hex(new Uint8Array())).toBe('c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470')
    expect(keccak256Hex(new TextEncoder().encode('abc'))).toBe('4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45')
  })

  it('pads across a block boundary', () => {
    // 136 bytes fill one block exactly, so the padding takes a second: same length out, a different hash.
    const a = keccak256Hex(new Uint8Array(135))
    const b = keccak256Hex(new Uint8Array(136))
    expect(a).toMatch(/^[0-9a-f]{64}$/)
    expect(b).toMatch(/^[0-9a-f]{64}$/)
    expect(a).not.toBe(b)
  })
})
