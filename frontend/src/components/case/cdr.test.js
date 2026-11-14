import { describe, expect, it } from 'vitest'
import {
  analyse, casePhones, cdrEvents, contactRow, eventType, imeiRow, normaliseNumber, parseDuration, readCdr, subjectOf,
  subjectRow, topContacts,
} from './cdr'

// Every number here is synthetic, and none can be a real Indian mobile. India's mobile
// numbers start with 6, 7, 8 or 9 and India sets aside no range for fiction, so a 10-digit
// number here starts with 5 (50000 0000x): no mobile series. normaliseNumber, like the
// identifier register, takes a 10-digit number as an Indian mobile only when it starts 6 to 9,
// on purpose, so a number that must be read as a phone is in Ofcom's range for drama
// (+44 7700 900000 to 900999), set aside so that no subscriber holds it. IMEIs are made up and
// start with a run of zeros; IMSIs use the test network's code (MCC 001, MNC 01). Cell IDs
// and places are invented.
const IMEI1 = '000000000000011'
const IMEI2 = '000000000000029'
const CSV = [
  'CDR of target +44 7700 900001 from 01/03/2026 to 31/03/2026',
  '',
  'Target No,B Party No.,Call Date,Call Time,Duration (Sec),Call Type,IMEI,IMSI,First Cell ID,First Cell Location',
  `+447700900001,0044 7700 900002,01/03/2026,10:15:00,120,MO,${IMEI1},001010000000001,TEST-CELL-1,Test Nagar`,
  `+447700900001,+44 7700 900002,02/03/2026,11:00:00,00:01:30,MT,${IMEI1},001010000000001,TEST-CELL-1,Test Nagar`,
  `+447700900001,+44-7700-900002,05/03/2026,09:00:00,0,SMS-MO,${IMEI1},001010000000001,TEST-CELL-2,Test Pur`,
  `+447700900001,+447700900003,10/03/2026,20:30:00,600,MT,${IMEI2},001010000000001,TEST-CELL-2,Test Pur`,
  `+447700900001,AX-TESTCO,11/03/2026,08:00:00,0,SMS-MT,${IMEI2},001010000000001,TEST-CELL-2,Test Pur`,
  `+447700900001,121,12/03/2026,08:05:00,30,MO,${IMEI1},001010000000001,TEST-CELL-1,Test Nagar`,
  'not a date,+447700900002,,,,,,,,',
].join('\n')

describe('reading a CDR', () => {
  it("finds the header under the operator's lines and maps its columns", () => {
    const read = readCdr(CSV)
    expect(read.error).toBeUndefined()
    expect(read.columns).toMatchObject({ a: 0, b: 1, date: 2, time: 3, duration: 4, type: 5, imei: 6, imsi: 7, firstCell: 8, location: 9, lastCell: -1 })
  })

  it('knows the common header names', () => {
    const cols = readCdr('Calling Number,Called Number,Start Time,Call Duration,Service Type,IMEI No,Last Cell ID\n').columns
    expect(cols).toMatchObject({ a: 0, b: 1, date: 2, time: -1, duration: 3, type: 4, imei: 5, lastCell: 6 })
    expect(readCdr('A Party,B Party,Date,Time,Duration\n').columns).toMatchObject({ a: 0, b: 1, date: 2, time: 3, duration: 4 })
    expect(readCdr('Name,Amount\nx,1\n').error).toMatch(/No header row/)
  })
})

describe('numbers', () => {
  it('makes every form of one number the same number', () => {
    for (const printed of ['+447700900002', '+44 7700 900002', '0044 7700 900002', '+44-7700-900002', '00 44 7700 900002']) {
      expect(normaliseNumber(printed)).toEqual({ value: '+447700900002', kind: 'foreign', checkable: true })
    }
  })

  it('never makes a number outside the mobile series (6 to 9) an Indian mobile, however printed', () => {
    for (const [printed, value] of [['5000000002', '5000000002'], ['05000000002', '05000000002'], ['915000000002', '915000000002'],
      ['+91 50000 00002', '915000000002'], ['0091 5000000002', '915000000002']]) {
      expect(normaliseNumber(printed)).toEqual({ value, kind: 'other', checkable: false })
    }
  })

  it('keeps other numbers apart, and refuses what is not one', () => {
    expect(normaliseNumber('+44 7700 900123')).toEqual({ value: '+447700900123', kind: 'foreign', checkable: true })
    expect(normaliseNumber('121')).toEqual({ value: '121', kind: 'other', checkable: false })
    expect(normaliseNumber('01100000000')).toEqual({ value: '01100000000', kind: 'other', checkable: false }) // a landline
    expect(normaliseNumber('5000000001')).toEqual({ value: '5000000001', kind: 'other', checkable: false }) // not a mobile series
    expect(normaliseNumber('ax-testco')).toEqual({ value: 'AX-TESTCO', kind: 'sender', checkable: false })
    expect(normaliseNumber('')).toBeNull()
    expect(normaliseNumber('internet')).toBeNull()
    expect(normaliseNumber('+0123456789')).toBeNull()
  })

  it('reads call types and durations', () => {
    expect(eventType('MO')).toEqual({ sms: false, direction: 'out' })
    expect(eventType('mt')).toEqual({ sms: false, direction: 'in' })
    expect(eventType('SMS-MO')).toEqual({ sms: true, direction: 'out' })
    expect(eventType('SMS_MT')).toEqual({ sms: true, direction: 'in' })
    expect(eventType('Incoming')).toEqual({ sms: false, direction: 'in' })
    expect(eventType('')).toEqual({ sms: false, direction: '' })
    expect([parseDuration('125'), parseDuration('00:02:05'), parseDuration('2:05'), parseDuration(''), parseDuration('n/a')]).toEqual([125, 125, 125, 0, 0])
  })
})

