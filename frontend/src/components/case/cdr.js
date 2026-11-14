import { readCells } from '../../csv'
import { guessColumns, parseDate } from './statement'

// Reading a call detail record (CDR) an Indian operator supplied, in the browser
// (suite feature 5; the server's side is backend/app/cdr_imports.py). Nothing here
// sends anything: the officer sees the analysis and saves only a summary they
// confirm -- numbers and counts, never the CDR's rows.
//
// A number is a lead, never a person: subscriber details come from the operator
// under a lawful request.

// Each field's header names, best first, compared as statement.js compares them
// (no case, spacing, punctuation, digits or bracketed unit): "B Party No." is "bpartyno".
export const CDR_HEADERS = {
  a: ['aparty', 'apartyno', 'apartynumber', 'targetno', 'targetnumber', 'callingnumber', 'callingno', 'callingparty',
    'callingpartynumber', 'msisdn', 'originatingnumber', 'caller'],
  b: ['bparty', 'bpartyno', 'bpartynumber', 'callednumber', 'calledno', 'calledparty', 'calledpartynumber', 'othernumber',
    'otherparty', 'terminatingnumber', 'dialednumber', 'dialledno', 'destination'],
  date: ['calldate', 'date', 'datetime', 'calldatetime', 'startdate', 'starttime', 'callstarttime'],
  time: ['calltime', 'time', 'starttime', 'callstarttime'],
  duration: ['duration', 'callduration', 'durationsec', 'durationinsec', 'durationseconds', 'dur', 'seconds'],
  type: ['calltype', 'type', 'callcategory', 'direction', 'servicetype', 'eventtype', 'usagetype', 'recordtype'],
  imei: ['imei', 'imeino', 'imeinumber', 'firstimei'],
  imsi: ['imsi', 'imsino', 'imsinumber'],
  firstCell: ['firstcellid', 'firstcgi', 'firstcellglobalid', 'startcellid', 'firstcell', 'firstbts', 'cellid', 'cgi'],
  lastCell: ['lastcellid', 'lastcgi', 'lastcellglobalid', 'endcellid', 'lastcell', 'lastbts'],
  location: ['firstcelllocation', 'firstcelladdress', 'firstcellidaddress', 'towerlocation', 'celladdress', 'siteaddress',
    'btslocation', 'location', 'address'],
}
export const CDR_FIELDS = Object.keys(CDR_HEADERS)

// Operators word their headers in many ways ("Target / A Party Number", "Call Start Date"). A field
// no header names exactly takes the first free column whose header contains one of these words,
// unless it also has a word that says it is something else: a circle or an operator is not a number,
// an address is not a cell ID.
const CDR_WORDS = {
  a: ['aparty', 'target', 'calling', 'msisdn', 'originating'],
  b: ['bparty', 'otherparty', 'called', 'dialled', 'dialed', 'terminating'],
  date: ['date'], time: ['time'], duration: ['duration'], type: ['calltype', 'typeofcall', 'type'],
  imei: ['imei'], imsi: ['imsi'],
  firstCell: ['firstcell', 'firstcgi', 'startcell', 'firstbts'], lastCell: ['lastcell', 'lastcgi', 'endcell', 'lastbts'],
  location: ['address', 'location'],
}
const NOT_A_NUMBER = /circle|operator|network|tsp|lrn|roam|imei|imsi|cell|cgi|name|address|location|type|date|time/
const NOT_A_CELL = /address|location|lat|long|name/
const NOT = { a: NOT_A_NUMBER, b: NOT_A_NUMBER, firstCell: NOT_A_CELL, lastCell: NOT_A_CELL }
const headerKey = (h) => String(h ?? '').toLowerCase().replace(/\([^)]*\)/g, '').replace(/[^a-z]/g, '') // as statement.js

