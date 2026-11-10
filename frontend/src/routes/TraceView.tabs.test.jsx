import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TraceView from './TraceView'
import { CASE_TABS } from './caseTab'
import recordings from '../../../backend/data/recorded_demos.json'
import { stubFetch } from '../test/setup'

// The case page in tabs (Flow · Timeline · Entities · Evidence · Letters):
// the blocks it had, moved into the view each belongs to, and what the
// pinned tests read kept above the tabs. Demo 11: Tron USDT, traced from the
// address, two wallets frozen by Tether, 30 wallets and 34 transfers.
const demo = recordings.find((r) => r.demo === 11)

function Where() {
  const { pathname, search } = useLocation()
  return <p data-testid="where">{pathname + search}</p>
}

async function openDemo11({ tab, routes = {}, ...overrides } = {}) {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  const fetch = stubFetch({ '/demos/recorded/11': { body: { ...demo.result, case_id: null, created_at: demo.recorded_at, recorded_demo: 11, ...overrides } }, ...routes })
  render(
    <MemoryRouter initialEntries={[`/demo/11${tab ? `?tab=${tab}` : ''}`]}>
      <Routes><Route path="/demo/:demoNo" element={<><TraceView /><Where /></>} /></Routes>
    </MemoryRouter>,
  )
  await screen.findByText(/Verified example 11/)
  return fetch
}

const panel = () => screen.getByRole('tabpanel')

// What each view holds, by text that names the block.
const BLOCKS = {
  flow: [/^Money flow · 30 addresses · 34 transfers$/],
  timeline: [/^Transfers that matter · /, /^Wallet statement · USDT$/],
  entities: [/^Hints · 1$/, /^Related cases · none$/],
  evidence: [/^Scope and evidence$/],
  letters: [/need a stored case/],
}

