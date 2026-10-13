import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import BulkIntake from './BulkIntake'
import ExportButton from './ExportButton'
import RequestsPanel from './RequestsPanel'
import WatchPanel from './WatchPanel'
import Watchlist from './Watchlist'
import Verify from '../routes/Verify'

/**
 * A fetch stub keyed by "METHOD /path". Handlers get the parsed JSON body (or
 * text) and return { status, body }. Every call is recorded.
 */
function api(routes) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const path = String(url).replace(/^\/api/, '').split('?')[0]
    let body = init.body
    try { body = JSON.parse(body) } catch { /* text */ }
    calls.push({ method, path, body, headers: init.headers })
    const handler = routes[`${method} ${path}`]
    if (!handler) return new Response(JSON.stringify({ detail: 'not stubbed' }), { status: 404 })
    const { status = 200, body: out } = typeof handler === 'function' ? handler(body, calls) : handler
    return new Response(typeof out === 'string' ? out : JSON.stringify(out), { status })
  }))
  return calls
}

const inRouter = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>)

const CASE = {
  case_id: 'case-1', address: '0x' + '1'.repeat(40), chain: 'ethereum', asset: 'ETH', direction: 'outgoing',
  exchange: 'Binance', exchange_address: '0x' + 'd'.repeat(40), attribution_inferred: true,
}

describe('Verify page', () => {
  it('sends the pasted report and shows the verdict', async () => {
    const calls = api({
      'GET /signing-key': { body: { algorithm: 'Ed25519', fingerprint: 'abcd1234abcd1234', public_key_pem: 'PEM', persistent: true } },
      'POST /verify': { body: { sealed: true, hash_ok: true, signed: true, signature_ok: true, key_fingerprint: 'abcd1234abcd1234', this_server_key: 'abcd1234abcd1234', detail: 'Genuine and unchanged: signed by this server, every byte as issued.' } },
    })
    const user = userEvent.setup()
    inRouter(<Verify />)
    await user.type(screen.getByLabelText('Report text'), 'EXCHEQUER REPORT')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Genuine and unchanged')
    expect(calls.find((c) => c.method === 'POST').body).toBe('EXCHEQUER REPORT')
    expect(screen.getByText(/abcd1234abcd1234/, { selector: '.note .mono' })).toBeInTheDocument()
  })

  it('names an edited report as changed', async () => {
    api({
      'GET /signing-key': { body: { fingerprint: 'k', public_key_pem: '', persistent: true } },
      'POST /verify': { body: { sealed: true, hash_ok: false, signed: true, signature_ok: false, key_fingerprint: 'k', this_server_key: 'k', detail: 'The signature does not match.' } },
    })
    const user = userEvent.setup()
    inRouter(<Verify />)
    await user.type(screen.getByLabelText('Report text'), 'x')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByRole('status')).toHaveTextContent('This report was changed')
  })
})

describe('Watch panel', () => {
  it('offers the reported wallet and the inferred deposit address, and watches one', async () => {
    let watches = []
    const calls = api({
      'GET /watches': () => ({ body: { count: watches.length, watches } }),
      'POST /watches': (body) => {
        watches = [{ watch_id: 'w1', address: body.address, chain: body.chain, asset: body.asset, unread_alerts: 0, last_checked_at: null }]
        return { status: 201, body: watches[0] }
      },
    })
    const user = userEvent.setup()
    inRouter(<WatchPanel result={CASE} />)
    expect(await screen.findByText('the probable Binance deposit address')).toBeInTheDocument()
    const buttons = screen.getAllByRole('button', { name: 'Watch' })
    expect(buttons).toHaveLength(2)
    await user.click(buttons[1])
    expect(await screen.findByRole('button', { name: 'Stop' })).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST')
    expect(post.body).toMatchObject({ address: CASE.exchange_address, chain: 'ethereum', asset: 'ETH', case_id: 'case-1' })
    expect(post.headers['X-Exchequer-Owner']).toMatch(/^[A-Za-z0-9_-]{43}$/)
  })

  it('never offers a labelled hot wallet', async () => {
    api({ 'GET /watches': { body: { count: 0, watches: [] } } })
    inRouter(<WatchPanel result={{ ...CASE, attribution_inferred: false }} />)
    await screen.findByText('the reported wallet')
    expect(screen.getAllByRole('button', { name: 'Watch' })).toHaveLength(1)
  })
})

