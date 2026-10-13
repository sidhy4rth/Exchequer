// A small CSV reader for bulk intake: RFC 4180 quoting, any line ending, and
// forgiving header names, because the file comes from whatever a bank or the
// reporting portal exported.

/** Rows of cells. Quoted cells may hold commas, quotes ("") and newlines. */
export function parseCsv(text) {
  const rows = []
  let row = []
  let cell = ''
  let quoted = false
  const src = text.replace(/^﻿/, '')
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i]
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') { cell += '"'; i += 1 } else if (ch === '"') quoted = false
      else cell += ch
    } else if (ch === '"' && cell === '') quoted = true
    else if (ch === ',' || ch === ';' || ch === '\t') { row.push(cell); cell = '' }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && src[i + 1] === '\n') i += 1
      row.push(cell); rows.push(row); row = []; cell = ''
    } else cell += ch
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row) }
  return rows.filter((r) => r.some((c) => c.trim() !== ''))
}

const FIELDS = {
  address: ['address', 'wallet', 'wallet address', 'reported address', 'suspect address', 'crypto address'],
  chain: ['chain', 'network', 'blockchain'],
  asset: ['asset', 'token', 'currency', 'coin'],
  direction: ['direction'],
  depth: ['depth', 'hops', 'max depth', 'max_depth'],
  reference: ['reference', 'ref', 'complaint', 'complaint no', 'complaint number', 'acknowledgement', 'acknowledgement no', 'ack no', 'fir'],
}

/**
 * Complaint rows from CSV text: [{address, chain, asset, direction, depth, reference}].
 * With a header row, columns are matched by name; without one, the first
 * column is the address and the second, if any, the chain.
 */
export function complaintsFromCsv(text) {
  const rows = parseCsv(text)
  if (rows.length === 0) return []
  const head = rows[0].map((h) => h.trim().toLowerCase().replace(/[._]+/g, ' '))
  const index = {}
  for (const [field, names] of Object.entries(FIELDS)) {
    const at = head.findIndex((h) => names.includes(h))
    if (at >= 0) index[field] = at
  }
  const hasHeader = index.address !== undefined
  const body = hasHeader ? rows.slice(1) : rows
  if (!hasHeader) { index.address = 0; if (rows[0].length > 1) index.chain = 1 }
  return body.map((r) => {
    const out = {}
    for (const [field, at] of Object.entries(index)) {
      const v = (r[at] ?? '').trim()
      if (v) out[field] = v
    }
    return out
  }).filter((r) => r.address)
}