function guess(headers) {
  const out = guessColumns(headers, CDR_HEADERS)
  const keys = headers.map(headerKey)
  const taken = new Set(Object.values(out).filter((i) => i >= 0))
  for (const field of CDR_FIELDS) {
    if (out[field] >= 0) continue
    const at = keys.findIndex((k, i) => !taken.has(i) && CDR_WORDS[field].some((w) => k.includes(w)) && !NOT[field]?.test(k))
    if (at >= 0) { out[field] = at; taken.add(at) }
  }
  return out
}
const usable = (map) => map.date >= 0 && (map.a >= 0 || map.b >= 0)

/** The CDR's header row and the records under it: an operator's export starts with lines about
 * the request; the header is the first of the first 30 records with a date and a number column,
 * named exactly, else named in words (a line about the request is less likely to pass the first). */
export function readCdr(text) {
  const { records } = readCells(text)
  const head = records.slice(0, 30)
  let at = head.findIndex((r) => usable(guessColumns(r.cells, CDR_HEADERS)))
  if (at < 0) at = head.findIndex((r) => usable(guess(r.cells)))
  if (at < 0) return { error: 'No header row with a date and an A or B party column was found in the first 30 lines.' }
  const headers = records[at].cells.map((c) => c.trim())
  return { headers, records: records.slice(at + 1), columns: guess(headers) }
}

const MOBILE = /^[6-9]\d{9}$/
// Country codes whose numbers are written with a trunk 0 after them (+44 (0)20 ...): the 0 is
// dropped, as identifiers.phone drops it (its _TRUNK_ZERO_CODES), so the two agree on every number.
const TRUNK_ZERO = new Set(['20', '27', '30', '31', '32', '33', '34', '36', '40', '41', '43', '44', '45', '46', '47', '48', '49',
  '51', '52', '53', '54', '55', '56', '57', '58', '60', '61', '62', '63', '64', '65', '66',
  '81', '82', '84', '86', '90', '92', '93', '94', '95', '98'])

/**
 * A number as the identifier register keeps it (identifiers.phone): {value, kind, checkable} or null.
 * An Indian mobile, however printed (+91, 0091, 91, 0 or nothing before its 10 digits), is +91 and its
 * 10 digits (kind mobile); a number with another country code is + and its digits (foreign). A short code
 * or a landline is kept as printed (other), an SMS sender as AX-ABCDEF (sender): neither can be checked
 * against the register, which holds phone numbers only.
 */
