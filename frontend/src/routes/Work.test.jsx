import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    expect(await screen.findByLabelText('Wallet the victim paid')).toBeInTheDocument()
  })

  it('fills in a payment hash it was sent', async () => {
    const hash = `0x${'c'.repeat(64)}`
    open('new', { path: `/trace/new?pay=${hash}`, extra: { '/trace/intake': { body: { payments: true } } } })
    expect(await screen.findByLabelText(/victim's payment hashes/i)).toHaveValue(hash)
  })

  it('says so when this site does not trace from a payment hash, and keeps the hash in view', async () => {
    const hash = `0x${'c'.repeat(64)}`
    open('new', { path: `/trace/new?pay=${hash}`, extra: { '/trace/intake': { body: { payments: false } } } })
    const note = await screen.findByText(/Tracing from a payment hash is off on this site/)
    expect(note).toHaveTextContent(hash)
    expect(note).toHaveTextContent(/paste the wallet the victim paid/i)
    expect(screen.queryByLabelText(/victim's payment hashes/i)).not.toBeInTheDocument()
  })

  it('starts a Tron hash on Tron, whatever the site\'s default chain', async () => {
    const hash = 'd'.repeat(64)
    const both = { ...oneChain, chains: { ...oneChain.chains, tron: { key: 'tron', name: 'Tron', ready: true, address_family: 'tron', assets: [{ symbol: 'USDT' }] } } }
    open('new', { path: `/trace/new?pay=${hash}&chain=tron`, extra: { '/chains': { body: both }, '/trace/intake': { body: { payments: true } } } })
    expect(await screen.findByLabelText(/victim's payment hashes/i)).toHaveValue(hash)
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Tron' })).toBeChecked())
    expect(screen.getByRole('radio', { name: 'USDT' })).toBeChecked()
    expect(screen.queryByText(/Not a valid .* transaction hash/)).not.toBeInTheDocument()
  })

  it('starts a hash on the chain and asset the console chose for it', async () => {
    const hash = `0x${'d'.repeat(64)}`
    const three = { ...oneChain, chains: { ethereum: { ...oneChain.chains.ethereum, assets: [{ symbol: 'ETH' }, { symbol: 'USDT' }, { symbol: 'USDC' }] } } }
    open('new', { path: `/trace/new?pay=${hash}&chain=ethereum&asset=USDC`, extra: { '/chains': { body: three }, '/trace/intake': { body: { payments: true } } } })
    expect(await screen.findByLabelText(/victim's payment hashes/i)).toHaveValue(hash)
    await waitFor(() => expect(screen.getByRole('radio', { name: 'USDC' })).toBeChecked())
    expect(screen.getByRole('radio', { name: 'Ethereum' })).toBeChecked()
  })

  it('asks for the demo code inside the search when it finds the site locked, and keeps the form', async () => {
    const user = userEvent.setup()
    const tron = { status: 'ok', default_chain: 'tron', chains: { tron: { key: 'tron', name: 'Tron', ready: true, address_family: 'tron', assets: [{ symbol: 'USDT' }] } } }
    let calls = 0
    open('new', { extra: { '/chains': { body: tron }, '/trace/intake': { body: { payments: true } }, '/access/check': { body: { pass: 'p1' } },
      '/payments/search': () => (calls++ === 0
        ? { status: 403, body: { detail: 'Live tracing on this site needs an access code.' } }
        : { body: { matches: [], more_matches: false, scanned: 3, complete: true } }) } })
    await user.type(await screen.findByLabelText('Wallet the victim paid'), 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts')
    await user.click(await screen.findByRole('button', { name: "I don't have the payment hash" }))
    await user.type(screen.getByLabelText('Exact amount paid'), '10')
    fireEvent.change(screen.getByLabelText('When the victim paid, in IST'), { target: { value: '2026-11-09T14:30' } })
    await user.click(screen.getByRole('button', { name: 'Search the wallet' }))
    await user.type(await screen.findByLabelText('Access code'), 'letmein')
    await user.click(screen.getByRole('button', { name: 'Unlock and search again' }))
    expect(await screen.findByText(/No transfer of exactly 10 USDT/)).toBeInTheDocument()
    expect(screen.getByLabelText('Wallet the victim paid')).toHaveValue('TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts')
    expect(screen.queryByText('Verified examples')).not.toBeInTheDocument()
  })

  it('asks for the demo code on a public site instead', async () => {
    open('new', { access: { demo_code_required: true } })
    expect(await screen.findByLabelText('Access code')).toBeInTheDocument()
    expect(screen.queryByLabelText('Wallet the victim paid')).not.toBeInTheDocument()
  })
})

describe('a site the owner has closed to officers', () => {
  const closed = { demo_code_required: false, console: 'officers', officer: false }

  it('sends the new trace page to the officer sign-in instead of the code box', async () => {
    open('new', { access: closed })
    const link = await screen.findByRole('link', { name: 'Sign in as an officer to trace live' })
    expect(link).toHaveAttribute('href', '/signin/investigator')
    expect(screen.queryByLabelText('Access code')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Wallet the victim paid')).not.toBeInTheDocument()
  })

  it.each(['watchlist', 'batch'])('keeps %s shut until an officer signs in', async (page) => {
    open(page, { access: closed })
    expect(await screen.findByText(/needs a signed-in officer/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Complaints CSV')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /sign in as an officer/i })).toHaveAttribute('href', '/signin/investigator')
  })

  it('opens every page to a signed-in officer', async () => {
    open('batch', { access: { ...closed, officer: true } })
    expect(await screen.findByLabelText('Complaints CSV')).toBeVisible()
    expect(screen.queryByText(/needs a signed-in officer/)).not.toBeInTheDocument()
  })
})
