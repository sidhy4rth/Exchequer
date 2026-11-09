// The shape of a transaction hash, checked on the device: nothing is sent.
// Tron and Ethereum-style hashes are both 64 hex characters. Ethereum-style
// ones are usually written with 0x and Tron's rarely are, but Exchequer takes
// either with or without it, so 0x only changes which networks come first.
// The networks are the ones Exchequer traces.
const EVM = ['Ethereum', 'BNB Smart Chain', 'Polygon', 'Arbitrum']

// What a copy from a phone can carry along, all ignored: zero-width,
// direction and soft hyphen marks, and spaces and line breaks (\s, which
// also covers U+FEFF and no-break spaces).
const INVISIBLE = /[\u00AD\u200B-\u200F\u202A-\u202E\u2060-\u2064\u2066-\u2069]/g
const ADDRESS = /^(T[1-9A-HJ-NP-Za-km-z]{33}|0x[0-9a-f]{40})$/i
// One hash with words or a link around it, as in "TxID: …" or an explorer's
// address. No lookbehind: iPhones before iOS 16.4 cannot parse one.
const INSIDE = /(?:^|[^0-9a-f])((?:0x)?[0-9a-f]{64})(?![0-9a-f])/gi
const runsIn = (text) => [...text.matchAll(INSIDE)].map((match) => match[1].toLowerCase())

const found = (hash) => ({
  ok: true, hash, networks: hash.startsWith('0x') ? [...EVM, 'Tron'] : ['Tron', ...EVM],
})

/**
 * {ok: true, hash, networks} for something shaped like a transaction hash,
 * most likely network first, with extracted: true when it was taken out of
 * words or a link; otherwise {ok: false, reason}: 'empty', 'address',
 * 'chars', or 'length' (with the length, not counting 0x).
 */
export function checkHash(input) {
  const raw = String(input ?? '').replace(INVISIBLE, '')
  const text = raw.replace(/\s/g, '')
  if (!text) return { ok: false, reason: 'empty' }
  if (ADDRESS.test(text)) return { ok: false, reason: 'address' }
  const prefixed = /^0x/i.test(text)
  const hex = prefixed ? text.slice(2) : text
  if (/[^0-9a-f]/i.test(hex)) {
    const runs = new Set(runsIn(raw).length ? runsIn(raw) : runsIn(text))
    return runs.size === 1 ? { ...found([...runs][0]), extracted: true } : { ok: false, reason: 'chars' }
  }
  if (hex.length !== 64) return { ok: false, reason: 'length', length: hex.length }
  return found(text.toLowerCase())
}