describe('the case page in tabs', () => {
  it('opens on Flow, with the money-flow card as it was', async () => {
    await openDemo11()
    expect(screen.getByRole('tab', { name: 'Flow' })).toHaveAttribute('aria-selected', 'true')
    expect(within(panel()).getByRole('button', { name: 'By hop' })).toBeInTheDocument()
    expect(within(panel()).getByRole('button', { name: 'Bubbles' })).toBeInTheDocument()
  })

  it.each(CASE_TABS.map((t) => t.key))('reaches the %s blocks through ?tab=, and draws no other view', async (tab) => {
    await openDemo11({ tab })
    expect(screen.getByRole('tab', { selected: true })).toHaveTextContent(CASE_TABS.find((t) => t.key === tab).label)
    for (const text of BLOCKS[tab]) expect(within(panel()).getByText(text)).toBeVisible()
    for (const [other, texts] of Object.entries(BLOCKS)) {
      if (other !== tab) for (const text of texts) expect(screen.queryByText(text)).not.toBeInTheDocument()
    }
  })

  it.each(CASE_TABS.map((t) => t.key))('keeps the alert, the band and its wording above the %s tab', async (tab) => {
    await openDemo11({ tab })
    const big = document.querySelector('.sure .big')
    expect(big).toHaveTextContent('Low')
    expect(big.textContent).not.toMatch(/\d/)
    expect(screen.getByText('a rule of three inputs, not a probability')).toBeVisible()
    expect(document.querySelector('.score-working')).toHaveTextContent('read the band, not the decimal')
    expect(document.querySelector('.alert')).toHaveTextContent('2 risk screening hits')
    for (const above of [document.querySelector('.finding-bar'), document.querySelector('.alert')]) {
      expect(panel()).not.toContainElement(above)
    }
  })

  // Blocks demo 11 does not have: a payment, an inferred deposit, a swap and
  // the follow-on it led to; and, on a reverse trace, the funders.
  const DEPOSIT = 'T' + 'Q'.repeat(33)
  const SWAP_TX = 'b'.repeat(64)
  const FULLER = {
    intake: { mode: 'payment', payments: [{ tx_hash: '0x' + 'a1'.repeat(32), amount: 4005, timestamp: 1_700_000_000, from: 'T' + '5'.repeat(33) }] },
    reported_amount: 4005,
    inferred_deposits: [{ address: DEPOSIT, exchange: 'Binance', depth: 2, evidence: { sweep_count: 3, sweep_destination_label: 'Binance-Hot 7', total_swept_native: 900 } }],
    swaps: [{ tx: SWAP_TX, sender: DEPOSIT, amount_in: 100, asset_in: 'USDT', router_label: 'SunSwap', output_read: true, amount_out: 300, asset_out: 'TRX' }],
    follow_ons: [{ address: DEPOSIT, asset: 'TRX', swap: { tx: SWAP_TX }, result: { graph: demo.result.graph, trace_path: [], exchange: null } }],
  }
  const FULLER_BLOCKS = {
    flow: [/^Continued in TRX after the swap · 30 addresses/],
    timeline: [/^Victim's payments · 1$/],
    entities: [/^Inferred deposit addresses · 1$/, /^Swaps · 1$/],
  }

  it.each(Object.keys(FULLER_BLOCKS))('reaches the rest of the %s blocks through ?tab=, in no other view', async (tab) => {
    await openDemo11({ tab, ...FULLER })
    for (const text of FULLER_BLOCKS[tab]) expect(within(panel()).getByText(text)).toBeVisible()
    for (const [other, texts] of Object.entries(FULLER_BLOCKS)) {
      if (other !== tab) for (const text of texts) expect(screen.queryByText(text)).not.toBeInTheDocument()
    }
  })

  it('reaches the funders of a reverse trace through ?tab=entities', async () => {
    const funders = [{ address: DEPOSIT, value_native: 50, tx_count: 2, exchange: 'Binance' }]
    await openDemo11({ tab: 'entities', direction: 'incoming', direct_senders: funders })
    expect(within(panel()).getByText(/^Funded this address · 1$/)).toBeVisible()
  })

  it('keeps a view drawn after leaving it', async () => {
    const user = userEvent.setup()
    await openDemo11({ tab: 'entities' })
    await user.click(screen.getByRole('tab', { name: 'Evidence' }))
    expect(screen.getByText('Hints · 1')).not.toBeVisible()
    expect(screen.getByText('Scope and evidence')).toBeVisible()
    expect(screen.getByTestId('where')).toHaveTextContent('/demo/11?tab=evidence')
  })
})

describe('the case header', () => {
  it('sums the case up in pills, from the case itself', async () => {
    await openDemo11()
    const pills = [...document.querySelectorAll('.case-pill')].map((p) => p.textContent)
    expect(pills).toEqual(['Tron USDT', '2 hops', '30 wallets', '34 transfers', '2 frozen by Tether', 'Verified example 11 · 2026-11-09'])
    expect(document.querySelector('.case-pill.risk')).toHaveTextContent('2 frozen by Tether')
  })

  it('says an address-only trace is exploratory, on the right of the pills row', async () => {
    await openDemo11()
    expect(document.querySelector('.case-origin')).toHaveTextContent('Exploratory, traced from the address')
    expect(document.querySelector('.case-pills').lastElementChild).toBe(document.querySelector('.case-origin'))
  })

  it('names the reported address as the page heading, and offers Present', async () => {
    await openDemo11()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^Reported address/)
    expect(screen.getByRole('button', { name: 'Present' })).toBeInTheDocument()
  })

  it('shows what the victim paid, when, and the NCRP number masked in the origin line', async () => {
    const pay = { tx_hash: '0x' + 'a1'.repeat(32), amount: 4005, timestamp: 1_700_000_000, from: '0x' + '5'.repeat(40) }
    await openDemo11({ intake: { mode: 'payment', ncrp_ack: '31911250012345', payments: [pay] }, reported_amount: 4005 })
    // 1 700 000 000 is 14 Nov 2023, 22:13 UTC: 15 Nov in India.
    expect(document.querySelectorAll('.case-pill')[1]).toHaveTextContent(/^4,?005 USDT paid · 15 Nov 2023$/)
    const origin = document.querySelector('.case-origin')
    expect(origin).toHaveTextContent(/^Traced from the victim's payment · NCRP ••••.*2345$/)
    expect(origin).not.toHaveTextContent('3191125')
  })

  it('names the issuer of each freeze, read as plain text', async () => {
    const frozen = demo.result.risk_matches[0]
    await openDemo11({ risk_matches: [frozen, { ...frozen, address: 'T2', issuer: 'Circ​le' }, { ...frozen, address: 'T3', category: 'sanctioned' }] })
    const risk = [...document.querySelectorAll('.case-pill.risk')].map((p) => p.textContent)
    expect(risk).toEqual(['1 frozen by Tether', '1 frozen by Circle'])
  })
})

describe('the letters of a recorded example', () => {
  it('are drafted from the recording, while the freeze log and watches wait for a stored case', async () => {
    await openDemo11({ tab: 'letters', routes: {
      '/demos/recorded/11/letters': { body: { case_id: null, recorded_demo: 11, letters: [{ to: 'exchange', title: 'Request to Binance' }, { to: 'tether', title: 'Request to Tether' }] } },
      '/demos/recorded/11/letter': { body: 'To        : Binance\n' },
    } })
    expect(await within(panel()).findByRole('button', { name: 'Request to Binance' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(panel()).getByRole('article', { name: 'Draft: Request to Binance' })).toBeInTheDocument()
    expect(within(panel()).getByText(/need a stored case/)).toBeVisible()
    expect(within(panel()).queryByText(/Freeze requests ·/)).not.toBeInTheDocument()
  })
})

describe('the letters, freeze requests and watches of a stored case', () => {
  const routes = {
    '/trace/c1/letters': { body: { letters: [{ to: 'exchange', title: 'Request to Binance' }] } },
    '/trace/c1/requests': { body: { count: 0, requests: [] } },
    '/watches': { body: { count: 0, watches: [] } },
  }

  it('sit in the Letters tab', async () => {
    await openDemo11({ tab: 'letters', case_id: 'c1', routes })
    expect(await within(panel()).findByRole('button', { name: /Request to Binance/ })).toBeInTheDocument()
    expect(within(panel()).getByText(/Freeze requests · 0/)).toBeInTheDocument()
    expect(within(panel()).getByText('Watch for movement')).toBeInTheDocument()
    expect(screen.queryByText(/need a stored case/)).not.toBeInTheDocument()
  })

  it('point the freeze log at the draft letters above it, not at Export', async () => {
    await openDemo11({ tab: 'letters', case_id: 'c1', routes })
    expect(await within(panel()).findByText(/^Draft the letter above, send it, then log it here\./)).toBeInTheDocument()
    expect(screen.queryByText(/from Export/)).not.toBeInTheDocument()
  })

  it('say only to send and log a request when the case supports no letter', async () => {
    await openDemo11({ tab: 'letters', case_id: 'c1', routes: { ...routes, '/trace/c1/letters': { body: { letters: [] } } } })
    expect(await within(panel()).findByText(/^Send the request, then log it here\./)).toBeInTheDocument()
    expect(screen.queryByText(/Draft the letter/)).not.toBeInTheDocument()
  })

  it('leave the Export menu to the files', async () => {
    const user = userEvent.setup()
    await openDemo11({ tab: 'letters', case_id: 'c1', routes })
    await within(panel()).findByRole('button', { name: /Request to Binance/ })
    await user.click(screen.getByRole('button', { name: 'Export' }))
    const menu = screen.getByRole('menu')
    expect(within(menu).getByRole('menuitem', { name: /Report \(\.pdf\)/ })).toBeInTheDocument()
    expect(within(menu).queryByRole('menuitem', { name: /Request to Binance/ })).not.toBeInTheDocument()
  })
})

describe('a live trace that finishes', () => {
  it('opens its case on the tab the link asked for, and keeps it saved while tabs change', async () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    const calls = []
    vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
      const path = String(url).replace(/^\/api/, '').split('?')[0]
      const method = init.method || 'GET'
      calls.push(`${method} ${path}`)
      const json = (body, status = 200) => new Response(JSON.stringify(body), { status })
      if (method === 'POST' && path === '/trace/jobs') return json({ job_id: 'j9', status: 'running', progress: { stage: 'starting' } }, 202)
      if (path === '/trace/jobs/j9') return json({ job_id: 'j9', status: 'done', result: { ...demo.result, case_id: 'c9', created_at: demo.recorded_at } })
      return json({ detail: 'not stubbed' }, 404)
    }))
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={[{ pathname: `/trace/${demo.result.address}`, search: '?chain=tron&asset=USDT&depth=2&tab=entities', state: { startedHere: true } }]}>
        <Routes>
          <Route path="/trace/:address" element={<TraceView />} />
          <Route path="/case/:caseId" element={<><TraceView /><Where /></>} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByText('Hints · 1')).toBeVisible()
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/case\/c9\?tab=entities$/)
    expect(screen.getByText(/^Saved/)).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Timeline' }))
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/case\/c9\?tab=timeline$/)
    expect(screen.getByText(/^Saved/)).toBeInTheDocument()
    expect(calls).not.toContain('GET /trace/c9')
  })
})

