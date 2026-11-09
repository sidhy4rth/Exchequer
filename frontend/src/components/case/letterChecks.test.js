import { describe, expect, it } from 'vitest'
import { blanks, checks, kindOf, lines, pieces, recipientOf } from './letterChecks'

// What the Letters tab says about a draft (request_letters.py): the blanks
// the officer must fill, named from the words beside each, and the checks
// that hold for this letter and case, each shown only when it is true.
const B = '[____________________]'
const EXCHANGE_WALLET_LETTER = [
  'DRAFT — for the investigating officer to review, complete and sign.',
  `From      : ${B} (name, rank, unit, official e-mail and phone)`,
  `Reference : ${B} (FIR / complaint / NCRP acknowledgement number)`,
  'Date      : 10 November 2026',
  `To        : Binance — Law Enforcement / Compliance team ${B} (officer to find and confirm the right channel)`,
  `   The victim's payments: ${B} (officer to state amounts, dates and references`,
  '   from the complaint). This trace followed the reported address\'s history, not specific payments.',
  '   On a pro-rata estimate from the public records, about 635.000000 USDT of everything the',
  '         received 635.000000 USDT in 2 transfer(s), 2024-12-19 14:36 IST (09:06 UTC)',
  `4. In exercise of the powers under ${B}`,
  '   This request is not about the wallet TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf itself.',
  `   consider restricting withdrawals from them pending this investigation ${B}.`,
  `Amount    : ${B} (officer to state)`,
  `Transactions into TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf: ${B} (officer to add)`,
  '',
  B,
  '(signature, name, designation, seal)',
].join('\n')

const CASE = { asset: 'USDT', exchange: 'Binance', exchange_label: 'Binance-Hot 7', estimates: { conservative: 635 }, intake: { mode: 'address', payments: [] } }

