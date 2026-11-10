import { describe, expect, it } from 'vitest'
import { entityGroups, groupLayout } from './entityGroups'
import recordings from '../../../../backend/data/recorded_demos.json'

// Demo 11 (Tron USDT, traced from the address): 30 wallets, 34 transfers.
// The reported wallet TUVN… is frozen too, and sent 6,000 to the split wallet
// TT4y…, which paid 8 recipients, one of them TZ7L…, also frozen. TXgo… is
// the one wallet between the reported wallet and Binance-Hot 7.
const demo = recordings.find((r) => r.demo === 11).result
const SEED = 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts'
const SPLIT = 'TT4yg2GguWvN5j8Xeb7nUB5Hg2wWd1dFp3'
const FROZEN = 'TZ7LmC6zBipRx6tDMavbzaF8piBpw89cNz'
const ROUTE = 'TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU'
const BINANCE = 'TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf'

const byKey = (groups) => Object.fromEntries(groups.map((g) => [g.key, g]))

describe('entityGroups, demo 11', () => {
  const { groups, links } = entityGroups(demo)
  const g = byKey(groups)

  it('folds the 30 wallets into 8 groups, in the plan order', () => {
    expect(groups.map((x) => [x.key, x.addresses.length])).toEqual([
      ['reported', 1], ['exchange', 1], ['frozen', 1], ['route', 1],
      ['split', 1], ['recipients', 7], ['passed', 6], ['end', 12],
    ])
    expect(groups.reduce((n, x) => n + x.addresses.length, 0)).toBe(30)
  })

  it('puts every wallet in exactly one group', () => {
    const all = groups.flatMap((x) => x.addresses)
    expect(new Set(all).size).toBe(30)
    expect(new Set(all)).toEqual(new Set(demo.graph.nodes.map((n) => n.address)))
  })

  it('gives each wallet the first group it fits', () => {
    // The reported wallet is frozen too; TZ7L… is frozen and a split recipient.
    expect(g.reported.addresses).toEqual([SEED])
    expect(g.frozen.addresses).toEqual([FROZEN])
    expect(g.recipients.addresses).not.toContain(FROZEN)
    expect(g.exchange.addresses).toEqual([BINANCE])
    expect(g.route.addresses).toEqual([ROUTE])
    expect(g.split.addresses).toEqual([SPLIT])
  })

  it('names the groups from the case: the exchange, its label and the issuer', () => {
    expect(groups.map((x) => x.name)).toEqual([
      'Reported wallet', 'Binance-Hot 7', 'Frozen by Tether', 'Route to Binance',
      'Split wallet', 'Split recipients', 'Passed on, no label', 'End of trace, no label',
    ])
  })

  it('colours the exchange green, the frozen wallets red and the rest grey', () => {
    expect(groups.map((x) => x.kind)).toEqual(['plain', 'go', 'risk', 'plain', 'plain', 'plain', 'plain', 'plain'])
    expect(groups.some((x) => x.inferred)).toBe(false)
  })

  it('sums the gross amount between groups, and draws none inside one', () => {
    const gross = Object.fromEntries(links.map((l) => [`${l.from}>${l.to}`, Number(l.gross.toFixed(2))]))
    expect(gross).toEqual({
      'reported>split': 6000,
      'reported>passed': 2791,
      'reported>route': 635,
      'reported>frozen': 465,
      'split>recipients': 5697.7,
      'split>frozen': 300,
      'route>exchange': 45968.32,
      'frozen>route': 2005,
      'frozen>recipients': 185,
      'frozen>end': 1320,
      'passed>end': 3549.43,
    })
    expect(links.every((l) => l.style === 'solid')).toBe(true)
  })

  it('reads each group\'s column from the hop its wallets are nearest', () => {
    expect(groups.map((x) => [x.key, x.depth])).toEqual([
      ['reported', 0], ['exchange', 2], ['frozen', 1], ['route', 1],
      ['split', 1], ['recipients', 2], ['passed', 1], ['end', 2],
    ])
  })
})

describe('groupLayout', () => {
  const { groups } = entityGroups(demo)

  it('places the reported wallet left, each hop to its right, the route to the exchange on top', () => {
    const at = groupLayout(groups)
    expect(at.reported.x).toBeLessThan(at.route.x)
    expect(at.route.x).toBeLessThan(at.exchange.x)
    const column1 = ['route', 'frozen', 'split', 'passed']
    expect([...column1].sort((a, b) => at[a].y - at[b].y)).toEqual(column1)
    expect(at.exchange.y).toBeLessThan(at.recipients.y)
    expect(at.recipients.y).toBeLessThan(at.end.y)
    for (const p of Object.values(at)) {
      expect(p.x).toBeGreaterThan(0); expect(p.x).toBeLessThan(1)
      expect(p.y).toBeGreaterThan(0); expect(p.y).toBeLessThan(1)
    }
  })

  it('runs right to left on a reverse trace, so money still flows left to right', () => {
    const at = groupLayout(groups, { reverse: true })
    expect(at.reported.x).toBeGreaterThan(at.route.x)
    expect(at.route.x).toBeGreaterThan(at.exchange.x)
  })
})

