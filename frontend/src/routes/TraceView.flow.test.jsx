import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TraceView from './TraceView'
import recordings from '../../../backend/data/recorded_demos.json'
import flow from '../test/victim-flow-11.json'
import { stubFetch } from '../test/setup'

// The Flow tab draws where the victim's share went when the case carries an
// estimated victim_flow, and falls back to the money-flow card when it does
// not. Its buttons open the Letters tab, or a deeper trace that still asks
// before it runs.
const demo = recordings.find((r) => r.demo === 11)
const TT4Y = 'TT4yg2GguWvN5j8Xeb7nUB5Hg2wWd1dFp3'

function Where() {
  const { pathname, search } = useLocation()
  return <p data-testid="where">{pathname + search}</p>
}

async function openDemo11({ search = '', routes = {}, ...overrides } = {}) {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  stubFetch({ '/demos/recorded/11': { body: { ...demo.result, case_id: null, created_at: demo.recorded_at, recorded_demo: 11, ...overrides } }, ...routes })
  render(
    <MemoryRouter initialEntries={[`/demo/11${search}`]}>
      <Routes>
        <Route path="/demo/:demoNo" element={<><TraceView /><Where /></>} />
        <Route path="/trace/:address" element={<><TraceView /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByText(/Verified example 11/)
}
const panel = () => screen.getByRole('tabpanel')
const where = () => screen.getByTestId('where').textContent

describe('the Flow tab', () => {
  it.each([[undefined], [{ status: 'not_applicable' }], [{ status: 'unavailable', reason: 'x' }]])('keeps the money-flow card when the flow is %j', async (victim_flow) => {
    await openDemo11({ victim_flow })
    expect(within(panel()).getByText(/^Money flow · 30 addresses · 34 transfers$/)).toBeVisible()
    expect(within(panel()).getByRole('button', { name: 'By hop' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: "Where the victim's share went" })).not.toBeInTheDocument()
  })

  it('draws the victim\'s share when the case carries it, with every wallet a click away', async () => {
    const user = userEvent.setup()
    await openDemo11({ victim_flow: flow })
    expect(within(panel()).getByRole('heading', { name: "Where the victim's share went" })).toBeInTheDocument()
    expect(within(panel()).queryByRole('button', { name: 'By hop' })).not.toBeInTheDocument()
    await user.click(within(panel()).getByText('Every wallet · 30 addresses · 34 transfers'))
    expect(within(panel()).getByRole('button', { name: 'By hop' })).toBeInTheDocument()
  })

  it('opens the Letters tab from Draft letter, naming the urgent freeze letter', async () => {
    const user = userEvent.setup()
    await openDemo11({ victim_flow: flow })
    await user.click(screen.getByRole('button', { name: 'Draft letter to Binance' }))
    expect(screen.getByRole('tab', { selected: true })).toHaveTextContent('Letters')
    expect(where()).toBe('/demo/11?tab=letters&letter=exchange-freeze')
    await waitFor(() => expect(panel()).toHaveFocus())
  })

  it('opens the Letters tab from Ask Tether, with the Tether letter', async () => {
    const user = userEvent.setup()
    await openDemo11({ victim_flow: flow })
    await user.click(screen.getByRole('button', { name: 'Ask Tether' }))
    expect(where()).toBe('/demo/11?tab=letters&letter=tether')
  })

  it('asks before tracing two hops deeper: the deeper trace spends the allowance', async () => {
    const user = userEvent.setup()
    await openDemo11({ victim_flow: flow })
    await user.click(screen.getByRole('button', { name: 'Trace 2 hops deeper' }))
    expect(where()).toBe(`/trace/${demo.result.address}?chain=tron&asset=USDT&depth=4&direction=outgoing`)
    expect(await screen.findByRole('heading', { name: 'Run this trace?' })).toBeInTheDocument()
  })

  it('takes Watch to the watch panel with the wallet where money is left', async () => {
    const user = userEvent.setup()
    await openDemo11({ victim_flow: flow })
    await user.click(screen.getByRole('button', { name: 'Watch' }))
    expect(where()).toBe(`/demo/11?tab=letters&watch=${TT4Y}`)
  })
})

describe('the Letters tab, opened from a flow card', () => {
  const routes = {
    '/trace/c1/letters': { body: { letters: [{ to: 'exchange', title: 'Request to Binance' }, { to: 'tether', title: 'Request to Tether' }] } },
    '/trace/c1/requests': { body: { count: 0, requests: [] } },
    '/watches': { body: { count: 0, watches: [] } },
  }

  it('puts the keyboard on the letter it was asked for', async () => {
    await openDemo11({ search: '?tab=letters&letter=tether', case_id: 'c1', routes })
    const tether = await within(panel()).findByRole('button', { name: /Request to Tether/ })
    await waitFor(() => expect(tether).toHaveFocus())
  })

  it.each([
    ['the urgent freeze letter, which goes first', [{ to: 'exchange-freeze', title: 'Urgent freeze request to Binance' }, { to: 'exchange', title: 'Request to Binance' }], 'Urgent freeze request to Binance'],
    ['the information letter, when the case lists no freeze letter', [{ to: 'exchange', title: 'Request to Binance' }, { to: 'tether', title: 'Request to Tether' }], 'Request to Binance'],
  ])('takes Draft letter to %s', async (_, letters, title) => {
    const user = userEvent.setup()
    await openDemo11({ case_id: 'c1', victim_flow: flow, routes: { ...routes, '/trace/c1/letters': { body: { letters } } } })
    await user.click(screen.getByRole('button', { name: 'Draft letter to Binance' }))
    const asked = await within(panel()).findByRole('button', { name: title, pressed: true })
    await waitFor(() => expect(asked).toHaveFocus())
  })

  it('offers to watch the wallet it was asked to', async () => {
    await openDemo11({ search: `?tab=letters&watch=${TT4Y}`, case_id: 'c1', routes, victim_flow: flow })
    expect(await within(panel()).findByText(/^TT4yg2GguW…/)).toBeInTheDocument()
    expect(within(panel()).getAllByRole('button', { name: 'Watch' })).toHaveLength(2)
  })

  it.each([
    ['a wallet the flow does not leave money in', 'TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU', flow],
    ['any wallet, when the case has no flow', TT4Y, undefined],
  ])('offers nothing more for a link that names %s', async (_, address, victim_flow) => {
    await openDemo11({ search: `?tab=letters&watch=${address}`, case_id: 'c1', routes, victim_flow })
    await within(panel()).findByText(/the reported wallet/)
    expect(within(panel()).getAllByRole('button', { name: 'Watch' })).toHaveLength(1)
    expect(within(panel()).queryByText(/victim's money is left/)).not.toBeInTheDocument()
  })
})
