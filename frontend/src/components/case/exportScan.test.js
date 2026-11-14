import { describe, expect, it } from 'vitest'
import { ExportScanner, SEED_WORDS, encodingOf, scanFile } from './exportScan'

// Addresses and hashes that already appear in the repository: DEMO.md, the
// EIP-55 vectors in backend/tests/test_address_checksum.py, and the contract
// fixtures in backend/tests/fixtures/contract/. None is invented.
const EVM = '0x7c3e9bab6715e4040f013e865b193b0209642e36' // DEMO.md
const EVM_MIXED = '0xdAC17F958D2ee523a2206206994597C13D831ec7' // USDT, EIP-55
const TRON = 'THWYhwUQnBcKpwSxaXjqv18RPtSoK4C5Ph' // DEMO.md
const TX_EVM = '0x5181ebcc322cf2d712d8f8c950a927621f179e7d49bb2d345cdf301cbf3f4c82' // deposit_inferred.json
const TX_TRON = '657b48486605d40ee51f6e36df243ed0fb9a1460b5a53f61080d51eaadf6b1d5' // exchange_wallet.json
// The first twelve words of the list, as backend/tests/test_identifiers.py uses:
// not a valid mnemonic (its checksum bits are wrong), and no one's seed.
const SEED = 'abandon ability able about above absent absorb abstract absurd abuse access accident'
const SEED_SET = SEED.split(' ')

function scan(...pieces) {
  const s = new ExportScanner()
  pieces.forEach((p) => s.push(p))
  return s.finish()
}

describe('addresses and hashes', () => {
  it('finds a valid address of each family and a hash of each shape, by line', () => {
    const text = [
      'date,from,message',
      `2024-03-01,Rahul,"send it to ${EVM} please"`,
      `2024-03-01,Rahul,"or the Tron one: ${TRON}"`,
      `<note>USDT contract ${EVM_MIXED}</note>`,
      `{"tx": "${TX_EVM}", "other": "${TX_TRON}"}`,
      `again ${EVM.toUpperCase().replace('0X', '0x')}`,
    ].join('\n')
    const out = scan(text)
    expect(out.lines).toBe(6)
    expect(out.addresses.map((a) => [a.value, a.kind, a.lines, a.count])).toEqual([
      [EVM, 'evm', [2, 6], 2],
      [TRON, 'tron', [3], 1],
      [EVM_MIXED, 'evm', [4], 1],
    ])
    expect(out.hashes.map((h) => [h.value, h.kind, h.lines])).toEqual([[TX_EVM, 'hex0x', [5]], [TX_TRON, 'hex', [5]]])
  })

  it('ignores near misses: a bad checksum, a wrong length, a value glued to more text', () => {
    const text = [
      '0x5AAeb6053F3E94C9b9A09f33669435E7Ef1BeAed', // one letter's case changed
      EVM.slice(0, -1), // 39 hex
      `${EVM}a`, // 41 hex
      `${TRON.slice(0, 10)}d${TRON.slice(11)}`, // one character changed
      TRON.slice(0, -1),
      TX_TRON.slice(0, -1), // 63 hex
      `${TX_EVM}0`, // 65 hex
      `x${TRON}`,
    ].join('\n')
    const out = scan(text)
    expect(out.addresses).toEqual([])
    expect(out.hashes).toEqual([])
  })

  it('joins a value cut between two pieces', () => {
    const out = scan(`to ${EVM.slice(0, 20)}`, `${EVM.slice(20)} and `, TX_TRON.slice(0, 5), `${TX_TRON.slice(5)}\n`)
    expect(out.addresses.map((a) => a.value)).toEqual([EVM])
    expect(out.hashes.map((h) => h.value)).toEqual([TX_TRON])
    expect(out.lines).toBe(1)
  })

  it('keeps at most `most` distinct values and counts the rest', () => {
    const s = new ExportScanner({ most: 1 })
    s.push(`${EVM} ${TRON} ${TX_EVM}`)
    const out = s.finish()
    expect(out.addresses).toHaveLength(1)
    expect(out.hashes).toHaveLength(0)
    expect(out.dropped).toBe(2)
  })
})

