import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import Home from './Home'
import { stubFetch } from '../test/setup'

const health = {
  status: 'ok',
  default_chain: 'ethereum',
  chains: {
    ethereum: { key: 'ethereum', name: 'Ethereum', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }] },
    tron: { key: 'tron', name: 'Tron', ready: true, address_family: 'tron', assets: [{ symbol: 'USDT' }] },
  },
}

function Landed() {
  const { pathname, search } = useLocation()
  return <p data-testid="landed">{pathname + search}</p>
}

const recordings = { demos: [{ demo: 6, recorded_at: '2026-10-14T16:44:03+00:00', address: '0x00000000072d54638c2c2a3da3f715360269eea1', exchange: 'Binance', confidence: 0.875 }] }

async function renderHome() {
  stubFetch({ '/chains': { body: health }, '/cases': { body: { count: 0, cases: [] } }, '/exchanges': { body: {} }, '/risk-labels': { body: {} }, '/demos/recorded': { body: recordings } })
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/trace/:address" element={<Landed />} />
        <Route path="/demo/:n" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByText(/Live · \d+ chains?$/)
}

describe('the trace form', () => {
  it('flags a malformed address and does not start a trace', async () => {
    const user = userEvent.setup()
    await renderHome()
    const field = screen.getByLabelText('Reported wallet address')
    await user.type(field, '0x1234')
    await user.keyboard('{Enter}')
    await user.tab()
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: /trace/i })).toBeDisabled()
    expect(screen.queryByTestId('landed')).not.toBeInTheDocument()
  })

  it('opens a shareable trace URL for a valid address', async () => {
    const user = userEvent.setup()
    await renderHome()
    const addr = '0x' + 'ab'.repeat(20)
    await user.type(screen.getByLabelText('Reported wallet address'), `  ${addr} {Enter}`)
    expect(screen.getByTestId('landed')).toHaveTextContent(
      `/trace/${addr}?chain=ethereum&asset=ETH&depth=4&direction=outgoing`)
  })

  it('holds a Tron address to the Tron format, not the EVM one', async () => {
    const user = userEvent.setup()
    await renderHome()
    await user.selectOptions(screen.getByLabelText('Blockchain'), 'tron')
    const field = screen.getByLabelText('Reported wallet address')
    await user.type(field, '0x' + 'ab'.repeat(20))
    await user.tab()
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: /trace/i })).toBeDisabled()
  })

  it('offers the recording of a loaded demo, and drops it once the form is edited', async () => {
    const user = userEvent.setup()
    await renderHome()
    await user.selectOptions(screen.getByLabelText('Load a verified example'), '06')
    const link = await screen.findByRole('link', { name: /open as recorded/i })
    expect(link).toHaveTextContent('2026-10-14')
    await user.type(screen.getByLabelText('Reported wallet address'), 'f')
    expect(screen.queryByRole('link', { name: /open as recorded/i })).not.toBeInTheDocument()
  })

  it('opens the recording without starting a trace', async () => {
    const user = userEvent.setup()
    await renderHome()
    await user.selectOptions(screen.getByLabelText('Load a verified example'), '06')
    await user.click(await screen.findByRole('link', { name: /open as recorded/i }))
    expect(screen.getByTestId('landed')).toHaveTextContent('/demo/6')
  })

  it('offers no recording for a demo that has none', async () => {
    const user = userEvent.setup()
    await renderHome()
    await user.selectOptions(screen.getByLabelText('Load a verified example'), '01')
    expect(screen.queryByRole('link', { name: /open as recorded/i })).not.toBeInTheDocument()
  })
})

