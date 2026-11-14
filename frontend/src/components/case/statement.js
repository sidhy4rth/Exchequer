import { readCells } from '../../csv'

// Reading a bank statement, or a transaction statement an exchange sent, in the
// browser and lining it up with the case (suite feature 5; the server's side is
// backend/app/statement_imports.py). Nothing here sends anything: the officer
// sees what was found and saves only the rows they confirm.
//
// Indian statements: dates are day first (12/03/2026, 12-Mar-2026, never month
// first), amounts may use lakh grouping (2,50,000.00), and money out and in come
// either as two columns (Withdrawal, Deposit), as one amount with a Dr/Cr column,
// or as one signed amount (-2,50,000.00, or 2,50,000.00 Dr).

// Each field's header names, best first, compared without case, spacing,
// punctuation or a bracketed currency: "Withdrawal Amt.(INR)" is "withdrawalamt".
export const HEADERS = {
  date: ['txndate', 'transactiondate', 'trandate', 'date', 'postingdate', 'datetime', 'time', 'createdat', 'valuedate'],
  narration: ['narration', 'description', 'particulars', 'transactionremarks', 'remarks', 'transactiondetails', 'details'],
  reference: ['utr', 'utrno', 'utrnumber', 'chqrefno', 'refno', 'referenceno', 'reference', 'refchqno', 'chqno', 'chequeno',
    'transactionid', 'txnid', 'txid', 'txhash', 'transactionhash'],
  debit: ['withdrawalamt', 'withdrawal', 'withdrawals', 'withdrawalamount', 'debit', 'debitamount', 'dr', 'debits'],
  credit: ['depositamt', 'deposit', 'deposits', 'depositamount', 'credit', 'creditamount', 'cr', 'credits'],
  amount: ['amount', 'transactionamount', 'amt', 'quantity', 'value'],
  drcr: ['drcr', 'crdr', 'debitcredit', 'type', 'transactiontype', 'side'],
  balance: ['balance', 'closingbalance', 'availablebalance', 'runningbalance', 'balanceamount'],
  counterparty: ['counterparty', 'beneficiary', 'beneficiaryname', 'payee', 'payeename', 'remitter', 'remittername', 'tofrom'],
}
export const FIELDS = Object.keys(HEADERS)
const key = (h) => String(h ?? '').toLowerCase().replace(/\([^)]*\)/g, '').replace(/[^a-z]/g, '')

/** Each field's column index, or -1: every column becomes one field at most. */
export function guessColumns(headers) {
  const keys = headers.map(key)
  const taken = new Set()
  const out = {}
  for (const field of FIELDS) {
    out[field] = -1
    for (const name of HEADERS[field]) {
      const at = keys.findIndex((k, i) => k === name && !taken.has(i))
      if (at >= 0) { out[field] = at; taken.add(at); break }
    }
  }
  return out
}

const usable = (map) => map.date >= 0 && (map.debit >= 0 || map.credit >= 0 || map.amount >= 0)

/** The statement's header row and the records under it. A bank's export starts
 * with lines about the account; the header is the first of the first 30 records
 * that has a date column and an amount column. */
export function readStatement(text) {
  const { records } = readCells(text)
  const at = records.slice(0, 30).findIndex((r) => usable(guessColumns(r.cells)))
  if (at < 0) return { error: 'No header row with a date and an amount column was found in the first 30 lines.' }
  const headers = records[at].cells.map((c) => c.trim())
  return { headers, records: records.slice(at + 1), columns: guessColumns(headers) }
}

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
const pad = (n) => String(n).padStart(2, '0')

/** A day-first or ISO date, with any time after it: {date: 'YYYY-MM-DD', time: 'HH:MM' or ''}, or null. */
export function parseDate(text) {
  const s = String(text ?? '').trim()
  let m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?)?\s*(Z|UTC|[+-]\d{2}:?\d{2})?$/i.exec(s)
  let y, mo, d, hh = null, mm = null
  if (m) [y, mo, d, hh, mm] = [+m[1], +m[2], +m[3], m[4], m[5]]
  else {
    m = /^(\d{1,2})[/.\- ]([A-Za-z]{3,9}|\d{1,2})[/.\- ](\d{4}|\d{2})(?:[ ,T]+(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?)?$/.exec(s)
    if (!m) return null
    d = +m[1]
    mo = /^\d+$/.test(m[2]) ? +m[2] : MONTHS.indexOf(m[2].slice(0, 3).toLowerCase()) + 1
    y = m[3].length === 2 ? 2000 + +m[3] : +m[3]
    hh = m[4]; mm = m[5]
    if (hh != null && m[6]) hh = String((+hh % 12) + (/p/i.test(m[6]) ? 12 : 0))
  }
  const day = new Date(Date.UTC(y, mo - 1, d))
  if (!mo || day.getUTCFullYear() !== y || day.getUTCMonth() !== mo - 1 || day.getUTCDate() !== d) return null
  if (hh != null && (+hh > 23 || +mm > 59)) return null
  return { date: `${y}-${pad(mo)}-${pad(d)}`, time: hh != null ? `${pad(+hh)}:${mm}` : '' }
}

