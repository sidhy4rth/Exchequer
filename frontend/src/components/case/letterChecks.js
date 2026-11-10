// What the Letters tab reads off a draft letter (backend request_letters.py):
// the blanks the officer must fill, and the checks that hold for it. Each
// check is shown only when this letter and case make it true.
import { plain } from '../../text'
import { middle, num } from './format'

const BLANK = /\[_{3,}\]/g

/** The letter as plain runs and blanks: { blank: n, text } is the n-th blank. */
export function pieces(text) {
  const out = []
  let at = 0
  let n = 0
  for (const m of text.matchAll(BLANK)) {
    if (m.index > at) out.push(text.slice(at, m.index))
    out.push({ blank: n++, text: m[0] })
    at = m.index + m[0].length
  }
  if (at < text.length) out.push(text.slice(at))
  return out
}

const ITEM = /^(\d+\.|\([a-z]\)) /           // "4. " or "(a) ": its lines hang under the words
const FIELD = /^[A-Z][A-Za-z]* +: /          // "Amount    : ": its lines wrap under the value
const OWN_LINE = /^(tx |Hop \d+:|Reported address)/
const SOLO = /^(tx |[0-9A-Za-z]{25,}$)/       // a tx or a listed wallet: never wrapped, so nothing flows into it

/** The letter for a proportional font, one entry per paragraph: the server
 * wraps at 95 fixed-width columns, so the lines that carry on a paragraph
 * at its own indent flow back into it. Leading spaces become `indent`; an
 * item's number is its `hang`; the runs of spaces that lined up columns
 * close to one ("From      :" reads "From:"). Items, hops, txs, listed
 * wallets and fields keep their own lines. */
export function lines(text) {
  const out = []
  let open = null // the paragraph still taking lines, and the column they start at
  for (const line of rawLines(text)) {
    const head = typeof line.parts[0] === 'string' ? line.raw : ''
    const item = ITEM.exec(head)
    const own = !line.parts.length || item || FIELD.test(head) || OWN_LINE.test(head) || SOLO.test(head)
    if (open && !own && line.indent === open.col && line.indent > 0) {
      for (const p of [' ', ...line.parts]) add(open.para.parts, p)
      continue
    }
    const para = { indent: line.indent, hang: item ? item[0].length : 0, parts: line.parts }
    out.push(para)
    const field = FIELD.exec(head)
    open = line.parts.length && !SOLO.test(head) ? { para, col: line.indent + (item ? item[0].length : field ? field[0].length : 0) } : null
  }
  return out
}

/** Push a part, running a string on into the string before it. */
function add(parts, p) {
  if (typeof p === 'string' && typeof parts.at(-1) === 'string') parts[parts.length - 1] += p
  else parts.push(p)
}

function rawLines(text) {
  const out = [[]]
  for (const p of pieces(text)) {
    if (typeof p !== 'string') { out.at(-1).push(p); continue }
    p.split('\n').forEach((run, i) => {
      if (i) out.push([])
      if (run) out.at(-1).push(run)
    })
  }
  return out.map((parts) => {
    const indent = typeof parts[0] === 'string' ? /^ */.exec(parts[0])[0].length : 0
    const tidy = parts.map((p, i) => {
      if (typeof p !== 'string') return p
      const run = (i === 0 ? p.slice(indent) : p).replace(/(\S) {2,}/g, '$1 ')
      return i === 0 ? run.replace(/^([A-Z][A-Za-z ]*?) +: /, '$1: ') : run
    })
    return { indent, raw: typeof parts[0] === 'string' ? parts[0].slice(indent) : '', parts: tidy.filter((p) => p !== '') }
  })
}

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1)
const LONG = /\b[0-9A-Za-z]{26,}\b/g // an address or hash: written short in a name

/** Each blank's name, from the words beside it: the note in brackets after
 * it (or on the next line, under a signature), led by the line's own label. */
export function blanks(text) {
  return [...text.matchAll(BLANK)].map((m) => {
    const lineStart = text.lastIndexOf('\n', m.index) + 1
    const before = text.slice(lineStart, m.index).replace(/^\s*(\d+\.\s*)?/, '').trim()
    const after = text.slice(m.index + m[0].length)
    const note = (/^[ \t]*\(([^)]*)\)/.exec(after) ?? (before ? null : /^\s*\n\s*\(([^)]*)\)/.exec(after)))?.[1]
    const said = note && note.replace(/\s+/g, ' ').replace(/^officer to /, '').trim()
    const label = /^([A-Za-z' ]{2,24}?)\s*:$/.exec(before)?.[1] ?? (/^To\s*:/.test(before) ? 'To' : null)
    if (/powers under$|^Under$/.test(before)) return said && said.split(' ').length > 2 ? cap(said) : 'The legal provision'
    if (label) return said && said.split(' ').length > 1 ? `${label}: ${said}` : label
    if (said && said.split(' ').length > 1) return cap(said)
    if (before.endsWith(':')) return before.slice(0, -1).replace(LONG, (a) => middle(a)).trim()
    return before ? `After "${before.split(/\s+/).slice(-3).join(' ')}"` : 'A blank'
  })
}

