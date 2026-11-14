import { describe, expect, it } from 'vitest'
import fixture from '../../../../backend/tests/fixtures/contract/exchange_wallet.json'
import {
  casePayments, findUtrs, guessColumns, matchRows, namesIn, parseAmount, parseDate, readStatement, sameAmount,
  statementRows, timeline, toSaved,
} from './statement'

// Every statement row here is synthetic: made-up narrations and payees, a test
// account number (9999000011112222) no bank issues, references shaped like a
// bank's but invented. On-chain values (hashes, times, amounts, the exchange
// address) come from the contract fixture backend/tests/fixtures/contract/exchange_wallet.json.

const NAMES = ['Binance', 'CoinDCX', 'Crypto.com', 'OKX']
const [T0] = fixture.transfers
// The fixture as a payment-mode case whose one payment is its first transfer.
const PAID = {
  ...fixture,
  intake: { mode: 'payment', payments: [{ tx_hash: T0.hash, asset: 'USDT', amount: T0.value_native, timestamp: T0.timestamp }] },
}

describe('reading the header', () => {
  it('finds common Indian bank header names', () => {
    const cols = guessColumns(['Txn Date', 'Value Date', 'Description', 'Ref No./Cheque No.', 'Withdrawal Amt.(INR)', 'Deposit Amt.(INR)', 'Closing Balance'])
    expect(cols).toMatchObject({ date: 0, narration: 2, debit: 4, credit: 5, balance: 6, amount: -1 })
    expect(guessColumns(['Date', 'Narration', 'Chq./Ref.No.', 'Amount', 'Dr/Cr', 'Balance'])).toMatchObject({ date: 0, narration: 1, reference: 2, amount: 3, drcr: 4, balance: 5 })
    expect(guessColumns(['Tran Date', 'PARTICULARS', 'UTR No', 'DR', 'CR', 'BAL'])).toMatchObject({ date: 0, narration: 1, reference: 2, debit: 3, credit: 4 })
  })

  it('prefers the transaction date to the value date, and gives no column twice', () => {
    const cols = guessColumns(['Value Date', 'Transaction Date', 'Remarks', 'Amount'])
    expect(cols.date).toBe(1)
    expect(new Set(Object.values(cols).filter((i) => i >= 0)).size).toBe(3)
  })

  it('skips the account lines a bank puts above the header', () => {
    const text = 'Account Name,TEST HOLDER\nAccount Number,9999000011112222\n\nDate,Narration,Debit,Credit\n12/03/2026,TEST,100.00,\n'
    const read = readStatement(text)
    expect(read.headers).toEqual(['Date', 'Narration', 'Debit', 'Credit'])
    expect(read.records.map((r) => r.line)).toEqual([5])
  })

  it('says so when no header has a date and an amount', () => {
    expect(readStatement('Name,Phone\nTEST,000\n').error).toMatch(/No header row/)
  })
})

