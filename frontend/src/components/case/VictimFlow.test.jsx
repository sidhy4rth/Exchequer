import { readFileSync } from 'node:fs'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import VictimFlow from './VictimFlow'
import flow from '../../test/victim-flow-11.json'
import instantFlow from '../../test/victim-flow-11-instant.json'
import recordings from '../../../../backend/data/recorded_demos.json'

// The Flow tab: where the victim's share went (backend victim_flow), drawn
// as a Sankey with a card for each place the money ended and what to do
// about it. Demo 11 with its flow (src/test/victim-flow-11.json).
const demo = recordings.find((r) => r.demo === 11).result
const TZ7L = 'TZ7LmC6zBipRx6tDMavbzaF8piBpw89cNz'
const TT4Y = 'TT4yg2GguWvN5j8Xeb7nUB5Hg2wWd1dFp3'

function draw(overrides = {}) {
  const on = { onLetters: vi.fn(), onWatch: vi.fn(), onDeeper: vi.fn() }
  const result = { ...demo, victim_flow: flow, ...overrides }
  const view = render(<VictimFlow result={result} unit="USDT" {...on} />)
  return { ...on, ...view }
}
const card = (name) => screen.getByRole('heading', { level: 3, name }).closest('article')

describe('the victim-flow Sankey', () => {
  it('draws the case as a picture with a summary in words', () => {
    draw()
    expect(screen.getByRole('heading', { level: 2, name: "Where the victim's share went" })).toBeInTheDocument()
    const img = screen.getByRole('img', { name: /^Of 9,891 USDT the reported wallet sent on: / })
    expect(img).toHaveAccessibleName(expect.stringContaining('959.58 USDT reached an exchange'))
    expect(img).toHaveAccessibleName(expect.stringContaining('8,732.34 USDT is beyond the trace\'s 2 hops'))
  })

  it('labels the wallets with mono address chips and their amounts, the frozen one marked', () => {
    const { container } = draw()
    const chips = [...container.querySelectorAll('.vf-chip.mono')].map((c) => c.textContent)
    expect(chips).toEqual(['TUVN…i3ts · 9,891 · frozen', 'TXgo…BBVU · 635', 'TZ7L…9cNz · 465 · frozen', 'TT4y…dFp3 · 6,000 · 300 via frozen TZ7L', 'TBCv…ZuA4 · 1,000', '5 more wallets · 1,791'])
    expect([...container.querySelectorAll('.vf-chip.risk')].map((c) => c.textContent)).toEqual(['TUVN…i3ts · 9,891 · frozen', 'TZ7L…9cNz · 465 · frozen'])
    // Money that went on through the frozen wallet is marked red on the row it left by.
    expect([...container.querySelectorAll('.vf-chip .vf-via')].map((c) => c.textContent)).toEqual([' · 300 via frozen TZ7L'])
    expect(screen.getByText('Binance-Hot 7 · 959.58')).toBeInTheDocument()
    expect(screen.getByText('Left in TT4y…dFp3 · 2.3')).toBeInTheDocument()
  })

  it('colours and styles each ribbon by its money and its link', () => {
    const { container } = draw()
    const paths = [...container.querySelectorAll('path.vf-ribbon')]
    expect(paths.some((p) => p.matches('.vf-go.vf-faded'))).toBe(true)
    expect(paths.some((p) => p.matches('.vf-go.vf-dashed'))).toBe(true)
    expect(paths.some((p) => p.matches('.vf-grey.vf-dashed'))).toBe(true)
    expect(paths.some((p) => p.matches('.vf-go.vf-solid'))).toBe(true)
    expect(container.querySelector('rect.vf-bar.risk')).toBeInTheDocument()
  })

  it('says how much reached a place someone can act on, and what the widths are', () => {
    draw()
    // 635 of the 959.58 at Binance is pro-rata's own; the 324.58 through
    // TZ7L is an upper bound, so the share is said as one and never added in.
    expect(screen.getByText(/reached a place someone can act on/).closest('p')).toHaveTextContent(/^6\.4% reached a place someone can act on, up to 9\.7% counting money through wallets whose shares are only upper bounds$/)
    expect(screen.getByText("widths are the victim's money, not the totals that passed through")).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: '6.4% can be acted on' })).toBeInTheDocument()
    expect(screen.getByText(/^up to 9\.7%/)).toHaveTextContent('up to 9.7% counting money through wallets whose shares are only upper bounds')
    // Said by what the bound is, never by how it is drawn: a phone shows no
    // chart, and a dashed link may be an inferred deposit, not a bound.
    expect(screen.queryByText(/(acted|act) on.*dashed|^up to.*dashed/)).not.toBeInTheDocument()
    expect(screen.getByText(/that it reached Binance · not a probability/).closest('p')).toHaveTextContent(/^Low that it reached Binance · not a probability$/)
  })

  it('lays the bar out green, red, then grey, whatever the order of the ribbons', () => {
    const { container } = draw()
    expect([...container.querySelectorAll('.vf-bar-all span')].map((c) => c.className)).toEqual(['go exchange', 'grey not_followed', 'grey beyond_limit', 'grey left'])
  })

  it('says why each rule it cannot offer is off, when the case gives a reason', () => {
    draw({ tracing_methods: { fifo: { status: 'unknown', reason: 'a wallet\'s history was too long to read' }, libr: { status: 'not_applicable' }, figures: { prorata: 635 } } })
    expect(screen.getByRole('radio', { name: 'FIFO' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'LIBR' })).toBeDisabled()
    expect(screen.getByRole('group', { name: 'Tracing rule' })).toHaveAccessibleDescription("FIFO: a wallet's history was too long to read. LIBR: not worked out for this case.")
  })

  it('offers FIFO and LIBR only when the case worked them out, and says why not', async () => {
    draw()
    expect(screen.getByRole('radio', { name: 'Pro-rata' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'FIFO' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'LIBR' })).toBeDisabled()
    expect(screen.getByRole('group', { name: 'Tracing rule' })).toHaveAccessibleDescription('FIFO and LIBR were not worked out for this case.')
  })

  it('gives the FIFO figure when it is chosen, and keeps the drawing pro-rata', async () => {
    const user = userEvent.setup()
    draw({ tracing_methods: { figures: { fifo: 600, prorata: 635, libr: 0 } } })
    await user.click(screen.getByRole('radio', { name: 'FIFO' }))
    expect(screen.getByText(/^By FIFO, 600 USDT reached Binance\./)).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'LIBR' })).toBeEnabled()
    expect(screen.getByRole('group', { name: 'Tracing rule' })).not.toHaveAccessibleDescription()
  })

  it('shows the notes and where the tracing stopped', () => {
    draw()
    for (const note of flow.notes) expect(screen.getByText(note)).toBeInTheDocument()
    expect(screen.getByText('The trace stopped at 2 hops.')).toBeInTheDocument()
    expect(screen.getAllByText('Only the 10 largest destinations were followed at TZ7LmC…9cNz.').length).toBeGreaterThan(0)
  })
})