export function normaliseNumber(text) {
  const s = String(text ?? '').trim()
  if (/^[A-Za-z0-9]{2}-[A-Za-z0-9]{3,11}$/.test(s) && /[A-Za-z]/.test(s)) return { value: s.toUpperCase(), kind: 'sender', checkable: false }
  if (!s || /[^\d\s()+.-]/.test(s)) return null
  const plus = /^\(?\+/.test(s) || s.startsWith('00') // "(+44) 7700 ..." too
  let d = s.replace(/\D/g, '')
  if (s.startsWith('00')) d = d.slice(2)
  if (plus && TRUNK_ZERO.has(d.slice(0, 2)) && d[2] === '0') d = d.slice(0, 2) + d.slice(3)
  const mobile = (ten) => ({ value: `+91${ten}`, kind: 'mobile', checkable: true })
  if (plus) {
    if (d.startsWith('91')) return MOBILE.test(d.slice(2)) ? mobile(d.slice(2)) : { value: d, kind: 'other', checkable: false }
    return d.length >= 8 && d.length <= 15 && d[0] !== '0' ? { value: `+${d}`, kind: 'foreign', checkable: true } : null
  }
  if (MOBILE.test(d)) return mobile(d)
  if (d.length === 11 && d[0] === '0' && MOBILE.test(d.slice(1))) return mobile(d.slice(1))
  if (d.length === 12 && d.startsWith('91') && MOBILE.test(d.slice(2))) return mobile(d.slice(2))
  return /^\d{3,15}$/.test(d) ? { value: d, kind: 'other', checkable: false } : null
}

/** A call type: {sms, direction: 'out' | 'in' | ''}. MO/MT, SMS-MO/SMS-MT, MOC/MTC, incoming/outgoing. */
export function eventType(text) {
  const t = String(text ?? '').toUpperCase().replace(/[^A-Z]/g, '')
  const sms = t.includes('SMS') || t === 'SMO' || t === 'SMT'
  const direction = /(MO|MOC|OUT|OUTGOING|ORIGINATED|ORIGINATING)$/.test(t) ? 'out'
    : /(MT|MTC|IN|INCOMING|TERMINATED|TERMINATING)$/.test(t) ? 'in' : ''
  return { sms, direction }
}

/** A duration in seconds: plain seconds (125), h:mm:ss or m:ss; 0 when blank or unreadable. */
export function parseDuration(text) {
  const s = String(text ?? '').trim()
  if (/^\d+(\.\d+)?$/.test(s)) return Math.round(Number(s))
  const m = /^(?:(\d+):)?(\d{1,2}):(\d{2})$/.exec(s)
  return m ? (+(m[1] ?? 0)) * 3600 + +m[2] * 60 + +m[3] : 0
}

function parseTime(text) {
  const m = /^(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?$/.exec(String(text ?? '').trim())
  if (!m) return ''
  const h = m[3] ? (+m[1] % 12) + (/p/i.test(m[3]) ? 12 : 0) : +m[1]
  return h <= 23 && +m[2] <= 59 ? `${String(h).padStart(2, '0')}:${m[2]}` : ''
}

const cell = (r, i) => (i >= 0 ? String(r.cells[i] ?? '').trim() : '')

/** The CDR's events: {events: [{line, date, time, at, a, b, sms, direction, seconds, imei, imsi, cell, location}],
 * skipped: [{line, why}]}. `at` is "YYYY-MM-DD HH:MM", for ordering. */
export function cdrEvents(records, columns) {
  const events = []
  const skipped = []
  for (const r of records) {
    const when = parseDate(cell(r, columns.date))
    if (!when) { skipped.push({ line: r.line, why: 'no date it can read' }); continue }
    const time = when.time || parseTime(cell(r, columns.time))
    const a = normaliseNumber(cell(r, columns.a))
    const b = normaliseNumber(cell(r, columns.b))
    if (!a && !b) { skipped.push({ line: r.line, why: 'no number it can read' }); continue }
    const imei = cell(r, columns.imei).replace(/\D/g, '')
    events.push({
      line: r.line, date: when.date, time, at: `${when.date} ${time || '00:00'}`, a, b, ...eventType(cell(r, columns.type)),
      seconds: parseDuration(cell(r, columns.duration)), imei: /^\d{14,16}$/.test(imei) ? imei : '',
      imsi: cell(r, columns.imsi).replace(/\D/g, ''), cell: cell(r, columns.firstCell), location: cell(r, columns.location),
    })
  }
  return { events, skipped }
}

/** The CDR's own number: the one on the most events, as A or B party. */
export function subjectOf(events) {
  const seen = new Map()
  for (const e of events) {
    for (const v of new Set([e.a?.value, e.b?.value].filter(Boolean))) seen.set(v, (seen.get(v) ?? 0) + 1)
  }
  return [...seen.entries()].sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]))[0]?.[0] ?? ''
}

/** Each distinct value of `key` (an IMEI, an IMSI) with its events, first and last use, oldest first,
 * and how many times the value changed from one event to the next. Two values are one when `same`
 * makes them equal; the first printed is shown. */
function uses(sorted, key, same = (v) => v) {
  const by = new Map()
  let changes = 0
  let before = ''
  for (const e of sorted) {
    const v = e[key]
    if (!v) continue
    const id = same(v)
    if (before && id !== before) changes += 1
    before = id
    const had = by.get(id)
    if (had) { had.events += 1; had.last = e.at } else by.set(id, { value: v, events: 1, first: e.at, last: e.at })
  }
  return { list: [...by.values()].sort((x, y) => x.first.localeCompare(y.first)), changes }
}