/** An amount as printed: {value (signed, Dr negative), places, text (unsigned)} or null for a blank or bad cell. */
export function parseAmount(text) {
  let s = String(text ?? '').trim().replace(/^(₹|rs\.?|inr)\s*/i, '').replace(/\s*(inr)$/i, '')
  let sign = 1
  const side = /\s*\b(dr|cr)\.?$/i.exec(s)
  if (side) { sign = side[1].toLowerCase() === 'dr' ? -1 : 1; s = s.slice(0, side.index).trim() }
  if (/^\(.*\)$/.test(s)) { sign = -sign; s = s.slice(1, -1).trim() }
  if (/^[-+]/.test(s)) { if (s[0] === '-') sign = -sign; s = s.slice(1).trim() }
  // Plain digits, Indian grouping (2,50,000) or Western grouping (250,000).
  if (!/^(\d+|\d{1,2}(,\d{2})*,\d{3}|\d{1,3}(,\d{3})+)(\.\d+)?$/.test(s)) return null
  const plain = s.replace(/,/g, '')
  const value = Number(plain)
  return Number.isFinite(value) ? { value: sign * value, places: (plain.split('.')[1] ?? '').length, text: plain } : null
}

// Bank references, as Indian banks print them: an NEFT UTR is 16 characters (the
// bank's 4-letter IFSC code, N, then 11 digits), an RTGS UTR 22 (the code, R, a
// channel character, then 16 digits), and an IMPS or UPI reference (RRN) 12 digits
// whose 2nd to 4th digits are the day of the year. A 12-digit number is read only in
// a UPI or IMPS narration, since account numbers are digits too.
const NEFT = /(?<![A-Z0-9])[A-Z]{4}N\d{11}(?![A-Z0-9])/g
const RTGS = /(?<![A-Z0-9])[A-Z]{4}R[A-Z0-9]\d{16}(?![A-Z0-9])/g
const RRN = /(?<![A-Z0-9])\d{12}(?![A-Z0-9])/g
const dayOfYear = (rrn) => +rrn.slice(1, 4) >= 1 && +rrn.slice(1, 4) <= 366

/** The UTRs and RRNs a narration or reference names: [{kind, value}]. */
export function findUtrs(text) {
  const s = String(text ?? '').toUpperCase()
  const out = [...s.matchAll(NEFT)].map((m) => ({ kind: 'NEFT', value: m[0] }))
    .concat([...s.matchAll(RTGS)].map((m) => ({ kind: 'RTGS', value: m[0] })))
  const channel = /(?<![A-Z])(UPI|IMPS)(?![A-Z])/.exec(s)
  if (channel) {
    out.push(...[...s.matchAll(RRN)].filter((m) => dayOfYear(m[0])).map((m) => ({ kind: channel[1], value: m[0] })))
  }
  return out.filter((u, i) => out.findIndex((o) => o.value === u.value) === i)
}

const HASH = /(?<![0-9a-fA-Fx])(0x)?[0-9a-fA-F]{64}(?![0-9a-fA-F])/g
const bareHash = (h) => String(h ?? '').toLowerCase().replace(/^0x/, '')

/** The canonical exchange names (from the server) that `text` contains as whole words, ignoring case. */
export function namesIn(text, names) {
  const s = String(text ?? '')
  return (names ?? []).filter((n) => new RegExp(`(?<![A-Za-z0-9])${n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![A-Za-z0-9])`, 'i').test(s))
}

const cell = (r, i) => (i >= 0 ? String(r.cells[i] ?? '').trim() : '')

/** Statement rows from its records and columns: {rows: [{line, date, time, direction, amount, places, text,
 * narration, reference, counterparty, balance}], skipped: [{line, why}]}. */
export function statementRows(records, columns) {
  const rows = []
  const skipped = []
  for (const r of records) {
    const when = parseDate(cell(r, columns.date))
    if (!when) { skipped.push({ line: r.line, why: 'no date it can read' }); continue }
    const debit = parseAmount(cell(r, columns.debit))
    const credit = parseAmount(cell(r, columns.credit))
    let money = null
    if (debit && debit.value !== 0) money = { ...debit, direction: 'debit' }
    else if (credit && credit.value !== 0) money = { ...credit, direction: 'credit' }
    else {
      const amount = parseAmount(cell(r, columns.amount))
      if (amount && amount.value !== 0) {
        const side = cell(r, columns.drcr).toLowerCase()
        const out = /^(d|dr|debit|withdrawal|sell|send|out)/.test(side) || (!side && amount.value < 0)
        money = { ...amount, direction: out ? 'debit' : 'credit' }
      }
    }
    if (!money) { skipped.push({ line: r.line, why: 'no amount it can read' }); continue }
    rows.push({
      line: r.line, ...when, direction: money.direction, amount: Math.abs(money.value), places: money.places, text: money.text,
      narration: cell(r, columns.narration), reference: cell(r, columns.reference),
      counterparty: cell(r, columns.counterparty), balance: parseAmount(cell(r, columns.balance))?.value ?? null,
    })
  }
  return { rows, skipped }
}

