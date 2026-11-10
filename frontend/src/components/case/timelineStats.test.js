import { describe, expect, it } from 'vitest'
import { emptyIn, frozeOn, hopToExchange, leftWithin, shareText, spanText, timelineStats } from './timelineStats'
import recordings from '../../../../backend/data/recorded_demos.json'

// The Timeline tab's stat cards, worked from demo 11 (Tron USDT, traced from
// the address). The pack's figures were rounded the wrong way: 9,890 arrived
// 16 Dec 2024 12:13:45 UTC; 440 + 451 + 6,000 = 6,891 of the 9,891 that left
// had gone by 18 Dec 09:05:36, 44 h 51 m later (69.67%, cut to 69.6%, not
// 70%); hop 1 got 340 at 19 Dec 09:06:33 and sent 1,148.688 into Binance at
// 12:33:03, 3 h 26 m 30 s later (3 h 26 m, not 3 h 27 m); the last of it
// left 26 Dec 11:34:15, 9.97 days after it came in.
const demo = recordings.find((r) => r.demo === 11).result
const SEED = demo.address
const HOP1 = demo.trace_path[1].address

describe('shareText', () => {
  it.each([
    [0.696690, '69.6%'], [0.69999, '69.9%'], [0.7, '70%'], [0.999999, '99.9%'], [1, '100%'], [0.0004, 'under 0.1%'], [0, '0%'],
  ])('writes %s as %s, cut, never rounded up', (share, text) => {
    expect(shareText(share)).toBe(text)
  })
})

describe('spanText', () => {
  it.each([
    [12_390, '3 h 26 m'], [12_419, '3 h 26 m'], [3 * 3600, '3 h 0 m'], [59 * 60 + 59, '59 m'], [26 * 3600 + 61, '1 d 2 h'], [0, '0 m'],
  ])('writes %i seconds as %s, cut to the unit', (seconds, text) => {
    expect(spanText(seconds)).toBe(text)
  })
})

describe('demo 11', () => {
  it('left the wallet: 69.6% within 45 h, cut from 6,891 of 9,891', () => {
    const card = leftWithin(demo)
    expect(card.share).toBeCloseTo(6891 / 9891, 9)
    expect(card).toMatchObject({ value: '69.6%', caption: 'left the wallet within 45 h' })
  })

  it('reached the exchange 3 h 26 m after hop 1, cut, not rounded up', () => {
    expect(hopToExchange(demo)).toMatchObject({ seconds: 12_390, value: '3 h 26 m', caption: 'from hop 1 to Binance' })
  })

  it('emptied the wallet in 10 days, with neither statement side at its limit', () => {
    expect(emptyIn(demo)).toMatchObject({ days: 10, value: '10 days', caption: 'until the wallet was empty' })
  })

  it('reads the freeze day from the label text when the case has no frozen_on', () => {
    expect(demo.risk_matches.some((m) => 'frozen_on' in m)).toBe(false)
    expect(frozeOn(demo)).toMatchObject({ on: '2026-09-11', value: '11 Sep 2026', caption: 'Tether froze both wallets' })
  })

  it('draws the four cards in the pack order, with their tones', () => {
    expect(timelineStats(demo).map((c) => [c.key, c.value, c.tone])).toEqual([
      ['left', '69.6%', ''], ['exchange', '3 h 26 m', 'go'], ['empty', '10 days', ''], ['frozen', '11 Sep 2026', 'risk'],
    ])
  })
})

