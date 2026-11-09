import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import EntitiesTab from './EntitiesTab'
import recordings from '../../../../backend/data/recorded_demos.json'
import { stubFetch } from '../../test/setup'

// The Entities view of demo 11: 30 wallets in 8 groups, by the role each
// plays in the case (not by who owns them), a card for the group chosen, and
// the other complaints that reached the same wallets.
const demo = recordings.find((r) => r.demo === 11).result
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

describe('every wallet', () => {
  it('shows the graph with the flow by hop beside it, in place of the groups', async () => {
    const user = userEvent.setup()
    show()
    await user.click(screen.getByRole('button', { name: 'Every wallet' }))
    expect(screen.getByRole('button', { name: 'Every wallet' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('group', { name: '30 wallets in 8 groups' })).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Money flow by hop' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeInTheDocument()
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