describe('the blanks in a draft', () => {
  it('names each from the words beside it, in the order they appear', () => {
    expect(blanks(EXCHANGE_WALLET_LETTER)).toEqual([
      'From: name, rank, unit, official e-mail and phone',
      'Reference: FIR / complaint / NCRP acknowledgement number',
      'To: find and confirm the right channel',
      "The victim's payments: state amounts, dates and references from the complaint",
      'The legal provision',
      'After "pending this investigation"',
      'Amount',
      'Transactions into TDqSquXBgU…89dkhSCf',
      'Signature, name, designation, seal',
    ])
  })

  it('finds none in a letter with none, and reads any length of underscores', () => {
    expect(blanks('Nothing to fill.')).toEqual([])
    expect(blanks('Under [____] (the legal provision this request is made under, officer to state):')).toEqual(['The legal provision this request is made under, officer to state'])
  })

  it('splits the text into plain runs and numbered blanks, losing nothing', () => {
    const parts = pieces(`a ${B} b ${B}`)
    expect(parts).toEqual(['a ', { blank: 0, text: B }, ' b ', { blank: 1, text: B }])
    expect(parts.map((p) => (typeof p === 'string' ? p : p.text)).join('')).toBe(`a ${B} b ${B}`)
  })

  it('lays the text out line by line for a proportional font: indents kept as a number, column padding closed up', () => {
    expect(lines(`From      : ${B} (name)\n\n   Hop 1:  TX\n         tx ab`)).toEqual([
      { indent: 0, hang: 0, parts: ['From: ', { blank: 0, text: B }, ' (name)'] },
      { indent: 0, hang: 0, parts: [] },
      { indent: 3, hang: 0, parts: ['Hop 1: TX'] },
      { indent: 9, hang: 0, parts: ['tx ab'] },
    ])
  })

  it('flows the lines the server wrapped back into one paragraph, and keeps items, hops, txs and fields apart', () => {
    const text = [
      'From      : Officer',
      'Date      : 10 November 2026',
      '',
      `1. This office is investigating a complaint. The wallet`,
      '   address T1 was reported in connection with it.',
      `   The victim's payments: ${B} (officer to state amounts, dates and references`,
      '   from the complaint).',
      `4. In exercise of the powers under ${B}`,
      '   [e.g. Section 94], you are requested to furnish:',
      '   (a) the account statement and all deposits,',
      '       from the date of the first transfer;',
      '   (b) linked bank accounts.',
      '   This request is not about the wallet T2 itself.',
      'Amount    : about 635.000000 USDT',
      '            (the smallest estimate the case holds)',
      '  Hop 1: TX',
      '         received 635.000000 USDT in 2 transfer(s), 2024-12-19 14:36 IST',
      '         to 2024-12-24 20:29 IST',
      '         tx ab',
      '         tx cd',
      B,
      '(signature, name, designation, seal)',
    ].join('\n')
    const flat = lines(text).map((l) => [l.indent, l.hang, l.parts.map((p) => (typeof p === 'string' ? p : '[B]')).join('')])
    expect(flat).toEqual([
      [0, 0, 'From: Officer'],
      [0, 0, 'Date: 10 November 2026'],
      [0, 0, ''],
      [0, 3, "1. This office is investigating a complaint. The wallet address T1 was reported in connection with it. The victim's payments: [B] (officer to state amounts, dates and references from the complaint)."],
      [0, 3, '4. In exercise of the powers under [B] [e.g. Section 94], you are requested to furnish:'],
      [3, 4, '(a) the account statement and all deposits, from the date of the first transfer;'],
      [3, 4, '(b) linked bank accounts.'],
      [3, 0, 'This request is not about the wallet T2 itself.'],
      [0, 0, 'Amount: about 635.000000 USDT (the smallest estimate the case holds)'],
      [2, 0, 'Hop 1: TX'],
      [9, 0, 'received 635.000000 USDT in 2 transfer(s), 2024-12-19 14:36 IST to 2024-12-24 20:29 IST'],
      [9, 0, 'tx ab'],
      [9, 0, 'tx cd'],
      [0, 0, '[B]'],
      [0, 0, '(signature, name, designation, seal)'],
    ])
    // Each blank keeps its number, in order, wherever its line lands.
    expect(lines(text).flatMap((l) => l.parts.filter((p) => typeof p !== 'string').map((p) => p.blank))).toEqual([0, 1, 2])
  })

  it('keeps each tx and each lone wallet on its own line, so a note after them reads as its own paragraph', () => {
    // The freeze letters (request_letters.py): a tx line or a listed wallet
    // is never wrapped, so the note that follows at its indent is not part of it.
    const text = [
      'Wallets   : (officer to confirm each)',
      '     TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU',
      '     TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf',
      '     (2 more wallets where the traced USDT stopped are not listed)',
      'Transactions into it (times in IST, with UTC):',
      `     tx ${'ab'.repeat(32)}, 2024-12-19 18:03 IST (12:33 UTC)`,
      `     tx ${'cd'.repeat(32)}, 2024-12-24 20:33 IST (15:03 UTC)`,
      '     (the earliest that can carry the traced funds; 25 other transfers into it in this trace',
      '     are not part of this request)',
      '         tx ef',
      '         (first 1 of 27 transfers shown; all are listed in the attached report)',
    ].join('\n')
    expect(lines(text).map((l) => [l.indent, l.parts.join('')])).toEqual([
      [0, 'Wallets: (officer to confirm each)'],
      [5, 'TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU'],
      [5, 'TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf'],
      [5, '(2 more wallets where the traced USDT stopped are not listed)'],
      [0, 'Transactions into it (times in IST, with UTC):'],
      [5, `tx ${'ab'.repeat(32)}, 2024-12-19 18:03 IST (12:33 UTC)`],
      [5, `tx ${'cd'.repeat(32)}, 2024-12-24 20:33 IST (15:03 UTC)`],
      [5, '(the earliest that can carry the traced funds; 25 other transfers into it in this trace are not part of this request)'],
      [9, 'tx ef'],
      [9, '(first 1 of 27 transfers shown; all are listed in the attached report)'],
    ])
  })
})

