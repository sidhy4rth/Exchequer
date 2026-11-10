import { describe, expect, it } from 'vitest'
import { shareText, spread, spreadColumns, victimFlowLayout } from './victimFlowLayout'
import flow from '../../test/victim-flow-11.json'
import recordings from '../../../../backend/data/recorded_demos.json'

// The Flow tab's Sankey, laid out without drawing it. Demo 11's flow comes
// from backend/app/victim_flow.py run on the recording (src/test/
// victim-flow-11.json): 9,891 USDT from the reported wallet, 959.58 at
// Binance (635 along the route the finding names, the rest through the
// frozen TZ7L), 8,732.34 beyond the 2-hop limit, 196.78 not followed at
// TZ7L's fan-out limit, and 2.30 left in TT4y.
const graph = recordings.find((r) => r.demo === 11).result.graph
const SEED = 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts'
const TXGO = 'TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU'
const TZ7L = 'TZ7LmC6zBipRx6tDMavbzaF8piBpw89cNz'
const TT4Y = 'TT4yg2GguWvN5j8Xeb7nUB5Hg2wWd1dFp3'
const TBCV = 'TBCvfA89EYAgTWFcfSzmjFwHvjFHWHZuA4'
const amountOf = (kind) => flow.buckets.find((b) => b.kind === kind).amount
const sum = (xs) => xs.reduce((s, x) => s + x, 0)

describe('the victim-flow layout', () => {
  const lay = victimFlowLayout(flow, { graph, width: 1000, height: 420 })

  it('puts the reported wallet left, its first hop in the middle and the buckets on the right edge', () => {
    expect(lay.seed.address).toBe(SEED)
    expect(lay.seed.x).toBe(0)
    expect(new Set(lay.hop1.map((n) => n.x)).size).toBe(1)
    expect(lay.hop1[0].x).toBeGreaterThan(300)
    expect(lay.hop1[0].x).toBeLessThan(700)
    for (const b of lay.buckets) expect(b.x + lay.bar).toBe(1000)
    expect(lay.buckets.map((b) => b.kind).sort()).toEqual(['beyond_limit', 'exchange', 'left', 'not_followed'])
  })

  it('keeps the route, the frozen wallet and the big branches, and folds the small ones', () => {
    expect(lay.hop1.map((n) => n.address ?? `${n.count} more`)).toEqual([TXGO, TZ7L, TT4Y, TBCV, '5 more'])
    const more = lay.hop1.at(-1)
    expect(more.amount).toBeCloseTo(500 + 500 + 451 + 300 + 40, 6)
    expect(lay.hop1[0].lead).toBe(true)
    expect(lay.hop1[1].risk).toBe('frozen')
    expect(lay.seed.risk).toBe('frozen')
  })

  it('sizes every ribbon by the victim\'s money, never by what passed through', () => {
    const k = (lay.seed.y1 - lay.seed.y0) / flow.totals.denominator
    for (const r of lay.ribbons) {
      expect(r.sy1 - r.sy0).toBeCloseTo(r.amount * k, 6)
      expect(r.ty1 - r.ty0).toBeCloseTo(r.amount * k, 6)
    }
    for (const b of lay.buckets) {
      expect(sum(lay.ribbons.filter((r) => r.to === b.kind).map((r) => r.amount))).toBeCloseTo(amountOf(b.kind), 6)
      expect(b.amount).toBeCloseTo(amountOf(b.kind), 6)
    }
    // TXgo passed 45,968 USDT to Binance; the victim's share of it is 959.58.
    const exchange = lay.buckets.find((b) => b.kind === 'exchange')
    expect(exchange.y1 - exchange.y0).toBeCloseTo(959.583566685 * k, 6)
    expect(sum(lay.ribbons.filter((r) => r.from === SEED && r.to === TXGO).map((r) => r.amount))).toBeCloseTo(635, 9)
  })

  it('orders the buckets by where their money comes from, the exchange at the top', () => {
    expect(lay.buckets[0].kind).toBe('exchange')
    const ys = lay.buckets.map((b) => b.y0)
    expect(ys).toEqual([...ys].sort((a, b) => a - b))
    const rows = lay.hop1.map((n) => n.y0)
    expect(rows).toEqual([...rows].sort((a, b) => a - b))
  })

  it('colours money by where it ended, and draws each link as its flow says', () => {
    const ribbon = (from, to, kind) => lay.ribbons.filter((r) => r.from === from && r.to === to && (!kind || r.kind === kind))
    expect(ribbon(TXGO, 'exchange').map((r) => [r.colour, r.style])).toEqual([['go', 'faded']])
    expect(ribbon(TZ7L, 'exchange').map((r) => [r.colour, r.style])).toEqual([['go', 'dashed']])
    expect(ribbon(TT4Y, 'beyond_limit').map((r) => [r.colour, r.style])).toEqual([['grey', 'dashed']])
    expect(ribbon(TT4Y, 'left')[0].amount).toBeCloseTo(2.297459, 9)
    // The reported wallet's own links are solid, split by where the money ended.
    expect(ribbon(SEED, TT4Y).every((r) => r.style === 'solid')).toBe(true)
    expect(ribbon(SEED, TT4Y).map((r) => r.colour)).toContain('go')
    expect(ribbon(SEED, TT4Y, 'beyond_limit')[0].colour).toBe('grey')
  })

  it('marks a first-hop row whose money went on through the frozen wallet', () => {
    const tt4y = lay.hop1.find((n) => n.address === TT4Y)
    expect(tt4y.via).toEqual([{ address: TZ7L, category: 'frozen', amount: 300 }])
    expect(lay.hop1.find((n) => n.address === TZ7L).via).toEqual([])
    expect(lay.hop1.find((n) => n.address === TXGO).via).toEqual([])
  })

  it('draws each ribbon from the right of its source to the left of its target', () => {
    for (const r of lay.ribbons) {
      expect(r.path.startsWith(`M${r.x0} ${r.sy0}`)).toBe(true)
      expect(r.x1).toBeGreaterThan(r.x0)
    }
  })
})