describe('the bucket cards and what each lets an officer do', () => {
  it('drafts the urgent freeze letter to the exchange: it is the one sent first', async () => {
    const user = userEvent.setup()
    const { onLetters } = draw()
    const exchange = card('At an exchange')
    expect(exchange).toHaveTextContent('up to 959.58 USDT')
    expect(exchange).toHaveTextContent('Binance · Binance-Hot 7')
    expect(exchange).toHaveTextContent('TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf')
    expect(within(exchange).getByText('Low · exact label')).toBeInTheDocument()
    expect(exchange.textContent).not.toMatch(/0\.49/)
    await user.click(within(exchange).getByRole('button', { name: 'Draft letter to Binance' }))
    expect(onLetters).toHaveBeenCalledWith('exchange-freeze')
  })

  it('asks Tether about the frozen wallet the money passed through', async () => {
    const user = userEvent.setup()
    const { onLetters } = draw({ risk_matches: demo.risk_matches.map((m) => ({ ...m, frozen_on: '2026-09-11' })) })
    const frozen = card('Through a wallet Tether froze')
    expect(frozen).toHaveTextContent('765 USDT reached it')
    expect(frozen).toHaveTextContent(new RegExp(`${TZ7L} · frozen 11 Sept? 2026`))
    await user.click(within(frozen).getByRole('button', { name: 'Ask Tether' }))
    expect(onLetters).toHaveBeenCalledWith('tether')
  })

  it('traces two hops deeper, through the confirm step', async () => {
    const user = userEvent.setup()
    const { onDeeper } = draw()
    const beyond = card("Beyond the trace's 2 hops")
    expect(beyond).toHaveTextContent('8,732.34')
    await user.click(within(beyond).getByRole('button', { name: 'Trace 2 hops deeper' }))
    expect(onDeeper).toHaveBeenCalledWith(4)
  })

  it('goes only as deep as a trace can', () => {
    draw({ max_depth: 5 })
    expect(within(card("Beyond the trace's 5 hops")).getByRole('button', { name: 'Trace 1 hop deeper' })).toBeInTheDocument()
  })

  it('watches the wallet where money is left', async () => {
    const user = userEvent.setup()
    const { onWatch } = draw()
    const left = card('Left in TT4y…dFp3')
    expect(left).toHaveTextContent('2.3 USDT')
    await user.click(within(left).getByRole('button', { name: 'Watch' }))
    expect(onWatch).toHaveBeenCalledWith(TT4Y)
  })

  it('notes what was not followed, with nothing to press', () => {
    draw()
    const unfollowed = card('Not followed')
    expect(unfollowed).toHaveTextContent('196.78')
    expect(within(unfollowed).queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows no card for an empty bucket', () => {
    draw()
    expect(screen.queryByRole('heading', { name: /^Held/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /^At a mixer/ })).not.toBeInTheDocument()
  })
})

// Shapes demo 11 does not have, each from a hand-made flow.
const S = 'S'.padEnd(34, 's')
const I = '0x' + '1'.repeat(40)
const H = '0x' + '2'.repeat(40)
const F = 'F'.padEnd(34, 'f')
const X = 'X'.padEnd(34, 'x')
function made({ nodes, links, buckets, ...rest }, result = {}) {
  const total = buckets.reduce((s, b) => s + b.amount, 0)
  const victim_flow = {
    status: 'estimated',
    nodes: nodes.map(([address, role, victim_in, left = 0]) => ({ address, role, victim_in, left, basis: role === 'seed' ? 'seed_outflow' : role === 'wallet' ? 'traced_only' : null })),
    links: links.map(([source, target, victim, style = 'solid']) => ({ source, target, victim, gross: victim, style })),
    buckets: buckets.map((b) => ({ addresses: [], share: b.amount / total, ...b })),
    totals: { denominator: total, basis: 'seed_outflow' }, lead: { path: [], reached: null }, passed_through: [], notes: [], stops: [], ...rest,
  }
  const on = { onLetters: vi.fn(), onWatch: vi.fn(), onDeeper: vi.fn() }
  const view = render(<VictimFlow result={{ address: S, max_depth: 2, graph: { nodes: [], edges: [] }, ...result, victim_flow }} unit="ETH" {...on} />)
  return { ...on, ...view }
}

describe('an exchange bucket of more than one address', () => {
  const twoAt = (other) => made({
    nodes: [[S, 'seed', 107.18], [H, 'exchange', 95.18], [I, 'exchange', 12]],
    links: [[S, H, 95.18], [S, I, 12, 'dashed']],
    buckets: [{ kind: 'exchange', amount: 107.18, addresses: [H, I] }],
  }, {
    exchange: 'Binance', exchange_label: 'probable Binance deposit address (inferred)', exchange_address: I, attribution_inferred: true, confidence_detail: { band: 'moderate' },
    graph: { nodes: [{ address: S }, { address: H, exchange: other, label: `${other} 14` }, { address: I, inferred_exchange: 'Binance' }], edges: [] },
  })

  it('gives each address its own amount, never the whole bucket against one', () => {
    const { container } = twoAt('Binance')
    const exchange = card('At an exchange')
    expect(exchange).toHaveTextContent('107.18 ETH')
    const rows = within(exchange).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    for (const [row, name, address, amount] of [[rows[0], 'Binance · Binance 14', H, '95.18 ETH'], [rows[1], 'Binance · probable Binance deposit address (inferred)', I, '12 ETH']]) {
      expect(within(row).getByText(name)).toBeInTheDocument()
      expect(within(row).getByText(address)).toBeInTheDocument()
      expect(within(row).getByText(amount)).toBeInTheDocument()
    }
    expect(within(exchange).getByRole('button', { name: 'Draft letter to Binance' })).toBeInTheDocument()
    expect([...container.querySelectorAll('.vf-at-end')].map((c) => c.textContent)).toEqual(['At Binance · 107.18'])
  })

  it('says "At exchanges" on the chart when the addresses belong to different exchanges', () => {
    const { container } = twoAt('Coinbase')
    expect([...container.querySelectorAll('.vf-at-end')].map((c) => c.textContent)).toEqual(['At exchanges · 107.18'])
    expect(within(within(card('At an exchange')).getAllByRole('listitem')[0]).getByText('Coinbase · Coinbase 14')).toBeInTheDocument()
  })
})

describe('a frozen wallet that still holds the money', () => {
  it('has one card and one Ask Tether, not one for passing through and one for holding', () => {
    made({
      nodes: [[S, 'seed', 10], [F, 'wallet', 4, 4], [H, 'exchange', 6]],
      links: [[S, H, 6], [S, F, 4]],
      buckets: [{ kind: 'exchange', amount: 6, addresses: [H] }, { kind: 'held', amount: 4, addresses: [F] }],
      passed_through: [{ address: F, category: 'frozen', victim_in: 4 }],
    }, {
      graph: { nodes: [{ address: S }, { address: H, exchange: 'Binance' }, { address: F, risk_category: 'frozen' }], edges: [] },
      risk_matches: [{ address: F, category: 'frozen', issuer: 'Tether' }],
    })
    expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['At an exchange', 'Held at a wallet Tether froze'])
    expect(screen.getAllByRole('button', { name: 'Ask Tether' })).toHaveLength(1)
  })

  it('says how much reached it when some went on', () => {
    made({
      nodes: [[S, 'seed', 10], [F, 'wallet', 10, 4], [X, 'beyond_limit', 6]],
      links: [[S, F, 10], [F, X, 6]],
      buckets: [{ kind: 'held', amount: 4, addresses: [F] }, { kind: 'beyond_limit', amount: 6, addresses: [X] }],
      passed_through: [{ address: F, category: 'frozen', victim_in: 10 }],
    }, { graph: { nodes: [{ address: F, risk_category: 'frozen' }], edges: [] }, risk_matches: [{ address: F, category: 'frozen', issuer: 'Tether' }] })
    expect(card('Held at a wallet Tether froze')).toHaveTextContent('4 ETH of the 10 ETH that reached it')
  })
})