describe('the checks on a draft', () => {
  const titles = (text, result = CASE) => checks(text, result).map((c) => c.title)

  it("ticks an exchange's own wallet letter for asking about the deposits, the stated estimate and IST", () => {
    expect(titles(EXCHANGE_WALLET_LETTER)).toEqual([
      "Asks about the deposits, not the wallet's owner",
      'States 635 USDT',
      'Dated in IST',
    ])
    expect(checks(EXCHANGE_WALLET_LETTER, CASE)[0].detail).toBe("Binance-Hot 7 is the exchange's own wallet; it belongs to no one customer")
    expect(checks(EXCHANGE_WALLET_LETTER, CASE)[2].detail).toBe('times shown in IST, with UTC beside them')
  })

  // The urgent freeze letter (g/freeze-letter's _freeze_header) wraps its
  // ask at 95 columns, so the phrase can break over a line anywhere.
  it("ticks the urgent freeze letter's ask about the deposits, however the server wrapped it", () => {
    const tron = '   Please hold, now, funds up to the amount below in the customer account(s) credited by the\n   transactions below into your wallet TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf (this request is not\n   about the wallet itself), pending a formal request from this office.'
    const eth = '   Please hold, now, funds up to the amount below in the customer account(s) credited by the\n   transactions below into your wallet 0x28c6c06298d514db089934071355e5743bf21d60 (this request\n   is not about the wallet itself), pending a formal request from this office.'
    expect(titles(tron)).toEqual(["Asks about the deposits, not the wallet's owner"])
    expect(titles(eth)).toEqual(["Asks about the deposits, not the wallet's owner"])
    expect(titles('This request is about the wallet itself.')).toEqual([])
  })

  it("ticks the complainant's payment only when the letter carries its hash", () => {
    const hash = 'fd' + 'e5'.repeat(31)
    const paid = { ...CASE, intake: { mode: 'payment', payments: [{ tx_hash: hash }] } }
    expect(titles(EXCHANGE_WALLET_LETTER, paid)).not.toContain("The complainant's payment is filled in")
    expect(titles(`${EXCHANGE_WALLET_LETTER}\n  paid in tx ${hash}`, paid)).toContain("The complainant's payment is filled in")
  })

  it('claims nothing the letter does not show', () => {
    const bare = 'To        : Tether Operations Limited\nDate      : 10 November 2026\n'
    expect(titles(bare)).toEqual([])
    // A stated amount other than the case's smallest estimate is not ticked.
    expect(titles('Amount    : about 600.000000 USDT')).toEqual([])
    expect(titles('about 635.000000 USDT', { ...CASE, estimates: {} })).toEqual([])
  })

  it('writes an estimate of a thousand or more with its separators, as the letter does', () => {
    expect(titles('Amount    : about 1,234.500000 USDT', { ...CASE, estimates: { conservative: 1234.5 } })).toEqual(['States 1,234.5 USDT'])
  })
})

describe('who a letter goes to', () => {
  it('names the exchange or Tether for each letter the backend lists, and any other from its title', () => {
    const result = { exchange: 'Bin​ance' }
    expect(recipientOf({ to: 'exchange', title: 'Request to Binance' }, result)).toBe('Binance')
    expect(recipientOf({ to: 'exchange-freeze', title: 'Urgent freeze request to Binance' }, result)).toBe('Binance')
    expect(recipientOf({ to: 'tether-freeze', title: 'Urgent freeze request to Tether' }, result)).toBe('Tether')
    expect(recipientOf({ to: 'bank', title: 'Request to State‮ Bank' }, result)).toBe('State Bank')
  })

  it('logs a letter the requests API knows under its own kind, and any other as other', () => {
    expect(['exchange', 'tether', 'exchange-freeze', 'tether-freeze', 'bank', 'exchange-x'].map(kindOf))
      .toEqual(['exchange', 'tether', 'exchange-freeze', 'tether-freeze', 'other', 'other'])
  })
})