// A small flow, written by hand, for the cases demo 11 does not have.
function tiny({ links, nodes, buckets, lead = [] }) {
  const total = sum(buckets.map((b) => b.amount))
  return {
    status: 'estimated',
    nodes: nodes.map(([address, role, victim_in, left = 0, basis = role === 'seed' ? 'seed_outflow' : role === 'wallet' ? 'traced_only' : null]) => ({ address, role, victim_in, left, basis })),
    links: links.map(([source, target, victim, style = 'solid']) => ({ source, target, victim, gross: victim, style })),
    buckets: buckets.map((b) => ({ addresses: [], action: null, ...b, share: b.amount / total })),
    totals: { denominator: total, basis: 'seed_outflow', accounted: total },
    lead: { path: lead, reached: null },
    passed_through: [],
    notes: [],
    stops: [],
  }
}

describe('the layout of other shapes', () => {
  it('lets the order of the first hop decide the order of the buckets', () => {
    const lay = victimFlowLayout(tiny({
      nodes: [['S', 'seed', 15], ['A', 'wallet', 10], ['B', 'wallet', 5], ['X', 'beyond_limit', 10], ['E', 'exchange', 5]],
      links: [['S', 'A', 10], ['S', 'B', 5], ['A', 'X', 10], ['B', 'E', 5]],
      buckets: [{ kind: 'exchange', amount: 5 }, { kind: 'beyond_limit', amount: 10 }],
    }))
    expect(lay.hop1.map((n) => n.address)).toEqual(['A', 'B'])
    expect(lay.buckets.map((b) => b.kind)).toEqual(['beyond_limit', 'exchange'])
  })

  it('sends money that came back, or was swapped, to other', () => {
    const lay = victimFlowLayout(tiny({
      nodes: [['S', 'seed', 10], ['A', 'wallet', 10], ['B', 'wallet', 0], ['X', 'beyond_limit', 4]],
      links: [['S', 'A', 10], ['A', 'S', 4], ['A', 'B', 2], ['A', 'X', 4]],
      buckets: [{ kind: 'beyond_limit', amount: 4 }, { kind: 'other', amount: 6 }],
    }), { graph: { nodes: [], edges: [{ source: 'A', target: 'B', swap: { router_label: 'Uniswap' } }] } })
    const other = lay.ribbons.filter((r) => r.to === 'other')
    expect(sum(other.map((r) => r.amount))).toBeCloseTo(6, 9)
  })

  it('carries the reported wallet\'s own remainder through the first hop as a gap, with no bar', () => {
    const lay = victimFlowLayout(tiny({
      nodes: [['S', 'seed', 10], ['A', 'wallet', 6], ['X', 'beyond_limit', 6]],
      links: [['S', 'A', 6], ['A', 'X', 6]],
      buckets: [{ kind: 'beyond_limit', amount: 6 }, { kind: 'not_followed', amount: 4 }],
    }))
    const gap = lay.hop1.find((n) => n.gap)
    expect(gap.amount).toBeCloseTo(4, 9)
    expect(lay.hop1.at(-1)).toBe(gap)
    expect(lay.ribbons.filter((r) => r.to === 'not_followed').map((r) => r.from)).toEqual(['gap'])
  })

  it('marks a frozen wallet deeper than the first hop on the row its money left by', () => {
    const flow = tiny({
      nodes: [['S', 'seed', 10], ['A', 'wallet', 10], ['F', 'wallet', 8], ['E', 'exchange', 8], ['X', 'beyond_limit', 2]],
      links: [['S', 'A', 10], ['A', 'F', 8], ['A', 'X', 2], ['F', 'E', 8]],
      buckets: [{ kind: 'exchange', amount: 8 }, { kind: 'beyond_limit', amount: 2 }],
    })
    flow.passed_through = [{ address: 'F', category: 'frozen', victim_in: 8 }]
    const lay = victimFlowLayout(flow)
    expect(lay.hop1.map((n) => n.address)).toEqual(['A'])
    expect(lay.hop1[0].via).toEqual([{ address: 'F', category: 'frozen', amount: 8 }])
  })

  it('folds a small branch only when there are two or more', () => {
    const lay = victimFlowLayout(tiny({
      nodes: [['S', 'seed', 100], ['A', 'wallet', 99], ['B', 'wallet', 1], ['X', 'beyond_limit', 100]],
      links: [['S', 'A', 99], ['S', 'B', 1], ['A', 'X', 99], ['B', 'X', 1]],
      buckets: [{ kind: 'beyond_limit', amount: 100 }],
    }))
    expect(lay.hop1.map((n) => n.address)).toEqual(['A', 'B'])
  })
})