describe('a sanctioned wallet the money passed through', () => {
  it('says a sanctions listing freezes nothing, and leaves it out of what can be acted on', () => {
    made({
      nodes: [[S, 'seed', 10], [F, 'wallet', 4, 4], [H, 'exchange', 6]],
      links: [[S, H, 6], [S, F, 4]],
      buckets: [{ kind: 'exchange', amount: 6, addresses: [H] }, { kind: 'left', amount: 4, addresses: [F] }],
      passed_through: [{ address: F, category: 'sanctioned', victim_in: 4 }],
    }, { graph: { nodes: [{ address: S }, { address: H, exchange: 'Binance' }, { address: F, risk_category: 'sanctioned' }], edges: [] } })
    expect(card('Through a sanctioned wallet')).toHaveTextContent("A sanctions listing freezes nothing: the money can still move unless a token's issuer has frozen it.")
    expect(screen.queryByRole('heading', { name: /^Held/ })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: '60% can be acted on' })).toBeInTheDocument()
    expect(screen.queryByText(/^up to/)).not.toBeInTheDocument()
  })
})

describe('an exchange bucket that came only through upper-bound shares', () => {
  it('says nothing firm reached it, worked from the amounts and not the rounded share', () => {
    // 2 of 300 is a share of 0.006667 once rounded: taking the exact 2/300
    // from that left 3e-7, said as "under 0.1%" when nothing firm reached it.
    made({
      nodes: [[S, 'seed', 300], [F, 'wallet', 2], [H, 'exchange', 2], [X, 'beyond_limit', 298]],
      links: [[S, F, 2], [F, H, 2, 'dashed'], [S, X, 298]],
      buckets: [{ kind: 'exchange', amount: 2, share: 0.006667, bounded_amount: 2, addresses: [H] }, { kind: 'beyond_limit', amount: 298, addresses: [X] }],
    }, { graph: { nodes: [{ address: S }, { address: H, exchange: 'Binance' }], edges: [] } })
    expect(screen.getByRole('heading', { level: 2, name: '0% can be acted on' })).toBeInTheDocument()
    expect(screen.getByText(/reached a place someone can act on/).closest('p')).toHaveTextContent(/^0% reached a place someone can act on, up to 0\.6% counting money through wallets whose shares are only upper bounds$/)
  })
})