const six = (x) => x.toLocaleString('en-US', { minimumFractionDigits: 6, maximumFractionDigits: 6 })

/** The checks this letter passes: [{ title, detail }]. */
export function checks(text, result) {
  const out = []
  if (/\bnot\s+about\s+the\s+wallet\s+(\S+\s+)?itself\b/i.test(text)) {
    const label = plain(result.exchange_label) || 'This wallet'
    out.push({ title: "Asks about the deposits, not the wallet's owner", detail: `${label} is the exchange's own wallet; it belongs to no one customer` })
  }
  const least = result.estimates?.conservative
  if (typeof least === 'number' && text.includes(`about ${six(least)} `)) {
    out.push({ title: `States ${num(least)} ${plain(result.asset)}`, detail: 'the smallest estimate the trace has' })
  }
  const paid = result.intake?.mode === 'payment' ? (result.intake.payments ?? []) : []
  if (paid.length && paid.every((p) => p.tx_hash && text.includes(p.tx_hash.replace(/^0x/, '')))) {
    out.push({ title: "The complainant's payment is filled in", detail: 'from the hash given at intake' })
  }
  if (/^Date\s*:/m.test(text) && /\d IST\b/.test(text)) {
    out.push({ title: 'Dated in IST', detail: /\d UTC\b/.test(text) ? 'times shown in IST, with UTC beside them' : 'times shown in IST' })
  }
  return out
}

/** The exchange a case's letters go to, its address and the asset that
 * reached it: the trace's own, else the first follow-on's that reached one,
 * as the backend picks it (request_letters._attribution). */
export function exchangeOf(result) {
  if (result.exchange) return { name: result.exchange, address: result.exchange_address ?? '', asset: result.asset ?? '' }
  const follow = (result.follow_ons ?? []).find((f) => f.result?.exchange)
  if (!follow) return { name: null, address: '', asset: result.asset ?? '' }
  return { name: follow.result.exchange, address: follow.result.exchange_address ?? '', asset: follow.asset ?? follow.result.asset ?? result.asset ?? '' }
}

/** The asset a logged request is in: what reached the exchange, USDT for
 * Tether (its letters are about USDT alone), else the trace's own. */
export function assetOf(to, result) {
  if (to.startsWith('tether')) return 'USDT'
  if (to.startsWith('exchange')) return exchangeOf(result).asset
  return result.asset ?? ''
}

/** Who a letter listed by GET /trace/{id}/letters goes to, as the requests log names them. */
export function recipientOf(letter, result) {
  if (letter.to.startsWith('tether')) return 'Tether'
  if (letter.to.startsWith('exchange')) return plain(exchangeOf(result).name ?? 'the exchange')
  return plain(letter.title).replace(/^(urgent freeze )?request to /i, '')
}

/** The wallet a letter is about, for its row in the requests log: the one an
 * instant exchanger's letter names (it need not be the case's exchange), the
 * exchange's wallet for an exchange letter (exchangeOf: a follow-on's when the
 * trace itself reached none), else none. */
export function addressOf(letter, result) {
  if (letter.to.startsWith('instant')) return letter.address ?? ''
  return letter.to.startsWith('exchange') ? exchangeOf(result).address : ''
}

/** The instant exchanger the letters go to, as request_letters._instant picks
 * it: the case's own exchange when it is one, else the first a trace reached.
 * Null when the case's matches name none. */
export function instantService(result) {
  const traces = [result, ...(result.follow_ons ?? []).map((f) => f.result).filter(Boolean)]
  const found = traces.find((t) => t.exchange)
  const picks = traces.flatMap((t) => [...(t.matches ?? []), ...(t.inferred_deposits ?? [])]
    .filter((m) => m.category === 'instant_exchanger' && m.address).map((m) => ({ t, m })))
  const own = picks.find(({ t, m }) => t === found && m.address === t.exchange_address)
  if (!picks.length) return null
  return plain(own ? own.t.exchange : picks[0].m.exchange) || 'the swap service'
}

const KINDS = new Set(['exchange', 'tether', 'exchange-freeze', 'tether-freeze', 'instant', 'instant-freeze']) // backend freeze_requests.KINDS

/** The requests log's kind for a letter: its own when the log knows it, else "other". */
export const kindOf = (to) => (KINDS.has(to) ? to : 'other')
