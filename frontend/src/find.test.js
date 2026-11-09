import { describe, expect, it } from 'vitest'
import { ADDRESS_RE, HASH_RE, findTarget } from './find'

// The header's search box: what it understands from the shape of the text
// alone, and where it sends each kind. Nothing here starts a trace.
const health = {
  default_chain: 'ethereum',
  chains: {
    ethereum: { key: 'ethereum', address_family: 'evm', ready: true, assets: [{ symbol: 'ETH' }, { symbol: 'USDT' }] },
    bsc: { key: 'bsc', address_family: 'evm', ready: true, assets: [{ symbol: 'BNB' }] },
    tron: { key: 'tron', address_family: 'tron', ready: true, assets: [{ symbol: 'TRX' }, { symbol: 'USDT' }] },
  },
}
const EVM = `0x${'ab'.repeat(20)}`
const TRON = 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts'

describe('the search box', () => {
  it('opens a wallet at its trace link, on the default chain for its format', () => {
    expect(findTarget(`  ${EVM} `, health)).toBe(`/trace/${EVM}?chain=ethereum&asset=ETH`)
  })

  it('opens a Tron wallet on Tron, for its USDT', () => {
    expect(findTarget(TRON, health)).toBe(`/trace/${TRON}?chain=tron&asset=USDT`)
  })

  it('still opens a wallet before /chains has answered', () => {
    expect(findTarget(EVM, null)).toBe(`/trace/${EVM}?chain=ethereum&asset=ETH`)
    expect(findTarget(TRON, null)).toBe(`/trace/${TRON}?chain=tron&asset=USDT`)
  })

  it('takes a transaction hash to a new trace, with the hash filled in', () => {
    const evmHash = `0x${'c'.repeat(64)}`
    expect(findTarget(evmHash, health)).toBe(`/trace/new?pay=${evmHash}`)
  })

  it('starts a bare 64-hex hash, which only Tron writes, on Tron', () => {
    const tronHash = 'd'.repeat(64)
    expect(findTarget(tronHash, health)).toBe(`/trace/new?pay=${tronHash}&chain=tron`)
  })

  it('opens a case by its id', () => {
    expect(findTarget('3F2504E0-4F89-41D3-9A0C-0305E82C3301', health)).toBe('/case/3f2504e0-4f89-41d3-9a0c-0305e82c3301')
  })

  it('recognises nothing else', () => {
    for (const text of ['', '   ', 'binance', '0x1234', `${EVM}0`, 'T123', `0x${'c'.repeat(63)}`, '../admin']) {
      expect(findTarget(text, health)).toBeNull()
    }
  })

  it('keeps the trace form\'s own address and hash rules', () => {
    expect(ADDRESS_RE.evm.test(EVM)).toBe(true)
    expect(ADDRESS_RE.tron.test(TRON)).toBe(true)
    expect(HASH_RE.evm.test('c'.repeat(64))).toBe(false)
    expect(HASH_RE.tron.test(`0x${'c'.repeat(64)}`)).toBe(true)
  })
})