describe('each card is left out when its data is missing', () => {
  const statement = (over) => ({ ...demo, statement: { ...demo.statement, ...over } })

  it('claims no empty wallet when either statement side hit its row limit', () => {
    const full = (n) => Array.from({ length: n }, (_, i) => ({ ...demo.statement.debits[0], tx: `x${i}` }))
    expect(emptyIn(statement({ debits: full(25) }))).toBeNull()
    expect(emptyIn(statement({ credits: [...demo.statement.credits, ...full(22)] }))).toBeNull()
    expect(emptyIn(statement({ rows_per_side: 11 }))).toBeNull()
    expect(emptyIn(statement({ rows_per_side: 12 }))).not.toBeNull()
  })

  it('claims no empty wallet while money is still in it', () => {
    const debits = demo.statement.debits.filter((d) => d.amount !== 500)
    expect(emptyIn(statement({ debits }))).toBeNull()
  })

  it('gives no share when the money out is past the row limit, or there is no statement', () => {
    expect(leftWithin(statement({ rows_per_side: 11 }))).toBeNull()
    expect(leftWithin({ ...demo, statement: null })).toBeNull()
    expect(timelineStats({ ...demo, statement: null }).map((c) => c.key)).toEqual(['exchange', 'frozen'])
  })

  it('starts a payment trace at its first payment, and gives no share when its times are withheld', () => {
    const at = 1734351225 // 16 Dec 2024 12:13:45 UTC, the 9,890 credit
    const payment = (timestamp) => ({ ...demo, intake: { mode: 'payment', payments: [{ tx_hash: 'a'.repeat(64), amount: 9890, timestamp }] } })
    expect(leftWithin(payment(at)).value).toBe('69.6%')
    expect(leftWithin(payment(at - 3 * 3600)).caption).toBe('left the wallet within 48 h')
    expect(leftWithin(payment(null))).toBeNull()
  })

  it('times no route that is missing a hop, ends at no exchange, or runs in reverse', () => {
    expect(hopToExchange({ ...demo, transfers: demo.transfers.filter((t) => t.from !== HOP1) })).toBeNull()
    expect(hopToExchange({ ...demo, exchange: null })).toBeNull()
    expect(hopToExchange({ ...demo, direction: 'incoming' })).toBeNull()
    expect(hopToExchange({ ...demo, trace_path: demo.trace_path.slice(0, 1) })).toBeNull()
  })

  it('times the route from the first transfer into hop 1 to the first into the exchange after it', () => {
    const late = { hash: 'late', from: SEED, to: HOP1, value_native: 1, timestamp: 1734599193 - 600 }
    expect(hopToExchange({ ...demo, transfers: [...demo.transfers, late] }).value).toBe('3 h 36 m')
  })

  it('prefers frozen_on, and says nothing when no freeze has a day', () => {
    const frozen = demo.risk_matches.map((m, i) => ({ ...m, frozen_on: i ? '2026-09-12' : '2026-09-10' }))
    expect(frozeOn({ ...demo, risk_matches: frozen })).toMatchObject({ value: '10 Sep 2026', caption: 'Tether froze both wallets, the first that day' })
    // A null frozen_on is no day: the label's own words still give one.
    expect(frozeOn({ ...demo, risk_matches: [{ ...demo.risk_matches[0], frozen_on: null }] })).toMatchObject({ value: '11 Sep 2026' })
    expect(frozeOn({ ...demo, risk_matches: [{ ...demo.risk_matches[0], frozen_on: null, label: 'USDT frozen by Tether' }] })).toBeNull()
    expect(frozeOn({ ...demo, risk_matches: [{ ...demo.risk_matches[0], label: 'USDT frozen by Tether' }] })).toBeNull()
    expect(frozeOn({ ...demo, risk_matches: [demo.risk_matches[0]] }).caption).toBe('Tether froze 1 wallet')
  })

  it('counts every frozen wallet, and says how many of them have a day', () => {
    const third = { ...demo.risk_matches[1], address: 'T3rd', label: 'USDT frozen by Tether' }
    expect(frozeOn({ ...demo, risk_matches: [...demo.risk_matches, third] }).caption).toBe('Tether froze 2 of 3 wallets')
    const undated = demo.risk_matches.map((m, i) => (i ? { ...m, label: 'USDT frozen by Tether' } : m))
    expect(frozeOn({ ...demo, risk_matches: undated }).caption).toBe('Tether froze 1 of 2 wallets')
  })

  it('cleans an issuer name from outside before showing it', () => {
    const odd = demo.risk_matches.map((m) => ({ ...m, issuer: 'Te​ther' }))
    expect(frozeOn({ ...demo, risk_matches: odd }).caption).toBe('Tether froze both wallets')
  })
})