describe('Watchlist on the home page', () => {
  it('lists watches and alerts, and marks them read', async () => {
    let alerts = [
      { alert_id: 'a1', kind: 'exchange', value: 3.123456789, asset: 'ETH', counterparty: '0xbin', counterparty_label: 'Binance 14', tx_time: 1700000000, tx_url: 'https://etherscan.io/tx/0x1', tx_hash: '0x1', read: false },
      { alert_id: 'a2', kind: 'moved', value: 1, asset: 'ETH', counterparty: '0x' + '9'.repeat(40), counterparty_label: '', tx_time: 1700000100, tx_url: '', tx_hash: '0x2', read: true },
    ]
    const calls = api({
      'GET /watches': { body: { count: 1, running: true, watches: [{ watch_id: 'w1', address: '0x' + '7'.repeat(40), chain: 'ethereum', asset: 'ETH', note: 'the reported wallet', last_checked_at: null, unread_alerts: 1 }] } },
      'GET /alerts': () => ({ body: { count: alerts.length, alerts } }),
      'POST /alerts/read': () => { alerts = alerts.map((a) => ({ ...a, read: true })); return { body: { marked: 1 } } },
    })
    const user = userEvent.setup()
    inRouter(<Watchlist />)
    expect(await screen.findByText('1 new')).toBeInTheDocument()
    expect(screen.getByText('into an exchange')).toBeInTheDocument()
    expect(screen.getByText(/3\.123457 ETH/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'transaction' })).toHaveAttribute('href', 'https://etherscan.io/tx/0x1')
    await user.click(screen.getByRole('button', { name: 'Mark all read' }))
    await waitFor(() => expect(screen.queryByText('1 new')).not.toBeInTheDocument())
    expect(calls.some((c) => c.method === 'POST' && c.path === '/alerts/read')).toBe(true)
  })

  it('renders nothing when this browser watches nothing', async () => {
    api({ 'GET /watches': { body: { count: 0, watches: [] } }, 'GET /alerts': { body: { count: 0, alerts: [] } } })
    const { container } = inRouter(<Watchlist />)
    await new Promise((r) => setTimeout(r, 20))
    expect(container).toBeEmptyDOMElement()
  })
})

describe('Freeze requests panel', () => {
  it('suggests the recipients the case supports and logs one', async () => {
    let items = []
    const calls = api({
      'GET /trace/case-1/requests': () => ({ body: { count: items.length, requests: items } }),
      'GET /trace/case-1/letters': { body: { letters: [{ to: 'exchange', title: 'Request to Binance' }, { to: 'tether', title: 'Request to Tether' }] } },
      'POST /requests': (body) => {
        items = [{ request_id: 'r1', ...body, status: 'drafted', history: [{ at: '2026-10-13T00:00:00+00:00', status: 'drafted' }], reference: '', notes: '' }]
        return { status: 201, body: items[0] }
      },
      'PATCH /requests/r1': (body) => { items = [{ ...items[0], ...body }]; return { body: items[0] } },
    })
    const user = userEvent.setup()
    inRouter(<RequestsPanel result={CASE} />)
    await user.click(await screen.findByRole('button', { name: 'Log a request to Binance' }))
    expect(await screen.findByText('Binance', { selector: '.nm' })).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST').body).toMatchObject({ case_id: 'case-1', recipient: 'Binance', kind: 'exchange', address: CASE.exchange_address })
    // Logged once, Binance is no longer suggested; Tether still is.
    expect(screen.queryByRole('button', { name: 'Log a request to Binance' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log a request to Tether' })).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Status'), 'sent')
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH' && c.body.status === 'sent')).toBe(true))
  })
})

describe('Bulk intake', () => {
  it('counts the rows it read and shows row errors from the server', async () => {
    api({
      'GET /batches': { body: { count: 0, batches: [] } },
      'POST /batches': { status: 400, body: { detail: '1 row cannot be traced as written.', row_errors: [{ row: 2, error: "'nope' is not a valid Ethereum Mainnet address." }] } },
    })
    const user = userEvent.setup()
    inRouter(<BulkIntake />)
    await user.click(screen.getByText('Bulk intake'))
    const box = screen.getByLabelText('Complaints CSV')
    await user.click(box)
    await user.paste('reference,address\nC-1,0xabc\nC-2,nope\n')
    await user.click(screen.getByRole('button', { name: 'Run batch of 2' }))
    expect(await screen.findByText(/Row 2: 'nope' is not a valid/)).toBeInTheDocument()
  })

  it('opens the batch page once the batch starts', async () => {
    api({ 'GET /batches': { body: { count: 0, batches: [] } }, 'POST /batches': { status: 202, body: { batch_id: 'b1' } } })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<BulkIntake />} />
          <Route path="/batch/:id" element={<p>batch page</p>} />
        </Routes>
      </MemoryRouter>,
    )
    await user.click(screen.getByText('Bulk intake'))
    await user.click(screen.getByLabelText('Complaints CSV'))
    await user.paste('0xabc\n')
    await user.click(screen.getByRole('button', { name: 'Run batch of 1' }))
    expect(await screen.findByText('batch page')).toBeInTheDocument()
  })
})

describe('Export menu', () => {
  it('offers the PDF, both graph formats and the case\'s draft letters', async () => {
    api({ 'GET /trace/case-1/letters': { body: { letters: [{ to: 'exchange', title: 'Request to Binance' }] } } })
    const user = userEvent.setup()
    inRouter(<ExportButton caseId="case-1" address={CASE.address} />)
    await user.click(screen.getByRole('button', { name: /Export/ }))
    const menu = screen.getByRole('menu')
    for (const name of [/Report \(\.pdf\)/, /Report \(\.txt\)/, /Data \(\.json\)/, /Graph \(\.graphml\)/, /Graph \(\.csv\)/]) {
      expect(within(menu).getByRole('menuitem', { name })).toBeInTheDocument()
    }
    expect(await within(menu).findByRole('menuitem', { name: /Request to Binance/ })).toBeInTheDocument()
  })
})