describe('Present from the keyboard', () => {
  const presenting = () => screen.queryByRole('dialog', { name: 'Present the case' })

  it.each([['Ctrl', '{Control>}p{/Control}'], ['Cmd', '{Meta>}p{/Meta}'], ['Alt', '{Alt>}p{/Alt}']])(
    'leaves %s+P to the browser, which prints the page', async (_, keys) => {
      const user = userEvent.setup()
      await openDemo11({ tab: 'letters' })
      const event = vi.fn()
      window.addEventListener('keydown', event)
      await user.keyboard(keys)
      window.removeEventListener('keydown', event)
      expect(presenting()).not.toBeInTheDocument()
      expect(event.mock.calls.find(([e]) => e.key === 'p')[0].defaultPrevented).toBe(false)
    })

  it('opens on a bare P, though not while typing in an editable area', async () => {
    const user = userEvent.setup()
    await openDemo11()
    const editable = document.createElement('div')
    editable.contentEditable = 'true'
    // jsdom does not work this out from the attribute; a browser does.
    Object.defineProperty(editable, 'isContentEditable', { value: true })
    editable.tabIndex = 0
    document.body.append(editable)
    editable.focus()
    await user.keyboard('p')
    expect(presenting()).not.toBeInTheDocument()
    editable.remove()
    await user.keyboard('P')
    expect(presenting()).toBeInTheDocument()
  })

  it('is a modal: the page behind it is inert, focus moves in, and returns on Escape', async () => {
    const user = userEvent.setup()
    await openDemo11()
    const button = screen.getByRole('button', { name: 'Present' })
    await user.click(button)
    const dialog = presenting()
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toContainElement(document.activeElement)
    const behind = screen.getByRole('heading', { level: 1 })
    expect(behind.closest('[inert]')).not.toBeNull()
    expect(dialog.closest('[inert]')).toBeNull()
    await user.keyboard('{Escape}')
    expect(presenting()).not.toBeInTheDocument()
    expect(document.querySelector('[inert]')).toBeNull()
    expect(button).toHaveFocus()
  })
})