describe('money beyond the hop limit and money the trace did not open', () => {
  const split = (stops) => made({
    nodes: [[S, 'seed', 10], [X, 'beyond_limit', 10]],
    links: [[S, X, 10]],
    buckets: [{ kind: 'beyond_limit', amount: 10, addresses: [X] }],
    stops,
  })

  it('counts only the hop limit\'s wallets as beyond the hops, and offers a deeper trace for those', async () => {
    const user = userEvent.setup()
    const { onDeeper } = split([{ kind: 'hop_limit', amount: 4, addresses: [X], note: 'The trace stopped at 2 hops.' }])
    expect(screen.getByText(/is beyond the trace's 2 hops/).closest('p')).toHaveTextContent(/^40% is beyond the trace's 2 hops$/)
    const beyond = card("Beyond the trace's 2 hops")
    expect(beyond).toHaveTextContent('4 ETH')
    await user.click(within(beyond).getByRole('button', { name: 'Trace 2 hops deeper' }))
    expect(onDeeper).toHaveBeenCalledWith(4)
    const unopened = card('Not opened')
    expect(unopened).toHaveTextContent('6 ETH')
    expect(within(unopened).queryByRole('button')).not.toBeInTheDocument()
  })

  it('offers no deeper trace when the hop limit stopped none of it', () => {
    split([])
    expect(card('Not opened')).toHaveTextContent('10 ETH')
    expect(screen.queryByRole('button', { name: /hops? deeper/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/is beyond the trace's/)).not.toBeInTheDocument()
  })
})

// A stub: demo 11 as the backend builds it when its exchange wallet is an
// instant exchanger (src/test/victim-flow-11-instant.json). No recorded demo
// reaches one, so the figures are demo 11's own.
describe('money at an instant exchanger', () => {
  const instant = (over = {}) => draw({ victim_flow: instantFlow, ...over })

  it('has a card of its own, outlined green, that drafts the urgent letter to the swap service', async () => {
    const user = userEvent.setup()
    const { onLetters } = instant()
    const at = card('At an instant exchanger')
    expect(at).toHaveClass('vf-card', 'vf-instant')
    expect(at).not.toHaveClass('inferred')
    expect(at).toHaveTextContent('959.58')
    expect(at).toHaveTextContent('TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf')
    expect(at).toHaveTextContent(/which order this paid for and where the payout went/)
    expect(within(at).getByText('Low · exact label')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 3, name: 'At an exchange' })).toBeNull()
    await user.click(within(at).getByRole('button', { name: 'Draft letter to Binance' }))
    expect(onLetters).toHaveBeenCalledWith('instant-freeze')
  })

  it('counts as a place someone can act on, green in the drawing and the bar', () => {
    const { container } = instant()
    // Demo 11's figures: part came through wallets whose shares are only upper bounds.
    expect(screen.getByRole('heading', { level: 2, name: '6.4% can be acted on' })).toBeInTheDocument()
    expect(screen.getByText(/^up to 9\.7%/)).toHaveTextContent('up to 9.7% counting money through wallets whose shares are only upper bounds')
    expect(screen.getByRole('img')).toHaveAccessibleName(expect.stringContaining('959.58 USDT reached an instant exchanger'))
    expect([...container.querySelectorAll('.vf-bar-all span')].map((c) => c.className)).toEqual(['go instant_exchanger', 'grey not_followed', 'grey beyond_limit', 'grey left'])
    expect(screen.getByText('At an instant exchanger · 959.58')).toHaveClass('go')
    expect(card('At an instant exchanger')).toHaveTextContent('up to 959.58 USDT')
  })

  it('is dashed, and says so, when the wallet is an inferred order deposit address', () => {
    const nodes = demo.graph.nodes.map((n) => (n.address === demo.exchange_address ? { ...n, exchange: null, inferred_exchange: 'ChangeNOW' } : n))
    instant({ graph: { ...demo.graph, nodes }, exchange: 'ChangeNOW', attribution_inferred: true })
    const at = card('At an instant exchanger')
    expect(at).toHaveClass('inferred')
    expect(at).toHaveTextContent('ChangeNOW · inferred')
  })
})

// Two swap services reached: the button names the one its letter goes to
// (backend request_letters._instant), never simply the larger.
describe('the instant exchanger card with two services', () => {
  const FF = 'TDoXUNZ6PajKuiUkcYg3EDSV9bnqGqsbcf'
  const two = (over = {}) => {
    const buckets = instantFlow.buckets.map((b) => (b.kind === 'instant_exchanger' ? { ...b, addresses: [FF, demo.exchange_address] } : b))
    const nodes = [...instantFlow.nodes, { address: FF, role: 'instant_exchanger', victim_in: 3000, share: null, basis: null, left: 0 }]
    const graph = { ...demo.graph, nodes: [...demo.graph.nodes, { address: FF, exchange: 'FixedFloat' }] }
    const own = { address: demo.exchange_address, exchange: 'ChangeNOW', category: 'instant_exchanger' }
    const side = { address: FF, exchange: 'FixedFloat', category: 'instant_exchanger' }
    return draw({ victim_flow: { ...instantFlow, buckets, nodes }, graph, exchange: 'ChangeNOW', matches: [side, own], ...over })
  }

  it("names the case's own exchange when it is one, though another got more", async () => {
    const user = userEvent.setup()
    const { onLetters } = two()
    await user.click(within(card('At an instant exchanger')).getByRole('button', { name: 'Draft letter to ChangeNOW' }))
    expect(onLetters).toHaveBeenCalledWith('instant-freeze')
  })

  it('names the first the trace reached when the case’s exchange is none of them', () => {
    const graph = { ...demo.graph, nodes: [...demo.graph.nodes, { address: FF, exchange: 'FixedFloat' }, { address: 'TSmall', exchange: 'SideShift' }] }
    const first = { address: 'TSmall', exchange: 'Side​Shift', category: 'instant_exchanger' }
    two({ exchange: 'Binance', graph, matches: [{ address: demo.exchange_address, exchange: 'Binance' }, first, { address: FF, exchange: 'FixedFloat', category: 'instant_exchanger' }] })
    expect(within(card('At an instant exchanger')).getByRole('button', { name: 'Draft letter to SideShift' })).toBeInTheDocument()
  })
})

// The figure in motion: it opens with its columns growing, its ribbons drawn
// in two stages, a few slow lights, and its figures counting up; with reduced
// motion it is drawn final at once. Every figure is the real one in the page
// from the first render: the count is drawn over it, aria-hidden.
describe('the Flow figure in motion', () => {
  const still = () => vi.stubGlobal('matchMedia', (query) => ({ matches: /reduce/.test(query), addEventListener: () => {}, removeEventListener: () => {} }))
  const frames = () => {
    const queue = []
    vi.stubGlobal('requestAnimationFrame', (cb) => queue.push(cb))
    vi.stubGlobal('cancelAnimationFrame', () => {})
    return (ms) => { const now = performance.now() + ms; for (const cb of queue.splice(0)) cb(now) }
  }

  it('shows every final figure at once, while the count is drawn over it', () => {
    const { container } = draw()
    const exchange = card('At an exchange')
    expect(exchange).toHaveTextContent('up to 959.58 USDT')
    expect(exchange.querySelector('.vf-count')).toHaveAttribute('data-counting')
    expect(screen.getByRole('heading', { level: 2, name: '6.4% can be acted on' })).toBeInTheDocument()
    expect(screen.getByText(/reached a place someone can act on/).closest('p')).toHaveTextContent(/^6\.4% reached a place someone can act on, up to 9\.7%/)
    // The running number is a mark with no text of its own, hidden from screen readers.
    for (const run of container.querySelectorAll('.vf-run')) {
      expect(run).toHaveAttribute('aria-hidden', 'true')
      expect(run.textContent).toBe('')
    }
  })

  it('counts each figure up once, then leaves the figure alone', () => {
    const tick = frames()
    draw()
    const box = card('At an exchange').querySelector('.vf-count')
    expect(box.lastChild.dataset.n).toBe('0.00')
    tick(450 + 550) // the card's delay, then half its count
    const mid = Number(box.lastChild.dataset.n)
    expect(mid).toBeGreaterThan(0)
    expect(mid).toBeLessThan(959.58)
    tick(60_000)
    expect(document.querySelector('[data-counting]')).toBeNull()
    expect(box.lastChild.dataset.n).toBeUndefined()
    expect(box).toHaveTextContent('959.58')
  })

  it('draws the ribbons in two stages, left then right, every one of them', () => {
    const { container } = draw()
    const first = [...container.querySelectorAll('g.vf-stage1 path.vf-ribbon')]
    const second = [...container.querySelectorAll('g.vf-stage2 path.vf-ribbon')]
    expect(first.length).toBeGreaterThan(0)
    expect(first).toHaveLength(second.length)
    expect(first.length + second.length).toBe(container.querySelectorAll('path.vf-ribbon').length)
    for (const p of first) expect(p.getAttribute('d')).toMatch(/^M12 /)
    for (const p of second) expect(p.getAttribute('d')).not.toMatch(/^M12 /)
    // The columns grow 60 ms apart, from the reported wallet to where it ended.
    const delays = [...container.querySelectorAll('rect.vf-bar')].map((r) => parseInt(r.style.getPropertyValue('--vf-d'), 10))
    expect(delays[0]).toBe(100)
    expect(delays).toEqual([...delays].sort((a, b) => a - b))
  })

  it('sends a few slow lights along the ribbons, green only towards the exchange', () => {
    const { container } = draw()
    const lights = [...container.querySelectorAll('.vf-lights .vf-light')]
    expect(lights.length).toBeGreaterThan(0)
    expect(lights.length).toBeLessThanOrEqual(5)
    expect(container.querySelector('.vf-lights')).toHaveAttribute('aria-hidden', 'true')
    expect(lights.filter((l) => l.matches('.go'))).toHaveLength(3)
    expect(lights.filter((l) => !l.matches('.go')).every((l) => l.matches('.grey'))).toBe(true)
  })

  it('has a Pause motion switch that stops the loops and says when it is on', async () => {
    const user = userEvent.setup()
    const { container } = draw()
    const [pause] = screen.getAllByRole('button', { name: 'Pause motion' })
    expect(pause).toHaveAttribute('aria-pressed', 'false')
    await user.click(pause)
    for (const b of screen.getAllByRole('button', { name: 'Pause motion' })) expect(b).toHaveAttribute('aria-pressed', 'true')
    expect(container.querySelector('.vflow')).toHaveClass('vf-paused')
    await user.click(pause)
    expect(container.querySelector('.vflow')).not.toHaveClass('vf-paused')
  })

  it('slides the chosen rule\'s pill to the rule picked', async () => {
    const user = userEvent.setup()
    const { container } = draw({ tracing_methods: { figures: { fifo: 600, prorata: 635, libr: 0 } } })
    const pill = container.querySelector('.vf-rule-pill')
    expect(pill).toHaveAttribute('aria-hidden', 'true')
    expect(pill.style.getPropertyValue('--vf-at')).toBe('0')
    await user.click(screen.getByRole('radio', { name: 'LIBR' }))
    expect(pill.style.getPropertyValue('--vf-at')).toBe('2')
  })

  it('with reduced motion, draws the final picture at once: no count, no lights, nothing to pause', () => {
    still()
    const { container } = draw()
    expect(container.querySelector('.vflow')).not.toHaveClass('vf-motion')
    expect(container.querySelector('[data-counting]')).toBeNull()
    expect(container.querySelector('.vf-lights')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Pause motion' })).not.toBeInTheDocument()
    expect(card('At an exchange')).toHaveTextContent('up to 959.58 USDT')
    expect(screen.getByRole('heading', { level: 2, name: '6.4% can be acted on' })).toBeInTheDocument()
    expect(container.querySelectorAll('path.vf-ribbon').length).toBeGreaterThan(0)
  })

  it('glows only where money reached an exchange', () => {
    made({ nodes: [[S, 'seed', 10], [X, 'beyond_limit', 10]], links: [[S, X, 10]], buckets: [{ kind: 'beyond_limit', amount: 10, addresses: [X] }] })
    expect(document.querySelector('.vf-hero')).not.toHaveClass('vf-glow')
    cleanup()
    const { container } = draw()
    expect(container.querySelector('.vf-hero')).toHaveClass('vf-glow')
  })
})

// The motion lives in the stylesheet: every animation only under .vf-motion
// (which reduced motion never sets), the loops slow, and reduced motion
// stopping all of it again as a backstop.
describe('the Flow figure\'s stylesheet', () => {
  const css = readFileSync(`${process.cwd()}/src/components/case/VictimFlow.css`, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
  const rules = [...css.replace(/@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*[^}]*\}/g, '').replace(/@media \(prefers-reduced-motion: reduce\)\s*\{(?:[^{}]*\{[^}]*\})*[^}]*\}/g, '')
    .matchAll(/([^{}]+)\{([^}]*)\}/g)].map(([, sel, body]) => [sel.trim(), body])

  it('animates only under .vf-motion', () => {
    const moving = rules.filter(([, body]) => /(^|;|\s)(animation|transition)\s*:/.test(body))
    expect(moving.length).toBeGreaterThan(5)
    for (const [sel] of moving) for (const s of sel.split(',')) expect(s.trim()).toMatch(/^\.vf-motion\b/)
  })

  it('loops nothing faster than 3 seconds', () => {
    const loops = rules.flatMap(([, body]) => [...body.matchAll(/animation:\s*([^;]+)/g)].map((m) => m[1])).filter((a) => /infinite/.test(a))
    expect(loops.length).toBeGreaterThan(0)
    for (const a of loops) expect(parseFloat(/([\d.]+)s\b/.exec(a)[1])).toBeGreaterThanOrEqual(3)
  })

  it('stops every animation under reduced motion', () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.vflow \*, \.vflow \*::after \{ animation: none !important; transition: none !important; \}/)
  })

  it('keeps the chosen rule neutral: green is for exchanges and the route', () => {
    // The focus ring is the site's own (styles.css :focus-visible), green everywhere.
    const on = rules.filter(([sel]) => /\.vf-rule/.test(sel)).flatMap(([, body]) => body.split(';')).filter((d) => !/^\s*outline/.test(d))
    expect(on.length).toBeGreaterThan(5)
    expect(on.join(';')).not.toMatch(/--go/)
  })
})
