import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import TimelineLanes, { buildLanes } from './TimelineLanes'
import recordings from '../../../../backend/data/recorded_demos.json'

// The Timeline tab's lane chart (pack 2-glass-05): one lane per wallet that
// matters, every transfer at its IST time. Demo 11: Tron USDT, 72 transfers
// from 16 Dec 2024 to 30 Dec 2025; hop 1 (TXgo…BBVU) got 340 at 19 Dec
// 2024 09:06:33 UTC (14:36 IST) and passed it to Binance-Hot 7.
const demo = recordings.find((r) => r.demo === 11).result
const SEED = demo.address
const HOP1 = demo.trace_path[1].address
const FROZEN = 'TZ7LmC6zBipRx6tDMavbzaF8piBpw89cNz'
const SPLIT = 'TT4yg2GguWvN5j8Xeb7nUB5Hg2wWd1dFp3'
const FIRST = demo.transfers.filter((t) => t.from === SEED && t.to === HOP1).sort((a, b) => a.timestamp - b.timestamp)[0]

const draw = (result = demo) => render(<TimelineLanes result={result} unit="USDT" />)
const chart = () => screen.getByRole('listbox', { name: 'Every transfer, in IST' })
const lanes = () => within(chart()).getAllByRole('group')
const lane = (name) => within(chart()).getByRole('group', { name: new RegExp(`^${name}`) })
const strip = () => screen.getByRole('region', { name: 'Selected transfer' })

describe('the lanes', () => {
  it('draws the reported wallet, the route, the exchange, the frozen and split wallets, then the rest', () => {
    draw()
    const names = lanes().map((g) => g.getAttribute('aria-label'))
    expect(names.slice(0, 5)).toEqual([
      `Reported wallet, ${SEED}`, `Hop 1 · to Binance, ${HOP1}`, `Binance-Hot 7, ${demo.exchange_address}`, `Frozen wallet, ${FROZEN}`, `Split wallet, ${SPLIT}`,
    ])
    expect(names[5]).toMatch(/^\d+ more wallets, the rest of the trace$/)
    expect(names).toHaveLength(6)
  })

  it('marks money in as a ring, money out as filled, the route green and a frozen wallet red', () => {
    const { dots } = buildLanes(demo)
    const of = (laneKey, t, kind) => dots.find((d) => d.lane === laneKey && d.hash === t.hash && d.kind === kind)
    expect(of(SEED, FIRST, 'out')).toMatchObject({ tone: 'go' })
    expect(of(HOP1, FIRST, 'in')).toMatchObject({ tone: 'go' })
    const toFrozen = demo.transfers.find((t) => t.from === SEED && t.to === FROZEN)
    expect(of(SEED, toFrozen, 'out')).toMatchObject({ tone: 'risk' })
    const toSplit = demo.transfers.find((t) => t.from === SEED && t.to === SPLIT)
    expect(of(SEED, toSplit, 'out')).toMatchObject({ tone: '' })
    // The 9,890 the wallet was paid, from its statement: a ring on its lane.
    expect(dots.find((d) => d.lane === SEED && d.kind === 'in' && d.amount === 9890)).toBeTruthy()
  })

  it('sizes a dot by the square root of its amount', () => {
    const { dots } = buildLanes(demo)
    const size = (amount) => dots.find((d) => d.amount === amount).size
    expect((size(6000) - 6) / (size(340) - 6)).toBeCloseTo(Math.sqrt(6000 / 340), 6)
    expect(size(6000)).toBeGreaterThan(size(340))
  })

  it('cleans a label from outside before it names a lane', () => {
    const graph = { ...demo.graph, nodes: demo.graph.nodes.map((n) => (n.id === demo.exchange_address ? { ...n, label: 'Binance​-Hot 7' } : n)) }
    draw({ ...demo, graph })
    expect(lane('Binance-Hot 7, ')).toBeInTheDocument()
  })

  it('draws nothing for a case with no transfers listed', () => {
    const { container } = draw({ ...demo, transfers: undefined })
    expect(container).toBeEmptyDOMElement()
  })
})