const read = () => { const r = readCdr(CSV); return cdrEvents(r.records, r.columns) }

describe('the analysis', () => {
  it('skips rows without a date, and takes the number on every row as the subject', () => {
    const { events, skipped } = read()
    expect(events).toHaveLength(6)
    expect(skipped).toEqual([{ line: 10, why: 'no date it can read' }])
    expect(subjectOf(events)).toBe('+447700900001')
  })

  it('counts each contact by calls, messages and time, with its first and last contact', () => {
    const a = analyse(read().events)
    expect(a.contacts.map((c) => [c.number, c.calls, c.sms, c.out, c.in, c.seconds, c.first, c.last])).toEqual([
      ['+447700900002', 2, 1, 2, 1, 210, '2026-03-01 10:15', '2026-03-05 09:00'],
      ['+447700900003', 1, 0, 0, 1, 600, '2026-03-10 20:30', '2026-03-10 20:30'],
      ['121', 1, 0, 1, 0, 30, '2026-03-12 08:05', '2026-03-12 08:05'],
      ['AX-TESTCO', 0, 1, 0, 1, 0, '2026-03-11 08:00', '2026-03-11 08:00'],
    ])
    expect(a.totals).toEqual({ events: 6, calls: 4, sms: 2, seconds: 840, first: '2026-03-01 10:15', last: '2026-03-12 08:05' })
    expect(topContacts(a.contacts, 'seconds', 2).map((c) => c.number)).toEqual(['+447700900003', '+447700900002'])
    expect(topContacts(a.contacts, 'count', 1).map((c) => c.number)).toEqual(['+447700900002'])
  })

  it('lists the handsets in the order first used, and counts each change of handset', () => {
    const a = analyse(read().events)
    expect(a.imeis.map((u) => [u.value, u.events, u.first, u.last])).toEqual([
      [IMEI1, 4, '2026-03-01 10:15', '2026-03-12 08:05'], [IMEI2, 2, '2026-03-10 20:30', '2026-03-11 08:00']])
    expect(a.handsetChanges).toBe(2) // IMEI1, then IMEI2, then IMEI1 again
    expect([a.imsis.length, a.simChanges]).toEqual([1, 0]) // one SIM throughout: silent
    expect(a.cells[0]).toEqual({ cell: 'TEST-CELL-1', location: 'Test Nagar', events: 3 })
  })

  it("names the case's own phone identifiers, and stays silent on other numbers", () => {
    const phones = casePhones([
      { kind: 'phone', value: '+447700900003', status: 'active' }, { kind: 'phone', value: '+447700900002', status: 'withdrawn' },
      { kind: 'telegram', value: '7700900002', status: 'active' }])
    const a = analyse(read().events)
    expect(a.contacts.filter((c) => phones.has(c.number)).map((c) => c.number)).toEqual(['+447700900003'])
    expect(phones.has(a.subject)).toBe(false)
    expect(casePhones([])).toEqual(new Set())
  })

  it('makes the rows the server keeps: numbers and counts, dates only', () => {
    const a = analyse(read().events)
    expect(contactRow(a.contacts[0], ['top_contact'])).toEqual({ kind: 'number', value: '+447700900002', calls: 2, sms: 1, seconds: 210,
      first: '2026-03-01', last: '2026-03-05', reasons: ['top_contact'] })
    expect(subjectRow(a, [])).toEqual({ kind: 'subject', value: '+447700900001', calls: 4, sms: 2, seconds: 840,
      first: '2026-03-01', last: '2026-03-12', reasons: [] })
    expect(imeiRow(a.imeis[1])).toEqual({ kind: 'imei', value: IMEI2, events: 2, first: '2026-03-10', last: '2026-03-11' })
  })
})
