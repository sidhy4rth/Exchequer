// A small CSV reader for bulk intake: RFC 4180 quoting, any line ending, and
// forgiving header names, because the file comes from whatever a bank or the
// reporting portal exported.

const SEPARATORS = [',', ';', '\t']
const SEPARATOR_NAMES = { ',': 'comma', ';': 'semicolon', '\t': 'tab' }

function stripBom(text) {
  return String(text ?? '').replace(/^﻿/, '')
}

/** Excel's 'sep=X' first line, as [separator, length of the line with its break], or null. */
function sepLine(src) {
  const m = /^sep=([^"\r\n])(\r\n|\r|\n|$)/i.exec(src)
  return m ? [m[1], m[0].length] : null
}

/**
 * The one separator this file uses: Excel's 'sep=' line if there is one, else
 * whichever of ',', ';' and tab is most common outside quotes on the first
 * line (a comma on a tie or when there is none).
 */
export function detectDelimiter(text) {
  const src = stripBom(text)
  const sep = sepLine(src)
  if (sep) return sep[0]
  const counts = { ',': 0, ';': 0, '\t': 0 }
  let quoted = false
  let blank = true
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i]
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') i += 1
      else if (ch === '"') { quoted = false; blank = false }
    } else if (ch === '"' && blank) quoted = true
    else if (ch === '\n' || ch === '\r') break
    else if (ch in counts) { counts[ch] += 1; blank = true }
    else if (ch.trim() !== '') blank = false
  }
  return SEPARATORS.reduce((best, s) => (counts[s] > counts[best] ? s : best), ',')
}

/**
 * The file's records, split on its one separator: [{cells, line}], with the
 * 1-based file line each record starts on. Blank records are dropped. A
 * record whose quote is never closed is marked unclosed.
 */
export function readCells(text) {
  let src = stripBom(text)
  const delimiter = detectDelimiter(src)
  let line = 1
  const sep = sepLine(src)
  if (sep) { src = src.slice(sep[1]); line = 2 }
  const records = []
  let row = []
  let cell = ''
  let quoted = false
  let start = line
  const end = () => {
    row.push(cell)
    if (row.some((c) => c.trim() !== '')) records.push({ cells: row, line: start, ...(quoted ? { unclosed: true } : {}) })
    row = []; cell = ''
  }
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i]
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') { cell += '"'; i += 1 } else if (ch === '"') quoted = false
      else {
        if (ch === '\n' || (ch === '\r' && src[i + 1] !== '\n')) line += 1
        cell += ch
      }
    } else if (ch === '"' && cell.trim() === '') { quoted = true; cell = '' }
    else if (ch === delimiter) { row.push(cell); cell = '' }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && src[i + 1] === '\n') i += 1
      end(); line += 1; start = line
    } else cell += ch
  }
  if (cell !== '' || row.length || quoted) end()
  return { records, delimiter }
}

/** Rows of cells. Quoted cells may hold the separator, quotes ("") and newlines. */
export function parseCsv(text) {
  return readCells(text).records.map((r) => r.cells)
}

// A cell that is an EVM or Tron address: a first row holding one is data, not a header.
const ADDRESS_SHAPE = /^(0x[0-9a-fA-F]{40}|T[1-9A-HJ-NP-Za-km-z]{33})$/
// Columns that are never the suspect's address, whatever else they say.
const NEVER = /\b(victim|complainant|customer|sender|from)\b/
// Address columns, best first. More than one match in the best tier that has
// any is refused rather than guessed.
const ADDRESS_TIERS = [
  (h) => /\b(suspect|fraudster|scammer|accused|reported)\b/.test(h) && /\b(address|wallet)\b/.test(h),
  (h) => h === 'address',
  (h) => ['wallet address', 'wallet', 'crypto address', 'beneficiary address'].includes(h),
]
// The other fields, each alias in priority order.
const FIELDS = {
  chain: ['chain', 'network', 'blockchain'],
  asset: ['asset', 'token', 'currency', 'coin'],
  direction: ['direction'],
  depth: ['depth', 'max depth', 'hops'],
  reference: ['reference', 'ref', 'acknowledgement no', 'acknowledgement', 'ack no', 'complaint no', 'complaint number', 'complaint', 'fir'],
}