describe('a share as text', () => {
  it.each([
    [0.097016, '9.7%'], [0.0999, '9.9%'], [0.882857, '88.2%'], [1, '100%'], [0, '0%'], [0.00001, 'under 0.1%'],
  ])('%s reads %s, never rounded up', (share, text) => {
    expect(shareText(share)).toBe(text)
  })
})

describe('labels that would overlap', () => {
  it('are pushed apart in order, and kept inside the box', () => {
    expect(spread([5, 10, 100], 24, 420)).toEqual([12, 36, 100])
    expect(spread([400, 410, 415], 24, 420)).toEqual([360, 384, 408])
  })

  it('are pushed apart across the middle and right columns, which share the space between them', () => {
    const [hops, ends] = spreadColumns([[100, 200], [100, 205, 300]], 24, 420)
    const all = [...hops, ...ends].sort((a, b) => a - b)
    for (let i = 1; i < all.length; i += 1) expect(all[i] - all[i - 1]).toBeGreaterThanOrEqual(24)
    expect(hops[0]).toBeLessThan(hops[1])
    expect(ends[0]).toBeLessThan(ends[1])
    expect(ends[1]).toBeLessThan(ends[2])
  })

  it('keep demo 11\'s hop and bucket labels apart', () => {
    const lay = victimFlowLayout(flow, { graph, height: 420 })
    const mid = (n) => (n.y0 + n.y1) / 2
    const [hops, ends] = spreadColumns([lay.hop1.filter((h) => !h.gap).map(mid), lay.buckets.map(mid)], 24, 420)
    const all = [...hops, ...ends].sort((a, b) => a - b)
    for (let i = 1; i < all.length; i += 1) expect(all[i] - all[i - 1]).toBeGreaterThanOrEqual(24 - 1e-9)
    for (const y of all) expect(y).toBeLessThanOrEqual(420)
  })
})