describe('a public site that asks for a demo code', () => {
  async function renderPublicHome(check = { status: 403, body: { detail: 'That access code is not right.' } }) {
    const fetch = stubFetch({
      '/chains': { body: health }, '/cases': { body: { count: 0, cases: [] } }, '/demos/recorded': { body: recordings },
      '/access': { body: { demo_code_required: true } }, '/access/check': check,
    })
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/demo/:n" element={<Landed />} />
        </Routes>
      </MemoryRouter>,
    )
    await screen.findByLabelText('Access code')
    return fetch
  }

  it('shows the recorded demos and no way to start a trace, batch or watch', async () => {
    const user = userEvent.setup()
    await renderPublicHome()
    expect(screen.queryByLabelText('Reported wallet address')).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Bulk intake' })).not.toBeInTheDocument()
    expect(screen.queryByText('Bulk intake')).not.toBeInTheDocument()
    expect(screen.queryByText(/^Watchlist/)).not.toBeInTheDocument()
    await user.click(await screen.findByRole('link', { name: /reached Binance/ }))
    expect(screen.getByTestId('landed')).toHaveTextContent('/demo/6')
  })

  it('keeps the site locked and remembers nothing when the code is wrong', async () => {
    const user = userEvent.setup()
    await renderPublicHome()
    await user.type(screen.getByLabelText('Access code'), 'guess{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('not right')
    expect(screen.queryByLabelText('Reported wallet address')).not.toBeInTheDocument()
    expect(sessionStorage.getItem('exchequer-demo-code')).toBeNull()
  })

  it('unlocks live tracing with the right code and sends it from then on', async () => {
    const user = userEvent.setup()
    const fetch = await renderPublicHome({ body: { ok: true } })
    await user.type(screen.getByLabelText('Access code'), 'river-otter-42{Enter}')
    expect(await screen.findByLabelText('Reported wallet address')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Bulk intake' })).toBeInTheDocument()
    expect(sessionStorage.getItem('exchequer-demo-code')).toBe('river-otter-42')
    // Requests after the check itself, which carries the typed code by design.
    const checked = fetch.mock.calls.findIndex(([url]) => String(url).includes('/access/check'))
    const after = fetch.mock.calls.slice(checked + 1)
    expect(after.length).toBeGreaterThan(0)
    for (const [, init] of after) expect(new Headers(init.headers).get('X-Exchequer-Demo-Code')).toBe('river-otter-42')
  })
})

describe('the headline numbers (R14)', () => {
  const counted = {
    status: 'ok',
    default_chain: 'ethereum',
    chains: {
      ethereum: { key: 'ethereum', name: 'Ethereum', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }],
        exchange_labels: 25038, exchange_wallets: 975, deposit_addresses: 24063,
        risk_labels: { sanctioned: 127, mixer: 0, frozen: 2828, stolen: 11 } },
      tron: { key: 'tron', name: 'Tron', ready: true, address_family: 'tron', assets: [{ symbol: 'USDT' }],
        exchange_labels: 41, exchange_wallets: 40, deposit_addresses: 1,
        risk_labels: { sanctioned: 915, mixer: 0, frozen: 6759, stolen: 0 } },
    },
  }

  it('shows only numbers that /chains gives, and never one total as exchange wallets', async () => {
    stubFetch({ '/chains': { body: counted }, '/cases': { body: { count: 0, cases: [] } }, '/demos/recorded': { body: recordings } })
    render(<MemoryRouter><Home /></MemoryRouter>)
    await screen.findByText(/Live · 2 chains/)
    const chains = Object.values(counted.chains)
    const sum = (f) => chains.reduce((s, c) => s + f(c), 0)
    const flagged = sum((c) => Object.values(c.risk_labels).reduce((a, b) => a + b, 0))
    const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(flagged)
    const allowed = new Set([
      sum((c) => c.exchange_wallets), sum((c) => c.deposit_addresses), flagged, chains.length,
      ...chains.flatMap((c) => [c.exchange_wallets, c.deposit_addresses, ...Object.values(c.risk_labels),
        Object.values(c.risk_labels).reduce((a, b) => a + b, 0)]),
    ])
    const card = screen.getByLabelText('Flagged addresses screened')
    const tables = document.querySelector('.tab-panel .coverage')
    // Text node by text node: textContent would run neighbouring cells together.
    const shown = []
    for (const root of [card, tables]) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
      while (walker.nextNode()) {
        for (const m of walker.currentNode.nodeValue.match(/\d[\d,]*(?:\.\d+)?[KMB]?/g) ?? []) {
          // A compact figure ("10.9M") must be the flagged total, rounded; anything else is a plain count.
          if (/[KMB]$/.test(m)) expect(m).toBe(compact)
          else shown.push(Number(m.replace(/,/g, '')))
        }
      }
    }
    expect(shown.length).toBeGreaterThan(10)
    for (const n of shown) expect(allowed, `${n} is not from /chains`).toContain(n)
    expect(document.body.textContent).not.toContain('25038')
    expect(card).toHaveTextContent(`${compact}flagged addresses`)
    expect(card).toHaveTextContent(`${flagged.toLocaleString('en')} · screened on every hop`)
  })
})