describe('entityGroups, other shapes', () => {
  const node = (address, depth, extra = {}) => ({ id: address, address, depth, label: null, exchange: null, risk_category: null, inferred_exchange: null, ...extra })
  const edge = (source, target, value_native) => ({ source, target, value_native })

  it('puts a probable deposit address in a dashed group of its own, after the exchanges', () => {
    const result = {
      address: 'A', attribution_inferred: true, exchange: 'Binance',
      graph: {
        nodes: [node('A', 0, { is_seed: true }), node('B', 1), node('D', 2, { inferred_exchange: 'Binance' })],
        edges: [edge('A', 'B', 10), edge('B', 'D', 9)],
      },
      trace_path: [{ address: 'A' }, { address: 'B' }, { address: 'D' }],
    }
    const { groups, links } = entityGroups(result)
    const g = byKey(groups)
    expect(groups.map((x) => x.key)).toEqual(['reported', 'deposit', 'route'])
    expect(g.deposit).toMatchObject({ name: 'Probable Binance deposit', kind: 'go', inferred: true, addresses: ['D'] })
    // The route to an inferred deposit is inferred too.
    expect(g.route.inferred).toBe(true)
    expect(links.map((l) => [l.from, l.to, l.style])).toEqual([['reported', 'route', 'dashed'], ['route', 'deposit', 'dashed']])
  })

  it('keeps a wallet named by any other list in a group of its own, so the total still holds', () => {
    const result = {
      address: 'A',
      graph: {
        nodes: [node('A', 0, { is_seed: true }), node('M', 1, { risk_category: 'mixer', label: 'Tornado' }), node('R', 1, { label: 'SunSwap router' })],
        edges: [edge('A', 'M', 5), edge('A', 'R', 4)],
      },
    }
    const { groups } = entityGroups(result)
    expect(groups.map((x) => [x.key, x.addresses])).toEqual([['reported', ['A']], ['other', ['M', 'R']]])
    expect(byKey(groups).other.name).toBe('Named on other lists')
  })

  it('reads outside names as plain text', () => {
    const result = {
      address: 'A', exchange: 'Bin\u200bance',
      graph: { nodes: [node('A', 0, { is_seed: true }), node('X', 1, { exchange: 'Bin\u200bance', label: 'Bin\u202eance-Hot 7' })], edges: [edge('A', 'X', 1)] },
      risk_matches: [{ address: 'A', category: 'frozen', issuer: 'Teth\u200ber' }],
      trace_path: [{ address: 'A' }, { address: 'X' }],
    }
    const names = entityGroups(result).groups.map((x) => x.name)
    expect(names).toEqual(['Reported wallet', 'Binance-Hot 7'])
  })

  it('names the issuers of a freeze, or says the issuer', () => {
    const result = {
      address: 'A',
      graph: { nodes: [node('A', 0, { is_seed: true }), node('F', 1, { risk_category: 'frozen' }), node('G', 1, { risk_category: 'frozen' })], edges: [] },
      risk_matches: [{ address: 'F', category: 'frozen', issuer: 'Tether' }, { address: 'G', category: 'frozen', issuer: 'Circle' }],
    }
    expect(byKey(entityGroups(result).groups).frozen.name).toBe('Frozen by Tether and Circle')
    expect(byKey(entityGroups({ ...result, risk_matches: [] }).groups).frozen.name).toBe('Frozen by the issuer')
  })

  it('reads the way a reverse trace walks: a wallet with funders of its own passed money on', () => {
    const result = {
      address: 'A', direction: 'incoming',
      graph: { nodes: [node('A', 0, { is_seed: true }), node('B', 1), node('C', 2)], edges: [edge('B', 'A', 3), edge('C', 'B', 3)] },
    }
    expect(entityGroups(result).groups.map((x) => [x.key, x.addresses])).toEqual([['reported', ['A']], ['passed', ['B']], ['end', ['C']]])
  })

  it('has nothing to group without a graph', () => {
    expect(entityGroups({}).groups).toEqual([])
    expect(entityGroups(null).links).toEqual([])
  })
})
