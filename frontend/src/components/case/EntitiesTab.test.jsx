import { readFileSync } from 'node:fs'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EntitiesTab from './EntitiesTab'
import recordings from '../../../../backend/data/recorded_demos.json'
import { stubFetch } from '../../test/setup'

// The Entities view of demo 11: 30 wallets in 8 groups, by the role each
// plays in the case (not by who owns them), a card for the group chosen, and
// the other complaints that reached the same wallets.
const demo = recordings.find((r) => r.demo === 11).result

// Both maps are stood in for, so the tests read the props the tab hands
// each one: the maps themselves are tested in their own files.
const seen = vi.hoisted(() => ({ graph: [], flow: [] }))
vi.mock('../GraphView', async (actual) => ({
  PALETTES: (await actual()).PALETTES,
  default: (props) => { seen.graph.push(props); return <div data-testid="bubble-map" /> },
}))
vi.mock('../FlowView', () => ({ default: (props) => { seen.flow.push(props); return <div data-testid="hop-map" /> } }))
const lastGraph = () => seen.graph.at(-1)
const lastFlow = () => seen.flow.at(-1)
beforeEach(() => { seen.graph.length = 0; seen.flow.length = 0 })
const SPLIT = 'TT4yg2GguWvN5j8Xeb7nUB5Hg2wWd1dFp3'
const ROUTE = 'TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU'

function show({ result = demo, caseId = null, correlation = null, routes = {} } = {}) {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  const fetch = stubFetch(routes)
  render(<EntitiesTab result={{ ...result, case_id: caseId }} unit="USDT" correlation={correlation} />)
  return fetch
}
const map = () => screen.getByRole('group', { name: '30 wallets in 8 groups' })
const card = () => screen.getByRole('region', { name: /^Selected group/ })

