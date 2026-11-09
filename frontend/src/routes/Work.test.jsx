import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import Work from './Work'
import { stubFetch } from '../test/setup'

// The console's pages that were Home's tabs, and the trace form on a page of
// its own. Each has its own heading and one line on what it is for. The
// Cases page is its own (Cases.test.jsx).
const oneChain = {
  status: 'ok',
  default_chain: 'ethereum',
  chains: { ethereum: { key: 'ethereum', name: 'Ethereum', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }] } },
}
const stored = {
  count: 1,
  cases: [{ case_id: 'c1', address: '0x' + 'ab'.repeat(20), chain: 'ethereum', asset: 'ETH', exchange: 'Binance',
            confidence: 0.875, node_count: 4, flag_count: 0, created_at: '2026-11-04T10:00:00+00:00' }],
}

function Landed() {
  const { pathname } = useLocation()
  return <p data-testid="landed">{pathname}</p>
}

function open(page, { path = '/', access = { demo_code_required: false }, extra = {} } = {}) {
  const fetch = stubFetch({
    '/chains': { body: oneChain }, '/cases': { body: stored }, '/access': { body: access },
    '/watches': { body: { watches: [] } }, '/alerts': { body: { alerts: [] } }, '/requests': { body: { requests: [] } },
    '/batches': { body: { batches: [] } }, '/demos/recorded': { body: { demos: [] } }, ...extra,
  })
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/case/:id" element={<Landed />} />
        <Route path="*" element={<Work page={page} />} />
      </Routes>
    </MemoryRouter>,
  )
  return fetch
}

describe('the monitor pages', () => {
  it.each([
    ['watchlist', 'Watchlist', 'Wallets this browser watches, and what moved'],
    ['requests', 'Requests', 'Letters logged from a case and still waiting on someone'],
    ['batch', 'Bulk intake', 'Trace up to 25 complaints from a CSV, then see what they share'],
  ])('heads %s with its title and one line on what it is for', async (page, title, line) => {
    open(page)
    const head = screen.getByRole('heading', { level: 1, name: title }).parentElement
    expect(head).toHaveTextContent(line)
    expect(head.firstElementChild).toHaveTextContent(line)
  })

  it.each([['watchlist', /^Nothing watched yet/], ['requests', /^No open requests/]])('puts an empty %s in its own card', async (page, empty) => {
    open(page)
    expect((await screen.findByText(empty)).closest('.card')).toHaveClass('glass')
  })

  it('shows the watchlist, or says nothing is watched', async () => {
    open('watchlist')
    expect(screen.getByRole('heading', { level: 1, name: 'Watchlist' })).toBeInTheDocument()
    expect(await screen.findByText(/Nothing watched yet/)).toBeInTheDocument()
  })

  it('shows the open requests, or says there are none', async () => {
    open('requests')
    expect(screen.getByRole('heading', { level: 1, name: 'Requests' })).toBeInTheDocument()
    expect(await screen.findByText(/No open requests/)).toBeInTheDocument()
  })

  it('opens bulk intake ready to paste', async () => {
    open('batch')
    expect(screen.getByRole('heading', { level: 1, name: 'Bulk intake' })).toBeInTheDocument()
    expect(await screen.findByLabelText('Complaints CSV')).toBeVisible()
  })

  it.each(['watchlist', 'batch'])('keeps %s shut on a public site until the demo code is given', async (page) => {
    open(page, { access: { demo_code_required: true } })
    expect(await screen.findByText(/needs the demo code/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Complaints CSV')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /enter the code/i })).toHaveAttribute('href', '/trace/new')
  })
})

describe('the new trace page', () => {
  it('holds the trace form', async () => {
    open('new', { extra: { '/trace/intake': { body: { payments: true } } } })
    expect(screen.getByRole('heading', { level: 1, name: 'New trace' })).toBeInTheDocument()
    expect(await screen.findByLabelText('Reported wallet address')).toBeInTheDocument()
  })

  it('fills in a payment hash it was sent', async () => {
    const hash = `0x${'c'.repeat(64)}`
    open('new', { path: `/trace/new?pay=${hash}`, extra: { '/trace/intake': { body: { payments: true } } } })
    expect(await screen.findByLabelText(/Victim's payment transaction hash/)).toHaveValue(hash)
  })

  it('says so when this site does not trace from a payment hash, and keeps the hash in view', async () => {
    const hash = `0x${'c'.repeat(64)}`
    open('new', { path: `/trace/new?pay=${hash}`, extra: { '/trace/intake': { body: { payments: false } } } })
    const note = await screen.findByText(/Tracing from a payment hash is off on this site/)
    expect(note).toHaveTextContent(hash)
    expect(note).toHaveTextContent(/paste the wallet the victim paid/i)
    expect(screen.queryByLabelText(/Victim's payment transaction hash/)).not.toBeInTheDocument()
  })

  it('starts a Tron hash on Tron, whatever the site\'s default chain', async () => {
    const hash = 'd'.repeat(64)
    const both = { ...oneChain, chains: { ...oneChain.chains, tron: { key: 'tron', name: 'Tron', ready: true, address_family: 'tron', assets: [{ symbol: 'USDT' }] } } }
    open('new', { path: `/trace/new?pay=${hash}&chain=tron`, extra: { '/chains': { body: both }, '/trace/intake': { body: { payments: true } } } })
    expect(await screen.findByLabelText(/Victim's payment transaction hash/)).toHaveValue(hash)
    await waitFor(() => expect(screen.getByLabelText('Blockchain')).toHaveValue('tron'))
    expect(screen.getByLabelText('Asset')).toHaveValue('USDT')
    expect(screen.queryByText(/Not a valid .* transaction hash/)).not.toBeInTheDocument()
  })

  it('starts a hash on the chain and asset the console chose for it', async () => {
    const hash = `0x${'d'.repeat(64)}`
    const three = { ...oneChain, chains: { ethereum: { ...oneChain.chains.ethereum, assets: [{ symbol: 'ETH' }, { symbol: 'USDT' }, { symbol: 'USDC' }] } } }
    open('new', { path: `/trace/new?pay=${hash}&chain=ethereum&asset=USDC`, extra: { '/chains': { body: three }, '/trace/intake': { body: { payments: true } } } })
    expect(await screen.findByLabelText(/Victim's payment transaction hash/)).toHaveValue(hash)
    await waitFor(() => expect(screen.getByLabelText('Asset')).toHaveValue('USDC'))
    expect(screen.getByLabelText('Blockchain')).toHaveValue('ethereum')
  })

  it('asks for the demo code on a public site instead', async () => {
    open('new', { access: { demo_code_required: true } })
    expect(await screen.findByLabelText('Access code')).toBeInTheDocument()
    expect(screen.queryByLabelText('Reported wallet address')).not.toBeInTheDocument()
  })
})