describe('seed-phrase-shaped runs', () => {
  it('reports twelve list words in a row by line and count only', () => {
    const out = scan(`chat log\nmy backup words: ${SEED}\nthanks`)
    expect(out.seeds).toEqual([{ line: 2, endLine: 2, words: 12 }])
    expect(JSON.stringify(out)).not.toMatch(new RegExp(SEED_SET.join('|')))
  })

  it('finds a numbered backup written one word a line, across pieces', () => {
    const numbered = SEED_SET.map((w, i) => `${i + 1}. ${w}`).join('\n')
    const out = scan('Notes\n', numbered.slice(0, 50), numbered.slice(50), '\nOK saved')
    expect(out.seeds).toEqual([{ line: 2, endLine: 13, words: 12 }])
  })

  it('counts a longer run whole', () => {
    expect(scan(`${SEED} ${SEED}`).seeds).toEqual([{ line: 1, endLine: 1, words: 24 }])
  })

  it('stays silent on ordinary prose full of list words', () => {
    const prose = [
      'I will meet you at the office about the account balance after lunch.',
      'Then we can review the market and decide what to buy, because the price may change soon.',
      'Please bring the paper, a pencil and your phone; the train leaves at seven from the north station.',
      'Remember the ticket, the address of the hotel and the coffee you promised.',
    ].join('\n')
    const out = scan(prose)
    expect(out.seeds).toEqual([])
    expect(out.addresses).toEqual([])
  })

  it('a run of eleven is not reported, and any other word ends a run', () => {
    expect(scan(SEED_SET.slice(0, 11).join(' ')).seeds).toEqual([])
    expect(scan([...SEED_SET.slice(0, 6), 'the', ...SEED_SET.slice(6)].join(' ')).seeds).toEqual([])
    expect(SEED_WORDS).toBe(12)
  })
})

describe('reading a file', () => {
  it('reads a large file in pieces and hands the page back between them', async () => {
    const line = `${'hello world, nothing to see here. '.repeat(3)}\n`
    const body = `${line.repeat(20000)}${EVM}\n${line.repeat(20000)}${SEED}\n`
    const file = new Blob([body])
    let ticks = 0
    const clock = setInterval(() => { ticks += 1 }, 0)
    const progress = []
    const out = await scanFile(file, { chunk: 256 * 1024, onProgress: (p) => progress.push(p) })
    clearInterval(clock)
    expect(file.size).toBeGreaterThan(4_000_000)
    expect(progress.length).toBeGreaterThan(15)
    expect(progress[progress.length - 1]).toBe(1)
    expect(ticks).toBeGreaterThan(0) // timers ran while the scan was going
    expect(out.addresses.map((a) => [a.value, a.lines])).toEqual([[EVM, [20001]]])
    expect(out.seeds).toEqual([{ line: 40002, endLine: 40002, words: 12 }])
    expect(out.lines).toBe(40002)
    expect(out.bytes).toBe(file.size)
  })

  it('stops when asked', async () => {
    const stop = new AbortController()
    stop.abort()
    await expect(scanFile(new Blob(['x'.repeat(10)]), { signal: stop.signal })).rejects.toThrow('Stopped')
  })

  it('reads UTF-16 with a byte-order mark, and says when a file looks binary', async () => {
    const units = new Uint16Array([0xfeff, ...[...`to ${TRON}\n`].map((c) => c.charCodeAt(0))])
    const out = await scanFile(new Blob([units]))
    expect(out.addresses.map((a) => a.value)).toEqual([TRON])
    expect(out.binary).toBe(false)
    expect(encodingOf(new Uint8Array([1, 0, 0, 0, 2, 0, 0, 0])).binary).toBe(true)
    expect(encodingOf(new TextEncoder().encode('plain text')).binary).toBe(false)
  })

  it('drops a single enormous value instead of holding it', () => {
    const s = new ExportScanner()
    s.push('start ')
    for (let i = 0; i < 3; i++) s.push('A'.repeat(600 * 1024))
    s.push(` ${TRON}\n`)
    const out = s.finish()
    expect(out.addresses.map((a) => a.value)).toEqual([TRON])
  })
})