describe('the money-flow view buttons', () => {
  it('say which view is showing, to a screen reader too', async () => {
    const user = userEvent.setup()
    await openDemo11()
    const hop = within(panel()).getByRole('button', { name: 'By hop' })
    const bubbles = within(panel()).getByRole('button', { name: 'Bubbles' })
    expect(hop).toHaveAttribute('aria-pressed', 'true')
    expect(bubbles).toHaveAttribute('aria-pressed', 'false')
    await user.click(bubbles)
    expect(hop).toHaveAttribute('aria-pressed', 'false')
    expect(bubbles).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('a trace continued after a swap', () => {
  it('states its confidence as the band word, with no decimal', async () => {
    const DEPOSIT = 'TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU'
    await openDemo11({
      follow_ons: [{ address: DEPOSIT, asset: 'TRX', swap: { tx: 'ab'.repeat(32) },
        result: { graph: demo.result.graph, trace_path: [], exchange: 'Binance', exchange_label: 'Binance-Hot 7', confidence: 0.49 } }],
    })
    const head = within(panel()).getByText(/^Continued in TRX after the swap/)
    expect(head).toHaveTextContent(/reached Binance-Hot 7 · low confidence$/)
    expect(head.textContent).not.toMatch(/\d\.\d/)
  })
})
