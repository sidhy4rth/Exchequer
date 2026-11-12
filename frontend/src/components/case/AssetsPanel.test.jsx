import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import AssetDeadlines from '../AssetDeadlines'
import AssetsPanel, { deadline, holderOf, todayInIndia } from './AssetsPanel'

// The asset register on the Letters tab (backend assets.py) and the home
// page's court-deadline card. Rows come from the backend; the panel shows the
// deadline, lets the officer record the court's order and the outcome, and
// adds a frozen request from the log above in one click.
const ROW = {
  asset_id: 'a1', case_id: 'c1', holder: 'custody', asset: 'USDT', amount: '635.000000', chain: 'tron',
  held_at: 'TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU', tx_hash: 'ab'.repeat(32), key_holders: '2 of 3: Insp. Rao, SI Iyer, SI Pal',
  request_id: null, seized_on: '2026-09-30', order_ref: '', status: 'held', outcome_ref: '', outcome_tx: '', notes: '',
  deadline: '2026-11-14', days_left: 2, due: true, history: [{ at: '2026-11-12T05:00:00Z', status: 'held' }],
}
const FROZEN = { request_id: 'r1', recipient: 'Binance', kind: 'exchange-freeze', status: 'frozen', amount_frozen: 635, asset: 'USDT' }

function api(routes) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const [path] = String(url).replace(/^\/api/, '').split('?')
    let body = init.body
    try { body = JSON.parse(body) } catch { /* none */ }
    calls.push({ method, path, body })
    const hit = routes[`${method} ${path}`]
    if (!hit) return new Response(JSON.stringify({ detail: 'not stubbed' }), { status: 404 })
    const { status = 200, body: out } = typeof hit === 'function' ? hit(body) : hit
    return new Response(JSON.stringify(out), { status })
  }))
  return calls
}

const open = () => render(<MemoryRouter><AssetsPanel result={{ case_id: 'c1' }} /></MemoryRouter>)

describe('the asset register panel', () => {
  it('shows each row with where it is held, who holds the keys and the court deadline', async () => {
    api({ 'GET /trace/c1/assets': { body: { assets: [ROW] } }, 'GET /trace/c1/requests': { body: { requests: [] } } })
    open()
    expect(await screen.findByText('Court order due in 2 days')).toBeInTheDocument()
    expect(screen.getByText('2 of 3: Insp. Rao, SI Iyer, SI Pal')).toBeInTheDocument()
    expect(screen.getByText(/1 court deadline this week/)).toBeInTheDocument()
  })

  it('adds a request the log marked Frozen in one click, linked to it', async () => {
    const calls = api({
      'GET /trace/c1/assets': { body: { assets: [] } },
      'GET /trace/c1/requests': { body: { requests: [FROZEN] } },
      'POST /trace/c1/assets': (b) => ({ status: 201, body: { ...ROW, ...b, asset_id: 'a2' } }),
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Add the 635 USDT Binance froze' }))
    const form = screen.getByRole('form', { name: 'Record frozen or seized funds' })
    expect(within(form).getByLabelText('Where it is held')).toHaveValue('exchange')
    await user.click(within(form).getByRole('button', { name: 'Add to the register' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST').body).toMatchObject({ holder: 'exchange', asset: 'USDT', amount: '635', held_at: 'Binance', request_id: 'r1' })
  })

  it('says what the server refused, such as a pasted seed phrase', async () => {
    api({
      'GET /trace/c1/assets': { body: { assets: [] } }, 'GET /trace/c1/requests': { body: { requests: [] } },
      'POST /trace/c1/assets': { status: 400, body: { detail: 'This looks like a private key or seed phrase.' } },
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Record frozen or seized funds' }))
    await user.click(screen.getByRole('button', { name: 'Add to the register' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('private key or seed phrase')
    expect(screen.getByText(/Never type a private key or seed phrase here/)).toBeInTheDocument()
  })

  it('records an outcome with its transaction, or with an order when it is not a hash', async () => {
    const calls = api({
      'GET /trace/c1/assets': { body: { assets: [ROW] } }, 'GET /trace/c1/requests': { body: { requests: [] } },
      'PATCH /assets/a1': (b) => ({ body: { ...ROW, ...b } }),
    })
    const user = userEvent.setup()
    open()
    await user.selectOptions(await screen.findByLabelText('Outcome'), 'released_to_victim')
    await user.type(screen.getByLabelText('Transaction hash or order'), 'cd'.repeat(32))
    await user.click(screen.getByRole('button', { name: 'Record the outcome' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH').body).toEqual({ status: 'released_to_victim', outcome_tx: 'cd'.repeat(32) })
  })
})

describe('deadline', () => {
  it('names the state of the court deadline', () => {
    expect(deadline({ ...ROW, days_left: -3 }).text).toBe('Court order overdue by 3 days')
    expect(deadline({ ...ROW, days_left: 0 }).text).toBe('Court order due today')
    expect(deadline({ ...ROW, days_left: 34, deadline: '2026-12-16' })).toEqual({ tone: '', text: 'Court order due 16 Dec 2026 · 34 days' })
    expect(deadline({ ...ROW, order_ref: 'Order 3/2026' }).tone).toBe('green')
    expect(deadline({ ...ROW, status: 'sold' }).text).toBe('Sold')
  })

  it('maps a freeze letter to where its money is held, and dates in India', () => {
    expect(['tether-freeze', 'bank-freeze', 'exchange-freeze', 'instant'].map(holderOf)).toEqual(['issuer', 'bank', 'exchange', 'exchange'])
    expect(todayInIndia(new Date('2026-11-12T20:00:00Z'))).toBe('2026-11-13')
  })
})

describe('the home page court-deadline card', () => {
  it('lists what is due, linked to its case', async () => {
    api({ 'GET /assets/due': { body: { count: 1, assets: [ROW] } } })
    render(<MemoryRouter><AssetDeadlines /></MemoryRouter>)
    const link = await screen.findByRole('link', { name: /635.000000 USDT/ })
    expect(link).toHaveAttribute('href', '/case/c1?tab=letters')
    expect(screen.getByRole('heading', { name: 'Court deadlines' })).toBeInTheDocument()
  })

  it('shows nothing when nothing is due or the register cannot be reached', async () => {
    api({ 'GET /assets/due': { body: { count: 0, assets: [] } } })
    const { container } = render(<MemoryRouter><AssetDeadlines /></MemoryRouter>)
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })
})