/**
 * The analysis: {subject, totals, contacts, imeis, handsetChanges, imsis, simChanges, cells}. Each contact is
 * {number, kind, checkable, calls, sms, out, in, seconds, first, last}, most events first. An event's other party
 * is whichever of A and B is not the subject; its direction is the call type's, else outgoing when the subject is A.
 */
export function analyse(events, subject = subjectOf(events)) {
  const sorted = [...events].sort((x, y) => x.at.localeCompare(y.at))
  const contacts = new Map()
  const cells = new Map()
  const totals = { events: sorted.length, calls: 0, sms: 0, seconds: 0, first: sorted[0]?.at ?? '', last: sorted.at(-1)?.at ?? '' }
  for (const e of sorted) {
    totals[e.sms ? 'sms' : 'calls'] += 1
    totals.seconds += e.sms ? 0 : e.seconds
    if (e.cell) {
      const c = cells.get(e.cell) ?? { cell: e.cell, location: e.location, events: 0 }
      c.events += 1
      cells.set(e.cell, c)
    }
    const other = e.a?.value === subject ? e.b : e.b?.value === subject ? e.a : e.b ?? e.a
    if (!other || other.value === subject) continue
    const c = contacts.get(other.value) ?? { number: other.value, kind: other.kind, checkable: other.checkable,
      calls: 0, sms: 0, out: 0, in: 0, seconds: 0, first: e.at, last: e.at }
    c[e.sms ? 'sms' : 'calls'] += 1
    c[(e.direction || (e.a?.value === subject ? 'out' : 'in'))] += 1
    c.seconds += e.sms ? 0 : e.seconds
    c.last = e.at
    contacts.set(other.value, c)
  }
  // A handset is its IMEI's first 14 digits: the 15th is a check digit a CDR may leave off or print
  // otherwise, and a 16-digit IMEISV ends in a software version, which changes with an update.
  const handsets = uses(sorted, 'imei', (v) => v.slice(0, 14))
  const sims = uses(sorted, 'imsi')
  return {
    subject, totals,
    contacts: [...contacts.values()].sort((x, y) => (y.calls + y.sms) - (x.calls + x.sms) || y.seconds - x.seconds || x.number.localeCompare(y.number)),
    imeis: handsets.list, handsetChanges: handsets.changes, imsis: sims.list, simChanges: sims.changes,
    cells: [...cells.values()].sort((x, y) => y.events - x.events || x.cell.localeCompare(y.cell)),
  }
}

/** The top `n` contacts by events ('count') or by total call time ('seconds'). */
export function topContacts(contacts, by = 'count', n = 20) {
  const score = (c) => (by === 'seconds' ? c.seconds : c.calls + c.sms)
  return [...contacts].sort((x, y) => score(y) - score(x) || x.number.localeCompare(y.number)).slice(0, n)
}

/** The case's own active phone identifiers (from GET /trace/{case}/identifiers), as a set of values. */
export function casePhones(identifiers) {
  return new Set((identifiers ?? []).filter((i) => i.kind === 'phone' && i.status === 'active').map((i) => i.value))
}

const day = (at) => String(at).slice(0, 10)

/** A contact, the subject or a handset as the server keeps it (cdr_imports.clean_row). */
export function contactRow(c, reasons) {
  return { kind: 'number', value: c.number, calls: c.calls, sms: c.sms, seconds: c.seconds, first: day(c.first), last: day(c.last), reasons }
}
export function subjectRow(analysis, reasons) {
  const t = analysis.totals
  return { kind: 'subject', value: analysis.subject, calls: t.calls, sms: t.sms, seconds: t.seconds, first: day(t.first), last: day(t.last), reasons }
}
export function imeiRow(u) {
  return { kind: 'imei', value: u.value, events: u.events, first: day(u.first), last: day(u.last) }
}