describe('the grouped map', () => {
  it('folds the wallets into groups, one button each, named with its count', () => {
    show()
    expect(screen.getByRole('heading', { level: 2, name: '30 wallets in 8 groups' })).toBeInTheDocument()
    const names = within(map()).getAllByRole('button').map((b) => b.textContent)
    expect(names).toEqual([
      'Reported wallet · 1 wallet', 'Binance-Hot 7 · 1 wallet', 'Frozen by Tether · 1 wallet', 'Route to Binance · 1 wallet',
      'Split wallet · 1 wallet', 'Split recipients · 7 wallets', 'Passed on, no label · 6 wallets', 'End of trace, no label · 12 wallets',
    ])
  })

  it('starts on Grouped, with Every wallet beside it', () => {
    show()
    expect(screen.getByRole('button', { name: 'Grouped' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Every wallet' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('draws a line per pair of groups, as wide as the gross amount between them', () => {
    show()
    const lines = [...document.querySelectorAll('.ent-lines path')]
    expect(lines).toHaveLength(11)
    const width = (from, to) => Number(document.querySelector(`.ent-lines path[data-link="${from}>${to}"]`).getAttribute('stroke-width'))
    expect(width('route', 'exchange')).toBeGreaterThan(width('reported', 'split'))
    expect(width('reported', 'split')).toBeGreaterThan(width('frozen', 'recipients'))
    // Toward the exchange green, into the frozen wallet red, the rest grey.
    expect(document.querySelector('[data-link="route>exchange"]')).toHaveClass('go')
    expect(document.querySelector('[data-link="reported>frozen"]')).toHaveClass('risk')
    expect(document.querySelector('[data-link="passed>end"]')).toHaveClass('plain')
  })

  it('says the lines are gross, and that the victim\'s share is on Flow', () => {
    show()
    expect(screen.getByText(/line width = gross amount between groups/)).toBeInTheDocument()
    expect(screen.getByText(/the victim's share is on Flow/)).toBeInTheDocument()
    expect(screen.getByText(/dashed = inferred/)).toBeInTheDocument()
  })

  it('draws a dashed line to a probable deposit address', () => {
    const deposit = 'T' + 'Q'.repeat(33)
    const result = {
      ...demo,
      graph: {
        nodes: [...demo.graph.nodes, { id: deposit, address: deposit, depth: 3, inferred_exchange: 'Binance' }],
        edges: [...demo.graph.edges, { source: 'TToGHkqC22mjbaUS1Runwp6NiDQRjjrQ6L', target: deposit, value_native: 40 }],
      },
    }
    show({ result })
    const to = [...document.querySelectorAll('.ent-lines path')].find((p) => p.dataset.link.endsWith('>deposit'))
    expect(to).toHaveAttribute('stroke-dasharray')
  })
})

describe('the card for the group chosen', () => {
  it('opens on the split wallet: amount in, recipients, bars, and the hint pill', () => {
    show()
    expect(within(map()).getByRole('button', { name: /^Split wallet/ })).toHaveAttribute('aria-pressed', 'true')
    expect(within(card()).getByRole('heading', { level: 2, name: 'Split wallet' })).toBeInTheDocument()
    expect(within(card()).getByText('hint · a shape, not evidence')).toBeInTheDocument()
    expect(within(card()).getByRole('button', { name: new RegExp(`^${SPLIT.slice(0, 10)}`) })).toBeInTheDocument()
    expect(card().querySelector('.ent-split-in')).toHaveTextContent('6,000')
    expect(card().querySelector('.ent-split-out')).toHaveTextContent('8')
    const bars = card().querySelectorAll('.ent-bars span')
    expect(bars).toHaveLength(8)
    // The 300 that went on to a wallet Tether froze is drawn red.
    expect([...bars].filter((b) => b.classList.contains('risk')).map((b) => b.title)).toEqual(['300 USDT'])
    expect(card().querySelector('.ent-range')).toHaveTextContent('200 to 1,020.28 USDT each · the largest is 17% of the total')
  })

  it('shows how often the shape fired on real wallets, from the measured figures', () => {
    show()
    expect(within(card()).getByRole('img', { name: 'Amount split seen in 6 of 32 documented fraud wallets and 5 of 47 ordinary ones' })).toBeInTheDocument()
    expect(within(card()).getByText('6 / 32 fraud wallets')).toBeInTheDocument()
    expect(within(card()).getByText('5 / 47 ordinary wallets')).toBeInTheDocument()
  })

  it('opens the 8 recipients on request, each with what it received', async () => {
    const user = userEvent.setup()
    show()
    const open = within(card()).getByRole('button', { name: 'Open the 8 wallets' })
    expect(open).toHaveAttribute('aria-expanded', 'false')
    await user.click(open)
    expect(open).toHaveAttribute('aria-expanded', 'true')
    expect(open).toHaveTextContent('Hide the 8 wallets')
    const rows = within(card()).getAllByRole('listitem').filter((li) => li.closest('.ent-wallets'))
    expect(rows).toHaveLength(8)
    expect(rows[0]).toHaveTextContent('1,020.28 USDT in')
    expect(rows.some((r) => /Frozen by issuer/.test(r.textContent))).toBe(true)
  })

  it('opens another group from the keyboard, with the gross in and out of it', async () => {
    const user = userEvent.setup()
    show()
    within(map()).getByRole('button', { name: /^Route to Binance/ }).focus()
    await user.keyboard('{Enter}')
    expect(within(card()).getByRole('heading', { level: 2, name: 'Route to Binance' })).toBeInTheDocument()
    expect(within(card()).queryByText('hint · a shape, not evidence')).not.toBeInTheDocument()
    const flows = [...card().querySelectorAll('.ent-flows li')].map((li) => li.textContent)
    expect(flows).toEqual([
      'In from Reported wallet635 USDT gross',
      'In from Frozen by Tether2,005 USDT gross',
      'Out to Binance-Hot 745,968.32 USDT gross',
    ])
    await user.click(within(card()).getByRole('button', { name: 'Open the 1 wallet' }))
    expect(within(card()).getByRole('button', { name: new RegExp(`^${ROUTE.slice(0, 10)}`) })).toBeInTheDocument()
  })
})

const FROZEN = 'TZ7LmC6zBipRx6tDMavbzaF8piBpw89cNz'
const node = (address) => demo.graph.nodes.find((n) => n.address === address)
/** A screen as wide as `phone` says: the phone breakpoint matches or not. */
const screenIs = ({ phone }) => vi.stubGlobal('matchMedia', (query) => ({
  matches: phone && query === '(max-width: 720px)', media: query, addEventListener() {}, removeEventListener() {},
}))
async function everyWallet({ phone = false } = {}) {
  const user = userEvent.setup()
  show()
  screenIs({ phone })
  await user.click(screen.getByRole('button', { name: 'Every wallet' }))
  return user
}
const pick = (address) => act(() => lastGraph().onSelect(node(address)))

describe('every wallet', () => {
  it('shows the bubble map, with the hop map mounted but hidden', async () => {
    await everyWallet()
    expect(screen.getByRole('button', { name: 'Every wallet' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('group', { name: '30 wallets in 8 groups' })).not.toBeInTheDocument()
    expect(screen.getByRole('radiogroup', { name: 'Map view' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Bubble map' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: 'Hop map' })).toHaveAttribute('aria-checked', 'false')
    // The hop map is set aside, not collapsed (display: none would shrink
    // it to nothing and lose its zoom): faded under the bubble map, inert.
    const bubble = screen.getByTestId('bubble-map').closest('.ent-mapwrap')
    const hop = screen.getByTestId('hop-map').closest('.ent-mapwrap')
    expect(bubble).not.toHaveClass('off')
    expect(bubble).not.toHaveAttribute('inert')
    expect(hop).toHaveClass('off')
    expect(hop).toHaveAttribute('inert')
    expect(hop).not.toHaveAttribute('hidden')
    expect(lastGraph()).toMatchObject({ data: demo.graph, tracePath: demo.trace_path, unit: 'USDT', active: true, selected: null, flagsOnly: false, compact: false })
    expect(lastFlow()).toMatchObject({ data: demo.graph, tracePath: demo.trace_path, unit: 'USDT', direction: demo.direction, active: false, selected: null, flagsOnly: false, compact: false })
  })

  it('switches to the hop map and back, by click and by the arrow keys, keeping both mounted', async () => {
    const user = await everyWallet()
    await user.click(screen.getByRole('radio', { name: 'Hop map' }))
    expect(screen.getByRole('radio', { name: 'Hop map' })).toHaveAttribute('aria-checked', 'true')
    expect(lastGraph().active).toBe(false)
    expect(lastFlow().active).toBe(true)
    expect(screen.getByTestId('bubble-map').closest('.ent-mapwrap')).toHaveClass('off')
    expect(screen.getByTestId('bubble-map').closest('.ent-mapwrap')).toHaveAttribute('inert')
    expect(screen.getByTestId('hop-map').closest('.ent-mapwrap')).not.toHaveClass('off')
    expect(screen.getByTestId('hop-map').closest('.ent-mapwrap')).not.toHaveAttribute('inert')
    expect(screen.getByRole('radiogroup', { name: 'Map view' })).toHaveClass('hop')
    // Only the chosen radio takes Tab; the arrows move and choose.
    expect(screen.getByRole('radio', { name: 'Bubble map' })).toHaveAttribute('tabindex', '-1')
    await user.keyboard('{ArrowLeft}')
    expect(screen.getByRole('radio', { name: 'Bubble map' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: 'Bubble map' })).toHaveFocus()
    expect(lastGraph().active).toBe(true)
    await user.keyboard('{End}')
    expect(screen.getByRole('radio', { name: 'Hop map' })).toHaveFocus()
    expect(lastFlow().active).toBe(true)
  })

  it('counts the possible flags and the confirmed ones from the graph', async () => {
    await everyWallet()
    // 8 wallets a pattern flagged that no list names; 2 a list confirms (the
    // reported wallet and one more, both frozen by Tether).
    const note = document.querySelector('.ent-flag-note')
    expect([...note.querySelectorAll('span')].map((t) => t.textContent)).toEqual(['8 possible flags', '·', '2 confirmed'])
    expect(note.querySelector('.role-flagged circle')).toHaveAttribute('stroke-dasharray')
    expect(note.querySelector('.role-risk circle')).not.toHaveAttribute('stroke-dasharray')
  })

  it('passes Show only flags to both maps, as a switch', async () => {
    const user = await everyWallet()
    const flags = screen.getByRole('switch', { name: 'Show only flags' })
    expect(flags).toHaveAttribute('aria-checked', 'false')
    await user.click(flags)
    expect(flags).toHaveAttribute('aria-checked', 'true')
    expect(flags).toHaveClass('on')
    expect(lastGraph().flagsOnly).toBe(true)
    expect(lastFlow().flagsOnly).toBe(true)
    await user.click(flags)
    expect(lastGraph().flagsOnly).toBe(false)
  })

  it('shares one selection across both maps, from either one', async () => {
    const user = await everyWallet()
    expect(screen.getByText(/^Select a wallet on either map/)).toBeInTheDocument()
    pick(SPLIT)
    expect(lastGraph().selected).toBe(SPLIT)
    expect(lastFlow().selected).toBe(SPLIT)
    await user.click(screen.getByRole('radio', { name: 'Hop map' }))
    expect(lastFlow().selected).toBe(SPLIT)
    // The hop map may hand back the id alone.
    act(() => lastFlow().onSelect(ROUTE))
    expect(lastGraph().selected).toBe(ROUTE)
    expect(lastFlow().selected).toBe(ROUTE)
    act(() => lastFlow().onSelect(null))
    expect(lastGraph().selected).toBeNull()
    expect(screen.queryByRole('region', { name: 'Selected wallet' })).not.toBeInTheDocument()
  })

  it('cards a possible flag as unconfirmed, in red, with the pattern named', async () => {
    await everyWallet()
    pick(SPLIT)
    const card = screen.getByRole('region', { name: 'Selected wallet' })
    expect(within(card).getByText('Possible flag · Amount split')).toBeInTheDocument()
    expect(within(card).getByText('Possible flag · Amount split')).toHaveStyle({ color: 'var(--risk)' })
    expect(card.querySelector('.role-flagged circle')).toHaveAttribute('stroke-dasharray')
    expect(within(card).getByText(/a lead to check, not a finding/)).toBeInTheDocument()
    expect(within(card).getByText(SPLIT)).toBeInTheDocument()
    const rows = [...card.querySelectorAll('.ent-pick-rows div')].map((r) => r.textContent)
    expect(rows).toEqual(['Hop1', 'Received6,000 USDT', 'Sent5,997.7 USDT'])
    expect(within(card).getByText(/^Selected on both maps/)).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Show on hop map' })).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Copy address' })).toBeInTheDocument()
  })

  it('cards a confirmed risk by the list that confirms it, with no green', async () => {
    await everyWallet()
    pick(FROZEN)
    const card = screen.getByRole('region', { name: 'Selected wallet' })
    expect(within(card).getByText('Confirmed risk · Tether (USDT freeze)')).toHaveStyle({ color: 'var(--risk)' })
    expect(card.querySelector('.role-risk circle')).not.toHaveAttribute('stroke-dasharray')
    expect(within(card).getByText('USDT frozen by Tether on 2026-09-11')).toBeInTheDocument()
    expect(card.querySelector('.ent-pick-route')).toBeNull()
  })

  it('cards the reported address, an exchange, and a wallet on the traced route', async () => {
    await everyWallet()
    pick(demo.address)
    let card = screen.getByRole('region', { name: 'Selected wallet' })
    expect(within(card).getByText('Reported address')).toBeInTheDocument()
    expect(within(card).getByText('Frozen by issuer')).toBeInTheDocument()
    expect(card.querySelector('.ent-pick-rows')).toHaveTextContent('Hop0 · reported')
    pick('TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf')
    card = screen.getByRole('region', { name: 'Selected wallet' })
    expect(within(card).getByText('Labelled exchange · Binance-Hot 7')).toHaveStyle({ color: 'var(--go)' })
    pick(ROUTE)
    card = screen.getByRole('region', { name: 'Selected wallet' })
    expect(within(card).getByText('Traced address')).toBeInTheDocument()
    expect(card.querySelector('.ent-pick-route')).toHaveTextContent(/^On the traced route/)
  })

  it('shows the selected wallet on the other map, and Clear lets it go on both', async () => {
    const user = await everyWallet()
    pick(SPLIT)
    await user.click(screen.getByRole('button', { name: 'Show on hop map' }))
    expect(screen.getByRole('radio', { name: 'Hop map' })).toHaveAttribute('aria-checked', 'true')
    expect(lastFlow()).toMatchObject({ active: true, selected: SPLIT })
    expect(screen.getByRole('button', { name: 'Show on bubble map' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(screen.queryByRole('region', { name: 'Selected wallet' })).not.toBeInTheDocument()
    expect(lastGraph().selected).toBeNull()
    expect(lastFlow().selected).toBeNull()
    // Focus goes back to the map switch, not to the page.
    expect(screen.getByRole('radio', { name: 'Hop map' })).toHaveFocus()
  })

  it('lets Escape clear the card', async () => {
    const user = await everyWallet()
    pick(SPLIT)
    screen.getByRole('button', { name: 'Show on hop map' }).focus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('region', { name: 'Selected wallet' })).not.toBeInTheDocument()
  })

  it('copies the full address from the card', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    const user = await everyWallet()
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    pick(SPLIT)
    await user.click(screen.getByRole('button', { name: 'Copy address' }))
    expect(writeText).toHaveBeenCalledWith(SPLIT)
    expect(await screen.findByText('Address copied')).toBeInTheDocument()
  })
})

describe('every wallet on a phone', () => {
  it('shows the compact bubble map\'s key on the page, with the possible and confirmed flags told apart', async () => {
    await everyWallet({ phone: true })
    const key = screen.getByRole('group', { name: 'Bubble map key' })
    expect(key).toHaveTextContent('Sanctioned / mixer / frozen (confirmed)')
    expect(key).toHaveTextContent('Possible flag · pattern (not confirmed)')
    // Dashed and faded for a possible flag, solid for a confirmed hit: not colour alone.
    expect(key.querySelector('.role-flagged .dot')).toHaveAttribute('stroke-dasharray')
    expect(key.querySelector('.role-risk .dot')).not.toHaveAttribute('stroke-dasharray')
  })

  it('draws the key\'s swatches in the bubble map\'s own colours, a service and a traced address apart', async () => {
    await everyWallet({ phone: true })
    const key = screen.getByRole('group', { name: 'Bubble map key' })
    const fill = (role) => key.querySelector(`.role-${role} .dot`).getAttribute('fill')
    // The page starts dark in the tests (no data-theme set).
    expect(fill('service')).toBe('#4a4a4a')
    expect(fill('node')).toBe('#5e5e5e')
    expect(fill('service')).not.toBe(fill('node'))
    act(() => { window.dispatchEvent(new CustomEvent('themechange', { detail: 'light' })) })
    expect(fill('service')).toBe('#b3b3b3')
    expect(fill('node')).toBe('#8e8e8e')
    act(() => { window.dispatchEvent(new CustomEvent('themechange', { detail: 'dark' })) })
  })

  it('moves focus to the sheet as it opens, and keeps the page clear of it until it closes', async () => {
    const user = await everyWallet({ phone: true })
    const root = document.documentElement
    expect(root.style.scrollPaddingBottom).toBe('')
    pick(SPLIT)
    const sheet = screen.getByRole('region', { name: 'Selected wallet' })
    expect(sheet).toHaveFocus()
    expect(screen.getByText(/Its details are in the panel at the foot of the screen\./)).toBeInTheDocument()
    // Room for the sheet: focus scrolls clear of it, and the page's end can too.
    expect(root.style.scrollPaddingBottom).toMatch(/^\d+px$/)
    expect(document.querySelector('.ent-sheet-room')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(lastGraph().selected).toBeNull()
    expect(root.style.scrollPaddingBottom).toBe('')
    expect(document.querySelector('.ent-sheet-room')).not.toBeInTheDocument()
  })

  it('leaves the key to the bubble map itself on a desk', async () => {
    await everyWallet()
    expect(screen.queryByRole('group', { name: 'Bubble map key' })).not.toBeInTheDocument()
  })

  it('makes both maps compact and opens a bottom sheet for the selected wallet', async () => {
    const user = await everyWallet({ phone: true })
    expect(lastGraph().compact).toBe(true)
    expect(lastFlow().compact).toBe(true)
    // No card beside the maps, and the sheet waits, closed, until a pick.
    expect(screen.queryByText(/^Select a wallet on either map/)).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Selected wallet' })).not.toBeInTheDocument()
    pick(SPLIT)
    const sheet = screen.getByRole('region', { name: 'Selected wallet' })
    expect(sheet).toHaveClass('ent-sheet', 'open')
    expect(sheet).toHaveAttribute('aria-hidden', 'false')
    expect(within(sheet).getByText('Possible flag · Amount split')).toBeInTheDocument()
    expect(within(sheet).getByText(SPLIT)).toBeInTheDocument()
    expect(within(sheet).getByText('Hop 1')).toBeInTheDocument()
    expect(within(sheet).getByRole('button', { name: 'Copy address' })).toBeInTheDocument()
    await user.click(within(sheet).getByRole('button', { name: 'See on hop map' }))
    expect(lastFlow()).toMatchObject({ active: true, selected: SPLIT })
    await user.click(within(sheet).getByRole('button', { name: 'Close' }))
    expect(lastGraph().selected).toBeNull()
    // It slides away with its wallet still in it, hidden from assistive tech.
    const closed = document.querySelector('.ent-sheet')
    expect(closed).not.toHaveClass('open')
    expect(closed).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('radio', { name: 'Hop map' })).toHaveFocus()
  })
})

describe('motion on the maps', () => {
  // A literal path here would be rewritten by Vite into an asset URL.
  const sheet = './EntitiesTab.css'
  const css = readFileSync(new URL(sheet, import.meta.url), 'utf8')
  const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))

  it('slides the pill, the knob and the sheet with the motion system\'s easings', () => {
    expect(css).toMatch(/\.ent-seg-pill \{[^}]*transition: transform var\(--ent-tab\) var\(--ent-enter\)/)
    expect(css).toMatch(/--ent-tab: var\(--dur-tab, 240ms\)/)
    expect(css).toMatch(/\.ent-sheet\.open \{[^}]*transition: transform 360ms var\(--ent-enter\)/)
    expect(css).toMatch(/\.ent-mapwrap \{ animation: ent-fade var\(--ent-tab\)/)
    // A cross-fade: the map going out fades over the tab duration, then hides;
    // it is never display: none, so it keeps its width and zoom.
    expect(css).toMatch(/\.ent-mapwrap\.off \{[^}]*opacity: 0;[^}]*transition: opacity var\(--ent-tab\) var\(--ent-enter\), visibility 0s linear var\(--ent-tab\)/)
    expect(css).not.toMatch(/\.ent-mapwrap\[hidden\]/)
  })

  it('renders every final state at once under reduced motion', () => {
    expect(reduced).not.toBe('')
    for (const moving of ['.ent-seg-pill', '.ent-switch-knob', '.ent-sheet', '.ent-sheet.open']) {
      expect(reduced).toMatch(new RegExp(`${moving.replace(/\./g, '\\.')}[^{]*\\{ transition: none; \\}`))
    }
    expect(reduced).toMatch(/\.ent-mapwrap, \.ent-pick \{ animation: none; \}/)
    expect(reduced).toMatch(/\.ent-mapwrap, \.ent-mapwrap\.off \{ transition: none; \}/)
  })
})

describe('other complaints', () => {
  const cluster = (address, reported, hidden = 0) => ({ chain: 'tron', address, reported_addresses: reported, other_complaints: hidden, cases: [] })

  it('says no other stored complaint shares a wallet, when none does', () => {
    show({ caseId: 'c1', correlation: { clusters: [], related_cases: [] } })
    const other = screen.getByRole('region', { name: 'Other complaints' })
    expect(within(other).getByText(/^No other stored complaint shares a wallet with this case yet\./)).toBeInTheDocument()
  })

  it('claims no more than it can see, for a case the book does not hold', async () => {
    // Unstored, it can only see wallets two stored complaints already share:
    // one stored complaint reaching the same wallet makes no cluster.
    show({ routes: { '/cases/correlate': { body: { clusters: [], related_cases: [] } } } })
    const other = screen.getByRole('region', { name: 'Other complaints' })
    expect(await within(other).findByText(/^This case is not in the case book, so only wallets that two or more stored complaints already share can show here\. None of this case's wallets is one yet\./)).toBeInTheDocument()
    expect(within(other).queryByText(/^No other stored complaint shares/)).not.toBeInTheDocument()
  })

  it('leaves out a wallet shared on another chain, even at the same address', async () => {
    const elsewhere = { ...cluster(ROUTE, ['TOther1', 'TOther2']), chain: 'bsc' }
    show({ routes: { '/cases/correlate': { body: { clusters: [elsewhere], related_cases: [] } } } })
    const other = screen.getByRole('region', { name: 'Other complaints' })
    expect(await within(other).findByText(/^This case is not in the case book/)).toBeInTheDocument()
    expect(within(other).queryByRole('listitem')).not.toBeInTheDocument()
  })

  it('asks the case book which of this case\'s wallets other complaints reached', async () => {
    const fetch = show({ routes: { '/cases/correlate': { body: { clusters: [cluster(ROUTE, ['TOther1', 'TOther2'], 1), cluster('TNotInThisCase', ['TOther1', 'TOther3'])] } } } })
    const other = screen.getByRole('region', { name: 'Other complaints' })
    const row = await within(other).findByText('3 other complaints')
    expect(row.closest('li')).toHaveTextContent('Route to Binance')
    expect(within(other).getAllByRole('listitem')).toHaveLength(1)
    // A recorded example is not in the case book, so it asks by wallet.
    expect(String(fetch.mock.calls[0][0])).toMatch(/\/cases\/correlate$/)
  })

  it('reads a stored case\'s answer from the page, without asking again, and leaves its own complaint out', async () => {
    const fetch = show({
      caseId: 'c1',
      correlation: { clusters: [cluster(ROUTE, [demo.address, 'TOther1'])], related_cases: [] },
    })
    const other = screen.getByRole('region', { name: 'Other complaints' })
    expect(within(other).getByText('1 other complaint')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('the blocks the tab already had', () => {
  it('keeps Hints · N, with the hit rate, and Related cases', () => {
    show({ routes: { '/cases/correlate': { body: { clusters: [] } } } })
    expect(screen.getByText('Hints · 1')).toBeInTheDocument()
    expect(screen.getByText(/^Measured on real wallets, this shape appeared in 6 of 32/)).toBeInTheDocument()
    expect(screen.getByText('Related cases · none')).toBeInTheDocument()
    expect(screen.queryByText(/Patterns ·/)).not.toBeInTheDocument()
  })
})