describe('the day axis', () => {
  it('opens on the first 14 days in IST, and shows all of them on request', async () => {
    const user = userEvent.setup()
    draw()
    const ticks = [...document.querySelectorAll('.tl-axis span')].map((s) => s.textContent)
    expect(ticks[0]).toBe('16 Dec')
    expect(ticks).toHaveLength(14)
    const first = within(chart()).getAllByRole('option').length
    const all = screen.getByRole('button', { name: /^All \d+ days$/ })
    expect(screen.getByRole('button', { name: 'First 14 days' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(all)
    expect(all).toHaveAttribute('aria-pressed', 'true')
    expect(within(chart()).getAllByRole('option').length).toBeGreaterThan(first)
  })

  it('says how many transfers it lists when the case trimmed them', () => {
    draw({ ...demo, transfers_total: 100, transfers_omitted: 28 })
    expect(screen.getByText('72 of 100 listed')).toBeInTheDocument()
  })

  it('says nothing of trimming when every transfer is listed', () => {
    draw()
    expect(screen.queryByText(/ listed$/)).not.toBeInTheDocument()
  })
})

describe('the selected transfer', () => {
  it('starts on the first transfer on the route, with IST and UTC time, both ends, amount, full hash and explorer link', () => {
    draw()
    expect(chart()).toHaveAttribute('aria-activedescendant', within(lane('Reported wallet')).getByRole('option', { selected: true }).id)
    const s = strip()
    expect(s).toHaveTextContent('19 Dec 2024, 14:36 IST')
    expect(s).toHaveTextContent('09:06 UTC')
    expect(s).toHaveTextContent('TUVN…i3ts → TXgo…BBVU')
    expect(s).toHaveTextContent('340 USDT')
    expect(s).toHaveTextContent(FIRST.hash)
    expect(within(s).getByRole('link', { name: /tronscan/i })).toHaveAttribute('href', `${demo.explorer_url}/#/transaction/${FIRST.hash}`)
  })

  it('names every dot for a screen reader', () => {
    draw()
    const picked = within(lane('Reported wallet')).getByRole('option', { selected: true })
    expect(picked).toHaveAccessibleName('19 Dec 2024, 14:36 IST: 340 USDT out to TXgo…BBVU, on the path to the exchange')
  })

  it('moves along a lane with the arrow keys, and between lanes up and down', async () => {
    const user = userEvent.setup()
    draw()
    chart().focus()
    await user.keyboard('{ArrowRight}')
    expect(strip()).toHaveTextContent('19 Dec 2024, 20:33 IST') // the next out of the reported wallet, 15:03 UTC
    await user.keyboard('{ArrowLeft}{ArrowDown}')
    const picked = within(lane('Hop 1')).getByRole('option', { selected: true })
    expect(chart()).toHaveAttribute('aria-activedescendant', picked.id)
    expect(picked).toHaveAccessibleName(/^19 Dec 2024, 14:36 IST: 340 USDT in from TUVN…i3ts/)
    await user.keyboard('{Home}')
    expect(strip()).toHaveTextContent('19 Dec 2024')
    await user.keyboard('{End}')
    expect(within(lane('Hop 1')).getAllByRole('option').at(-1)).toHaveAttribute('aria-selected', 'true')
  })

  it('picks a dot that is clicked', async () => {
    const user = userEvent.setup()
    draw()
    const dot = within(lane('Split wallet')).getAllByRole('option')[0]
    await user.click(dot)
    expect(dot).toHaveAttribute('aria-selected', 'true')
    expect(strip()).toHaveTextContent('18 Dec 2024, 14:35 IST')
    expect(strip()).toHaveTextContent('6,000 USDT')
  })

  it('steps through the chosen lane with Earlier and Later, for a pointer that cannot reach a dot', async () => {
    const user = userEvent.setup()
    draw()
    const earlier = within(strip()).getByRole('button', { name: 'Earlier transfer in this lane' })
    const later = within(strip()).getByRole('button', { name: 'Later transfer in this lane' })
    const row = within(lane('Reported wallet')).getAllByRole('option')
    const at = row.findIndex((o) => o.getAttribute('aria-selected') === 'true')
    expect(strip()).toHaveTextContent(`${at + 1} of ${row.length} in this lane`)
    await user.click(later)
    expect(row[at + 1]).toHaveAttribute('aria-selected', 'true')
    expect(strip()).toHaveTextContent('19 Dec 2024, 20:33 IST')
    await user.click(earlier)
    expect(row[at]).toHaveAttribute('aria-selected', 'true')
    for (let i = at; i > 0; i -= 1) await user.click(earlier)
    expect(row[0]).toHaveAttribute('aria-selected', 'true')
    expect(earlier).toBeDisabled()
    expect(later).toBeEnabled()
  })

  it('gives a tap to the dot centred nearest it, not to a later dot whose hit area lies on top', () => {
    draw()
    const [under, over] = within(lane('Reported wallet')).getAllByRole('option')
    const box = (left) => () => ({ left, top: 0, width: 24, height: 24, right: left + 24, bottom: 24, x: left, y: 0 })
    under.getBoundingClientRect = box(100) // centre x=112
    over.getBoundingClientRect = box(110) // centre x=122, drawn on top
    fireEvent.click(over, { clientX: 108, clientY: 12 })
    expect(under).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(over, { clientX: 120, clientY: 12 })
    expect(over).toHaveAttribute('aria-selected', 'true')
  })

  it('draws a dot at its own size inside a hit area the CSS keeps at 24 px or more', () => {
    draw()
    const { dots } = buildLanes(demo)
    const dot = within(lane('Split wallet')).getAllByRole('option')[0]
    const d = dots.find((x) => x.lane === SPLIT)
    expect(dot.style.getPropertyValue('--d')).toBe(`${d.size}px`)
    expect(dot.style.width).toBe('')
  })
})