describe('Indian dates and amounts', () => {
  it.each([
    ['12/03/2026', '2026-03-12', ''], ['12-03-2026', '2026-03-12', ''], ['12.03.26', '2026-03-12', ''],
    ['12-Mar-2026', '2026-03-12', ''], ['12 MAR 2026', '2026-03-12', ''], ['05-Sept-2026', '2026-09-05', ''],
    ['2026-03-12 14:05:09', '2026-03-12', '14:05'], ['12/03/2026 02:05 PM', '2026-03-12', '14:05'], ['2026-03-12T09:01:00Z', '2026-03-12', '09:01'],
  ])('reads %s day first', (text, date, time) => {
    expect(parseDate(text)).toEqual({ date, time })
  })

  it.each(['03/31/2026', '31/02/2026', '2026/03/12', 'yesterday', '', '12/03/2026 25:00'])('refuses %s', (text) => {
    expect(parseDate(text)).toBeNull()
  })

  it.each([
    ['2,50,000.00', 250000, 2], ['25,00,000', 2500000, 0], ['250,000.50', 250000.5, 2], ['₹ 1,000', 1000, 0],
    ['Rs. 99.5', 99.5, 1], ['-2,50,000.00', -250000, 2], ['(1,500.00)', -1500, 2], ['2,50,000.00 Dr', -250000, 2],
    ['2,50,000.00 CR', 250000, 2], ['473.890000', 473.89, 6],
  ])('reads %s', (text, value, places) => {
    expect(parseAmount(text)).toMatchObject({ value, places })
  })

  it.each(['', '-', '2,5,0000', '1.2.3', 'abc', '12,34'])('refuses %s', (text) => {
    expect(parseAmount(text)).toBeNull()
  })

  it('reads debit and credit columns, a Dr/Cr column, and a signed amount', () => {
    const cols = { date: 0, narration: 1, reference: -1, debit: 2, credit: 3, amount: -1, drcr: -1, balance: -1, counterparty: -1 }
    const two = statementRows([{ line: 2, cells: ['12/03/2026', 'TEST', '2,50,000.00', ''] }, { line: 3, cells: ['13/03/2026', 'TEST', '0.00', '500'] }], cols)
    expect(two.rows.map((r) => [r.direction, r.amount])).toEqual([['debit', 250000], ['credit', 500]])
    const one = statementRows([{ line: 2, cells: ['12/03/2026', 'TEST', '1,000', 'Dr'] }, { line: 3, cells: ['12/03/2026', 'TEST', '-20', ''] },
      { line: 4, cells: ['12/03/2026', 'TEST', '30', ''] }], { ...cols, debit: -1, credit: -1, amount: 2, drcr: 3 })
    expect(one.rows.map((r) => [r.direction, r.amount])).toEqual([['debit', 1000], ['debit', 20], ['credit', 30]])
    const bad = statementRows([{ line: 9, cells: ['Opening balance', '', '', ''] }, { line: 10, cells: ['12/03/2026', 'x', '', ''] }], cols)
    expect(bad).toEqual({ rows: [], skipped: [{ line: 9, why: 'no date it can read' }, { line: 10, why: 'no amount it can read' }] })
  })
})

describe('references and names', () => {
  it('finds NEFT, RTGS and UPI/IMPS references', () => {
    expect(findUtrs('NEFT/SBINN26071000001/TEST PAYEE')).toEqual([{ kind: 'NEFT', value: 'SBINN26071000001' }])
    expect(findUtrs('RTGS-HDFCR52026031200000001-TEST')).toEqual([{ kind: 'RTGS', value: 'HDFCR52026031200000001' }])
    expect(findUtrs('UPI/607200000001/TEST/okaxis')).toEqual([{ kind: 'UPI', value: '607200000001' }])
    expect(findUtrs('imps/p2a/607200000002/test')).toEqual([{ kind: 'IMPS', value: '607200000002' }])
  })

  it('stays silent on account numbers and other digits', () => {
    expect(findUtrs('NEFT/TEST/A/C 9999000011112222')).toEqual([])
    expect(findUtrs('ATM WDL 607200000001 TEST BRANCH')).toEqual([]) // twelve digits, but not a UPI or IMPS row
    expect(findUtrs('UPI/600000000001/TEST')).toEqual([]) // day 000 of the year
    expect(findUtrs('NEFT/SBINN2607100000/TEST')).toEqual([]) // one digit short
  })

  it('matches exchange names only as whole canonical names', () => {
    expect(namesIn('UPI/607200000001/COINDCX TEST', NAMES)).toEqual(['CoinDCX'])
    expect(namesIn('IMPS to crypto.com test', NAMES)).toEqual(['Crypto.com'])
    expect(namesIn('UPI/COINDXC/TEST', NAMES)).toEqual([]) // misspelt
    expect(namesIn('NEFT/BOOKXPRESS TEST', NAMES)).toEqual([]) // OKX inside a word
    expect(namesIn('UPI/WAZIRX TEST', NAMES)).toEqual([]) // not a name the list has
  })
})