const normalise = (h) => h.trim().toLowerCase().replace(/[._]+/g, ' ').replace(/\s+/g, ' ')
const named = (c) => `'${c.text}' (column ${c.column})`
const listed = (cs) => cs.length === 2 ? `${named(cs[0])} and ${named(cs[1])}`
  : `${cs.slice(0, -1).map(named).join(', ')} and ${named(cs[cs.length - 1])}`

/** The header's field -> column index, or an error that names the columns at fault. */
function mapHeader(cells) {
  const head = cells.map((c, i) => ({ text: c.trim(), norm: normalise(c), column: i + 1 }))
  let address = null
  for (const tier of ADDRESS_TIERS) {
    const hits = head.filter((h) => h.norm && !NEVER.test(h.norm) && tier(h.norm))
    if (hits.length > 1) {
      return { error: `${hits.length === 2 ? 'Two' : hits.length} columns could be the suspect's address: ${listed(hits)}. `
        + "Rename the suspect's column to 'suspect address', or delete the other." }
    }
    if (hits.length === 1) { address = hits[0]; break }
  }
  if (!address) return { error: "has no address column. Name the suspect's column 'suspect address'." }
  const index = { address: address.column - 1 }
  const mapped = [{ field: 'address', header: address.text, column: address.column }]
  for (const [field, names] of Object.entries(FIELDS)) {
    for (const name of names) {
      const hits = head.filter((h) => h !== address && h.norm === name)
      if (hits.length > 1) {
        return { error: `Two columns are named '${hits[0].text}' (columns ${hits.slice(0, -1).map((h) => h.column).join(', ')} and ${hits[hits.length - 1].column}). Delete or rename one.` }
      }
      if (hits.length === 1) {
        index[field] = hits[0].column - 1
        mapped.push({ field, header: hits[0].text, column: hits[0].column })
        break
      }
    }
  }
  const used = new Set(mapped.map((m) => m.column))
  const unused = head.filter((h) => h.text && !used.has(h.column)).map((h) => ({ header: h.text, column: h.column }))
  return { index, columns: { mapped, unused } }
}

/**
 * Complaint rows from CSV text, and what stops any row from being sent.
 *
 * Returns {rows, errors, columns, delimiter}: rows are [{line, address, chain,
 * asset, direction, depth, reference}], errors are [{line, error}] by file
 * line, and columns says which column became which field. With a header row,
 * columns are matched by name; a first row holding an address is data, read
 * as address[, chain]. Every row must have as many cells as the first row,
 * because one stray separator moves every later field into the wrong column.
 */
export function readComplaints(text) {
  const { records, delimiter } = readCells(text)
  const out = { rows: [], errors: [], columns: { mapped: [], unused: [] }, delimiter }
  if (records.length === 0) return out
  const first = records[0]
  const hasHeader = !first.cells.some((c) => ADDRESS_SHAPE.test(c.trim()))
  let index
  if (hasHeader) {
    const header = mapHeader(first.cells)
    if (header.error) { out.errors.push({ line: first.line, error: header.error }); return out }
    index = header.index
    out.columns = header.columns
  } else {
    index = { address: 0 }
    out.columns.mapped.push({ field: 'address', header: null, column: 1 })
    if (first.cells.length > 1) {
      index.chain = 1
      out.columns.mapped.push({ field: 'chain', header: null, column: 2 })
    }
  }
  const width = first.cells.length
  for (const r of hasHeader ? records.slice(1) : records) {
    if (r.unclosed) { out.errors.push({ line: r.line, error: 'opens a quote (") that is never closed.' }); continue }
    if (r.cells.length !== width) {
      out.errors.push({ line: r.line, error: `has ${r.cells.length} cells; the ${hasHeader ? 'header' : 'first row'} has ${width}. `
        + `A ${SEPARATOR_NAMES[delimiter] ?? `'${delimiter}'`} inside a cell must be in quotes ("…"), or every column after it shifts.` })
      continue
    }
    const row = { line: r.line }
    for (const [field, at] of Object.entries(index)) {
      const v = r.cells[at].trim()
      if (v) row[field] = v
    }
    if (!row.address) { out.errors.push({ line: r.line, error: 'has no address.' }); continue }
    out.rows.push(row)
  }
  return out
}