const istDay = (seconds) => new Date((seconds + 19800) * 1000).toISOString().slice(0, 10)
const days = (a, b) => Math.round((Date.parse(a) - Date.parse(b)) / 86_400_000)

/** The case's own payments (intake.payments), one per hash with its legs added:
 * [{amount, currency, date, timestamp}]. A payment whose time is withheld from this reader has date null. */
export function casePayments(result) {
  const paid = result?.intake?.mode === 'payment' ? result.intake.payments ?? [] : []
  const byHash = new Map()
  paid.forEach((p, i) => {
    const k = p.tx_hash ?? `#${i}`
    const had = byHash.get(k)
    if (had) had.amount += p.amount
    else byHash.set(k, { amount: p.amount, currency: String(p.asset ?? '').toUpperCase(), timestamp: p.timestamp ?? null,
      date: p.timestamp ? istDay(p.timestamp) : null, tx_hash: p.tx_hash ?? null })
  })
  return [...byHash.values()]
}

/** Agree to the places the statement prints, and to at least two. */
export function sameAmount(row, amount) {
  const places = Math.min(Math.max(row.places ?? 2, 2), 8)
  return Math.round(row.amount * 10 ** places) === Math.round(amount * 10 ** places)
}

export const WINDOW_DAYS = 2

/**
 * Why each row is worth a look: [{row, reasons, payment, exchange, utrs, hash}] for the rows with any.
 * amount_date: the same currency, the same amount, and a date within WINDOW_DAYS of a payment's (in India);
 * utr: it carries a UTR or RRN; exchange: it names a canonical exchange; tx_hash: it names a hash of the trace.
 */
export function matchRows(rows, { payments = [], currency = 'INR', names = [], hashes = [] } = {}) {
  const known = new Set(hashes.filter(Boolean).map(bareHash))
  const cur = String(currency).toUpperCase()
  const out = []
  for (const row of rows) {
    const reasons = []
    const payment = payments.findIndex((p) => p.date && p.currency === cur && sameAmount(row, p.amount)
      && Math.abs(days(row.date, p.date)) <= WINDOW_DAYS)
    if (payment >= 0) reasons.push('amount_date')
    const utrs = findUtrs(`${row.reference} ${row.narration}`)
    if (utrs.length) reasons.push('utr')
    const exchange = namesIn(`${row.narration} ${row.counterparty}`, names)[0] ?? ''
    if (exchange) reasons.push('exchange')
    const hash = [...`${row.reference} ${row.narration}`.matchAll(HASH)].map((m) => m[0]).find((h) => known.has(bareHash(h)))
    if (hash) reasons.push('tx_hash')
    if (reasons.length) out.push({ row, reasons, payment: payment >= 0 ? payment : null, exchange, utrs, hash: hash ?? '' })
  }
  return out
}

const REFERENCE = /^[A-Za-z0-9][A-Za-z0-9/._-]{0,39}$/

/** A match as the server keeps it. A transaction hash goes in the reference, never in the narration,
 * where the server would take 64 hex characters for a private key. */
export function toSaved(m) {
  const { row } = m
  const shaped = REFERENCE.test(row.reference) ? row.reference : ''
  const reference = m.hash || (m.reasons.includes('utr') ? (findUtrs(shaped).length ? shaped : m.utrs[0].value) : shaped)
  return {
    date: row.date, time: row.time, direction: row.direction, amount: row.places > 8 ? row.amount.toFixed(8) : row.text,
    reference, narration: row.narration.replace(HASH, '[hash]').slice(0, 300),
    counterparty: row.counterparty.replace(HASH, '[hash]').slice(0, 120), reasons: m.reasons, exchange: m.exchange,
  }
}

const istTime = (seconds) => new Date((seconds + 19800) * 1000).toISOString().slice(11, 16)

/** The statement's matched rows beside the trace's own on-chain times, oldest first:
 * [{date, time, side: 'statement' | 'chain', text}]. Chain times are in India's time. */
export function timeline(matches, result) {
  const events = matches.map((m) => ({
    date: m.row.date, time: m.row.time, side: 'statement',
    text: `${m.row.direction === 'debit' ? 'Debit' : 'Credit'} ${m.row.text}${m.exchange ? ` · names ${m.exchange}` : ''}`,
  }))
  for (const p of casePayments(result)) {
    if (p.timestamp) events.push({ date: istDay(p.timestamp), time: istTime(p.timestamp), side: 'chain', text: `Payment of ${p.amount} ${p.currency} reached the reported wallet` })
  }
  const exchange = result?.attribution?.address?.toLowerCase()
  for (const t of result?.transfers ?? []) {
    if (exchange && t.timestamp && String(t.to ?? '').toLowerCase() === exchange) {
      events.push({ date: istDay(t.timestamp), time: istTime(t.timestamp), side: 'chain',
        text: `${t.value_native}${result.asset ? ` ${result.asset}` : ''} reached ${result.attribution.exchange ?? 'the exchange'}` })
    }
  }
  return events.sort((a, b) => `${a.date} ${a.time || '00:00'}`.localeCompare(`${b.date} ${b.time || '00:00'}`))
}