const row = (over) => ({ line: 2, date: '2026-03-12', time: '', direction: 'debit', amount: 250000, places: 2, text: '250000.00',
  narration: 'TEST', reference: '', counterparty: '', balance: null, ...over })
const REPORTED = [{ amount: 250000, currency: 'INR', date: '2026-03-12' }]

describe('matching', () => {
  it('fires on the row whose amount and date match a reported payment', () => {
    const rows = [row({ line: 2, amount: 1000, text: '1000.00' }), row({ line: 3, date: '2026-03-13' })]
    expect(matchRows(rows, { payments: REPORTED }).map((m) => [m.row.line, m.reasons, m.payment])).toEqual([[3, ['amount_date'], 0]])
  })

  it('stays silent on near misses: the amount off, the date outside the window, another currency', () => {
    const near = [row({ amount: 250000.5, text: '250000.50' }), row({ amount: 249999, text: '249999.00' }),
      row({ date: '2026-03-15' }), row({ date: '2026-03-09' })]
    expect(matchRows(near, { payments: REPORTED })).toEqual([])
    expect(matchRows([row()], { payments: REPORTED, currency: 'USDT' })).toEqual([])
    expect(matchRows([row()], { payments: [{ ...REPORTED[0], date: null }] })).toEqual([]) // a time withheld from this reader
  })

  it('compares to the places the statement prints, and at least two', () => {
    expect(sameAmount({ amount: 473.89, places: 2 }, 473.890001)).toBe(true)
    expect(sameAmount({ amount: 473.89, places: 6 }, 473.890001)).toBe(false)
    expect(sameAmount({ amount: 474, places: 0 }, 473.89)).toBe(false)
  })

  it("lines an exchange's statement up with the case's own payment, its hash and the exchange's name", () => {
    const payments = casePayments(PAID)
    expect(payments).toEqual([{ amount: 473.89, currency: 'USDT', date: '2024-02-23', timestamp: T0.timestamp, tx_hash: T0.hash }])
    const deposit = row({ date: '2024-02-23', time: '21:46', direction: 'credit', amount: 473.89, places: 2, text: '473.89',
      reference: T0.hash, narration: 'Deposit TEST', counterparty: 'Binance TEST' })
    const [m] = matchRows([deposit], { payments, currency: 'usdt', names: NAMES, hashes: [T0.hash] })
    expect(m.reasons).toEqual(['amount_date', 'exchange', 'tx_hash'])
    expect(m.exchange).toBe('Binance')
  })

  it('keeps a hash out of the narration it saves, and a UTR as the reference', () => {
    const m = matchRows([row({ narration: `TEST ${T0.hash}`, reference: 'not a ref!' })], { hashes: [T0.hash] })[0]
    expect(toSaved(m)).toMatchObject({ reference: T0.hash, narration: 'TEST [hash]', reasons: ['tx_hash'], amount: '250000.00' })
    const u = matchRows([row({ narration: 'NEFT/SBINN26071000001/TEST', reference: '000123' })])[0]
    expect(toSaved(u)).toMatchObject({ reference: 'SBINN26071000001', reasons: ['utr'] })
  })
})

describe('the timeline', () => {
  it("puts the statement's rows beside the trace's own times, in India's time", () => {
    const m = { row: row({ date: '2024-02-23', time: '', text: '40,000.00' }), reasons: ['amount_date'], exchange: '' }
    const events = timeline([m], PAID)
    expect(events[0]).toEqual({ date: '2024-02-23', time: '', side: 'statement', text: 'Debit 40,000.00' })
    expect(events[1]).toEqual({ date: '2024-02-23', time: '21:46', side: 'chain', text: `Payment of ${T0.value_native} USDT reached the reported wallet` })
    const arrivals = events.filter((e) => e.text.includes('reached Binance'))
    expect(arrivals.length).toBe(fixture.transfers.filter((t) => t.to === fixture.attribution.address).length)
  })

  it('has no chain events for a case with no times', () => {
    expect(timeline([], { intake: { mode: 'address', payments: [] } })).toEqual([])
  })
})
