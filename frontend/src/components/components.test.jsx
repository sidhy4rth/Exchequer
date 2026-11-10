import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import BulkIntake from './BulkIntake'
import ExportButton, { DraftLetters } from './ExportButton'
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
      'POST /verify': { body: { status: 'genuine', sealed: true, hash_ok: true, signed: true, signature_ok: true, key_fingerprint: 'abcd1234abcd1234', this_server_key: 'abcd1234abcd1234', genuine: true, extra_content: false, detail: 'Genuine and unchanged: signed by this server, and nothing was added below the signature.' } },
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
      'POST /verify': { body: { status: 'changed', sealed: true, hash_ok: false, signed: true, signature_ok: false, key_fingerprint: 'k', this_server_key: 'k', detail: 'The signature does not match.' } },
    })
    const user = userEvent.setup()
    inRouter(<Verify />)
    await user.type(screen.getByLabelText('Report text'), 'x')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByRole('status')).toHaveTextContent('This report was changed')
  })

  it('never shows text added below the seal as genuine, even with a valid signature', async () => {
    api({
      'GET /signing-key': { body: { fingerprint: 'k', public_key_pem: '', persistent: true } },
      'POST /verify': { body: { status: 'text_added', sealed: true, hash_ok: true, signed: true, signature_ok: true, genuine: false, extra_content: true, extra_lines: 1, key_fingerprint: 'k', this_server_key: 'k', detail: 'The signed part is genuine, but 1 line was added below the seal.' } },
    })
    const user = userEvent.setup()
    inRouter(<Verify />)
    await user.type(screen.getByLabelText('Report text'), 'x')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent('Text was added after signing')
    expect(status).not.toHaveTextContent('Genuine and unchanged')
    expect(status).toHaveClass('red')
  })

  const verdictFor = async (body) => {
    api({ 'GET /signing-key': { body: { fingerprint: 'k', public_key_pem: '', persistent: true } }, 'POST /verify': { body } })
    const user = userEvent.setup()
    inRouter(<Verify />)
    await user.type(screen.getByLabelText('Report text'), 'x')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    return screen.findByRole('status')
  }

  it('shows a removed signature in red', async () => {
    const s = await verdictFor({ status: 'signature_missing', sealed: true, hash_ok: true, signed: false, signature_ok: false, detail: 'Signature missing.' })
    expect(s).toHaveTextContent('Signature missing')
    expect(s).toHaveClass('red')
    expect(s).toHaveTextContent('self-consistent only')
  })

  it('never calls an unchecked key a different server', async () => {
    const s = await verdictFor({ status: 'unknown_key', sealed: true, hash_ok: true, signed: true, signature_ok: false, signature_checked: false, claimed_key: 'deadbeefdeadbeef', detail: 'Unknown key.' })
    expect(s).toHaveTextContent('Cannot be verified here')
    expect(s).not.toHaveTextContent('different server')
    expect(s).not.toHaveClass('amber')
    expect(s).toHaveTextContent('not checked')
    expect(s).toHaveTextContent('claimed key (not checked)')
  })

  it('shows a clone claiming this server as forged, in red', async () => {
    const s = await verdictFor({ status: 'forged_issuer', sealed: true, hash_ok: true, signed: true, signature_ok: false, signature_checked: false, claimed_key: 'f'.repeat(64), detail: 'Claims to be issued by this server.' })
    expect(s).toHaveTextContent('Forged')
    expect(s).toHaveClass('red')
    expect(s).toHaveTextContent('not checked')
  })

  it('shows who issued a genuine report and its full key, and whether the key is official', async () => {
    const fp = 'abcd'.repeat(16)
    const s = await verdictFor({ status: 'genuine', sealed: true, hash_ok: true, signed: true, signature_ok: true, genuine: true, issued_by: 'https://exchequer.example', key_fingerprint: fp.slice(0, 16), key_fingerprint_sha256: fp, official: true, detail: 'Genuine.' })
    expect(s).toHaveTextContent('https://exchequer.example')
    expect(s).toHaveTextContent('abcd abcd abcd abcd')
    expect(s).toHaveTextContent("in Exchequer's published list")
  })

  it('shows what the signed report says, to hold against a PDF summary page', async () => {
    const s = await verdictFor({ status: 'genuine', sealed: true, hash_ok: true, signed: true, signature_ok: true, genuine: true, detail: 'Genuine.', finding: { case_id: 'case-1', exchange: 'Binance', address: '0x' + 'a'.repeat(40), likely_arrived: 'about 9.5 of 10 ETH sent from the reported address (pro-rata)' } })
    expect(s).toHaveTextContent('What the signed report says')
    expect(s).toHaveTextContent('0x' + 'a'.repeat(40))
    expect(s).toHaveTextContent('about 9.5 of 10 ETH')
    expect(s).toHaveTextContent('not covered by the signature')
  })

  it('shows a report signed with an earlier official key as genuine', async () => {
    const earlier = await verdictFor({ status: 'genuine_earlier_key', sealed: true, hash_ok: true, signed: true, signature_ok: true, official: true, detail: 'Earlier key.' })
    expect(earlier).toHaveClass('green')
    expect(earlier).toHaveTextContent('earlier Exchequer key')
  })

  it('shows a revoked key in red', async () => {
    const s = await verdictFor({ status: 'revoked_key', sealed: true, hash_ok: true, signed: true, signature_ok: true, detail: 'Revoked.' })
    expect(s).toHaveClass('red')
  })

  it('shows an unsigned report as unverifiable, not amber', async () => {
    const s = await verdictFor({ status: 'unsigned', sealed: true, hash_ok: true, signed: false, signature_ok: false, detail: 'No signature.' })
    expect(s).toHaveTextContent('Unsigned: cannot be verified')
    expect(s).not.toHaveClass('amber')
  })

  it('treats a status it does not know as a warning, never as genuine', async () => {
    const s = await verdictFor({ status: 'something_new', sealed: true, hash_ok: true, signed: true, signature_ok: true, detail: '?' })
    expect(s).toHaveClass('red')
    expect(s).not.toHaveTextContent('Genuine')
  })

  // r1-evidence-crypto-6, round 2: a PDF is sent whole, and a doctored page 1 is named.
  const pdfFile = (size = 0) => {
    const file = new File(['%PDF-1.4 fake'], 'exchequer-case-1.pdf', { type: 'application/pdf' })
    if (size) Object.defineProperty(file, 'size', { value: size })
    return file
  }
  const uploadPdf = async (body, file = pdfFile()) => {
    const calls = api({ 'GET /signing-key': { body: { fingerprint: 'k', public_key_pem: '', persistent: true } }, 'POST /verify': { body } })
    const user = userEvent.setup()
    inRouter(<Verify />)
    await user.upload(screen.getByLabelText('Open a .txt or .pdf file'), file)
    return calls
  }
  const FINDING = { case_id: 'case-1', exchange: 'Binance', address: '0x' + 'a'.repeat(40), likely_arrived: 'about 2 of 10 ETH sent from the reported address (pro-rata)' }

  it('sends a PDF as PDF bytes, not as text', async () => {
    const calls = await uploadPdf({ status: 'genuine', sealed: true, hash_ok: true, signed: true, signature_ok: true, genuine: true, detail: 'Genuine.', finding: FINDING, pdf: { pages_match: true, problems: [] } })
    const post = await waitFor(() => { const c = calls.find((x) => x.method === 'POST'); expect(c).toBeTruthy(); return c })
    expect(post.headers['Content-Type']).toBe('application/pdf')
    expect(post.body).toBeInstanceOf(ArrayBuffer)
    const s = await screen.findByRole('status')
    expect(s).toHaveTextContent('Genuine and unchanged')
    expect(s).toHaveTextContent('Page 1 and the printed copy show what the attached report states')
    expect(screen.getByText('exchequer-case-1.pdf')).toBeInTheDocument()
  })

  it('names a page 1 that does not match the signed record, in red, with the true facts', async () => {
    await uploadPdf({ status: 'summary_differs', sealed: true, hash_ok: true, signed: true, signature_ok: true, genuine: false, detail: 'The attached report is genuine, but page 1 of this PDF does not match it.', finding: FINDING, pdf: { pages_match: false, problems: ['Page 1 does not show the address the signed report names (0xaaaa).', 'Page 1 shows an address or hash the signed report never mentions: 0x9999.'] } })
    const s = await screen.findByRole('status')
    expect(s).toHaveClass('red')
    expect(s).toHaveTextContent('Page 1 does not match the signed record')
    expect(s).not.toHaveTextContent('Genuine and unchanged')
    expect(within(s).getAllByRole('listitem')).toHaveLength(2)
    expect(s).toHaveTextContent('never mentions: 0x9999')
    expect(s).toHaveTextContent('What the signed report says')
    expect(s).toHaveTextContent('0x' + 'a'.repeat(40))
  })

  it('shows the other PDF verdicts in red', async () => {
    for (const [status, title] of [['printed_copy_differs', 'The printed pages do not match the signed record'], ['pdf_altered', 'This PDF was changed after it was issued'], ['pdf_no_report', 'No signed report in this PDF'], ['pdf_unreadable', 'This PDF cannot be read']]) {
      const differs = status === 'printed_copy_differs' || status === 'pdf_altered'
      await uploadPdf({ status, genuine: false, sealed: false, detail: 'x', pdf: { pages_match: differs ? false : null, problems: differs ? ['The printed copy (Part 2) differs from the attached file.'] : [] } })
      const s = await screen.findByRole('status')
      expect(s).toHaveClass('red')
      expect(s).toHaveTextContent(title)
      cleanup()
    }
  })

  it('refuses a file over the size limit without sending it', async () => {
    const calls = await uploadPdf({ status: 'genuine' }, pdfFile(2_000_001))
    expect(await screen.findByText(/larger than any Exchequer report/)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')).toBeUndefined()
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

  const alertRow = (i, kind, read = false) => ({ alert_id: `a${i}`, kind, value: 1, asset: 'ETH', counterparty: '0x' + String(i).padStart(40, '0'), counterparty_label: kind === 'exchange' ? 'Binance 14' : '', tx_time: 1700000000 + i, tx_url: '', tx_hash: `0x${i}`, read })
  const listing = (alerts) => api({
    'GET /watches': { body: { count: 1, watches: [{ watch_id: 'w1', address: '0x' + '7'.repeat(40), chain: 'ethereum', asset: 'ETH', last_checked_at: null, unread_alerts: alerts.length }] } },
    'GET /alerts': { body: { count: alerts.length, alerts } },
  })

  it('pins an unread exchange alert above 30 newer moved alerts', async () => {
    listing([...Array.from({ length: 40 }, (_, i) => alertRow(i + 1, 'moved')), alertRow(99, 'exchange')])
    inRouter(<Watchlist />)
    const rows = await screen.findAllByText(/into an exchange|^moved$/)
    expect(rows[0]).toHaveTextContent('into an exchange')
    expect(screen.getByText('Binance 14')).toBeInTheDocument()
  })

  it('does not pin dust sent to an exchange: only 30 of it show, after the pinned cash-out', async () => {
    const dust = Array.from({ length: 40 }, (_, i) => ({ ...alertRow(i + 1, 'exchange'), value: 0.000001, dust: true }))
    listing([{ ...alertRow(99, 'exchange'), value: 25 }, ...dust])
    inRouter(<Watchlist />)
    const rows = await screen.findAllByText(/into an exchange/)
    expect(rows).toHaveLength(31)
    expect(screen.getByRole('button', { name: 'Show all 41' })).toBeInTheDocument()
    expect(screen.getAllByText(/· dust/)).toHaveLength(30)
  })

  it('offers Show all past 30 alerts', async () => {
    listing(Array.from({ length: 45 }, (_, i) => alertRow(i + 1, 'moved')))
    const user = userEvent.setup()
    inRouter(<Watchlist />)
    await user.click(await screen.findByRole('button', { name: 'Show all 45' }))
    expect(screen.getAllByText('moved')).toHaveLength(45)
  })

  it('names a "more movements" notice for what it is', async () => {
    listing([{ ...alertRow(1, 'more'), message: 'Not everything since the last check was read in one go.' }])
    inRouter(<Watchlist />)
    expect(await screen.findByText('more movements')).toBeInTheDocument()
    expect(screen.getByText(/Not everything since the last check/)).toBeInTheDocument()
  })

  it("removes a watch's webhook and keeps the watch", async () => {
    let watch = { watch_id: 'w1', address: '0x' + '7'.repeat(40), chain: 'ethereum', asset: 'ETH', last_checked_at: null, unread_alerts: 0, webhook: 'https://hooks.slack.com/…' }
    const calls = api({
      'GET /watches': () => ({ body: { count: 1, watches: [watch] } }),
      'GET /alerts': { body: { count: 0, alerts: [] } },
      'DELETE /watches/w1/webhook': () => { watch = { ...watch, webhook: null }; return { body: watch } },
    })
    const user = userEvent.setup()
    inRouter(<Watchlist />)
    expect(await screen.findByText(/posts to hooks.slack.com/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove webhook' }))
    await waitFor(() => expect(screen.queryByText(/posts to hooks.slack.com/)).not.toBeInTheDocument())
    expect(calls.some((c) => c.method === 'DELETE' && c.path === '/watches/w1/webhook')).toBe(true)
    expect(screen.getByRole('button', { name: 'Check now' })).toBeInTheDocument()
  })

  it('says when a webhook must be entered again', async () => {
    api({
      'GET /watches': { body: { count: 1, watches: [{ watch_id: 'w1', address: '0x' + '7'.repeat(40), chain: 'ethereum', asset: 'ETH', last_checked_at: null, unread_alerts: 0, webhook: null, webhook_unreadable: true }] } },
      'GET /alerts': { body: { count: 0, alerts: [] } },
    })
    inRouter(<Watchlist />)
    expect(await screen.findByText(/webhook needs re-entering/)).toBeInTheDocument()
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

  it('suggests the urgent freeze letters first and logs one as its own kind', async () => {
    let items = []
    const calls = api({
      'GET /trace/case-1/requests': () => ({ body: { count: items.length, requests: items } }),
      'GET /trace/case-1/letters': { body: { letters: LETTERS } },
      'POST /requests': (body) => {
        items = [{ request_id: 'r1', ...body, status: 'drafted', history: [], reference: '', notes: '' }]
        return { status: 201, body: items[0] }
      },
    })
    const user = userEvent.setup()
    inRouter(<RequestsPanel result={{ ...CASE, exchange: 'Bin\u200bance' }} />)
    await screen.findByRole('button', { name: 'Log a request to Tether' })
    expect(screen.getAllByRole('button', { name: /^Log (a|an urgent freeze) request to/ }).map((b) => b.textContent)).toEqual([
      'Log an urgent freeze request to Binance', 'Log an urgent freeze request to Tether',
      'Log a request to Binance', 'Log a request to Tether',
    ])
    await user.click(screen.getByRole('button', { name: 'Log an urgent freeze request to Binance' }))
    expect(calls.find((c) => c.method === 'POST').body).toMatchObject({ recipient: 'Binance', kind: 'exchange-freeze', address: CASE.exchange_address })
    expect(await screen.findByText('Urgent freeze')).toBeInTheDocument()
    // Logged once, the urgent one to Binance is no longer suggested; the information letter still is.
    expect(screen.queryByRole('button', { name: 'Log an urgent freeze request to Binance' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log a request to Binance' })).toBeInTheDocument()
  })

  it('names an instant exchanger the trace passed beside the exchange, and logs it under its own wallet', async () => {
    const FF = '0x' + 'f'.repeat(40)
    let items = [{ request_id: 'r0', case_id: 'case-1', recipient: 'Binance', kind: 'exchange-freeze', status: 'sent', history: [], reference: '', notes: '' }]
    const calls = api({
      'GET /trace/case-1/requests': () => ({ body: { count: items.length, requests: items } }),
      'GET /trace/case-1/letters': { body: { letters: [
        { to: 'exchange-freeze', title: 'Urgent freeze request to Binance' },
        { to: 'instant-freeze', title: 'Urgent freeze request to Fixed\u200bFloat', address: FF },
        { to: 'exchange', title: 'Request to Binance' },
        { to: 'instant', title: 'Request to FixedFloat', address: FF },
      ] } },
      'POST /requests': (body) => {
        items = [...items, { request_id: `r${items.length}`, ...body, status: 'drafted', history: [], reference: '', notes: '' }]
        return { status: 201, body: items.at(-1) }
      },
    })
    const user = userEvent.setup()
    inRouter(<RequestsPanel result={CASE} />)
    await screen.findByRole('button', { name: 'Log a request to Binance' })
    // Binance's urgent letter is logged already: FixedFloat's is still offered, under its own name.
    expect(screen.getAllByRole('button', { name: /^Log (a|an urgent freeze) request to/ }).map((b) => b.textContent)).toEqual([
      'Log an urgent freeze request to FixedFloat', 'Log a request to Binance', 'Log a request to FixedFloat',
    ])
    await user.click(screen.getByRole('button', { name: 'Log an urgent freeze request to FixedFloat' }))
    expect(calls.find((c) => c.method === 'POST').body).toMatchObject({ recipient: 'FixedFloat', kind: 'instant-freeze', address: FF })
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Log an urgent freeze request to FixedFloat' })).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Log a request to FixedFloat' })).toBeInTheDocument()
  })

  it('offers an urgent letter only the statuses its sign-off allows, and shows the unit\'s rows on the Letters tab only', async () => {
    const row = (over) => ({ case_id: 'case-1', recipient: 'Binance', history: [], reference: '', notes: '', mine: true, ...over })
    api({
      'GET /trace/case-1/requests': { body: { count: 4, requests: [
        row({ request_id: 'r1', kind: 'exchange-freeze', status: 'awaiting_signoff', needs_signoff: true, signoff: null }),
        row({ request_id: 'r2', kind: 'tether-freeze', recipient: 'Tether', status: 'ready', needs_signoff: true, signoff: { by: 'Bina Iyer', at: '2026-11-10T09:00:00+00:00' } }),
        row({ request_id: 'r3', kind: 'exchange', status: 'sent', needs_signoff: false }),
        row({ request_id: 'r4', kind: 'exchange-freeze', recipient: 'Elsewhere', status: 'awaiting_signoff', needs_signoff: true, mine: false }),
      ] } },
      'GET /trace/case-1/letters': { body: { letters: [] } },
    })
    inRouter(<RequestsPanel result={CASE} />)
    await screen.findByText('Tether', { selector: '.nm' })
    expect(screen.queryByText('Elsewhere', { selector: '.nm' })).not.toBeInTheDocument()
    const [waiting, ready, info] = screen.getAllByLabelText('Status')
    const options = (select) => [...select.options].map((o) => o.value)
    expect(options(waiting)).toEqual(['drafted', 'awaiting_signoff', 'closed'])
    expect(options(ready)).toEqual(['ready', 'sent', 'acknowledged', 'frozen', 'declined', 'closed'])
    expect(options(info)).toEqual(['drafted', 'sent', 'acknowledged', 'frozen', 'declined', 'closed'])
    expect(screen.getByText('Awaiting a second officer', { selector: '.pill' })).toBeInTheDocument()
    expect(screen.getByText('Signed off · ready to send', { selector: '.pill' })).toBeInTheDocument()
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
    expect(await screen.findByText(/Line 3: 'nope' is not a valid/)).toBeInTheDocument()
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
    await user.paste('0x' + 'a'.repeat(40) + '\n')
    await user.click(screen.getByRole('button', { name: 'Run batch of 1' }))
    expect(await screen.findByText('batch page')).toBeInTheDocument()
  })
})

// The information letters first, as an older server listed them: the menu still puts the urgent ones first.
const LETTERS = [
  { to: 'exchange', title: 'Request to Binance' }, { to: 'tether', title: 'Request to Tether' },
  { to: 'exchange-freeze', title: 'Urgent freeze request to Bin\u200bance' }, { to: 'tether-freeze', title: 'Urgent freeze request to Tether' },
]

describe('Export menu', () => {
  it('offers the PDF and both graph formats', async () => {
    api({ 'GET /trace/case-1/letters': { body: { letters: [{ to: 'exchange', title: 'Request to Binance' }] } } })
    const user = userEvent.setup()
    inRouter(<ExportButton caseId="case-1" address={CASE.address} />)
    await user.click(screen.getByRole('button', { name: /Export/ }))
    const menu = screen.getByRole('menu')
    for (const name of [/Report \(\.pdf\)/, /Report \(\.txt\)/, /Data \(\.json\)/, /Graph \(\.graphml\)/, /Graph \(\.csv\)/]) {
      expect(within(menu).getByRole('menuitem', { name })).toBeInTheDocument()
    }
  })

  // The letters moved to the case's Letters tab (DraftLetters).
  it('leaves the case\'s draft letters to the Letters tab, which offers each', async () => {
    api({ 'GET /trace/case-1/letters': { body: { letters: [{ to: 'exchange', title: 'Request to Binance' }] } } })
    inRouter(<DraftLetters caseId="case-1" />)
    expect(await screen.findByRole('button', { name: /Request to Binance/ })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Draft letters · 1' })).toBeInTheDocument()
  })

  it('lists the urgent freeze letters first, named in plain text', async () => {
    api({ 'GET /trace/case-1/letters': { body: { letters: LETTERS } } })
    inRouter(<DraftLetters caseId="case-1" />)
    const card = await screen.findByRole('region', { name: 'Draft letters · 4' })
    const letters = within(card).getAllByRole('button', { name: /request to/i }).map((b) => b.textContent)
    expect(letters.map((t) => t.split(/(?<=Binance|Tether)/)[0])).toEqual([
      'Urgent freeze request to Binance', 'Urgent freeze request to Tether', 'Request to Binance', 'Request to Tether',
    ])
    expect(letters[0]).toContain('hold the funds now')
    expect(letters[2]).not.toContain('hold the funds now')
  })
})

describe('Exchange alerts', () => {
  it('log a freeze request against the case in one click', async () => {
    const calls = api({
      'GET /watches': { body: { count: 1, watches: [{ watch_id: 'w1', address: '0x' + '7'.repeat(40), chain: 'ethereum', asset: 'ETH', case_id: 'case-1', unread_alerts: 1 }] } },
      'GET /alerts': { body: { count: 1, alerts: [{ alert_id: 'a1', kind: 'exchange', exchange: 'OKX', case_id: 'case-1', value: 2, asset: 'ETH', counterparty: '0xdep', counterparty_label: 'probable OKX deposit address (inferred)', tx_time: 1700000000, tx_url: '', tx_hash: '0x1', read: false }] } },
      'POST /requests': { status: 201, body: { request_id: 'r1' } },
    })
    const user = userEvent.setup()
    inRouter(<Watchlist />)
    await user.click(await screen.findByRole('button', { name: 'Log freeze request' }))
    expect(await screen.findByRole('link', { name: 'request logged' })).toHaveAttribute('href', '/case/case-1')
    expect(calls.find((c) => c.method === 'POST').body).toEqual({ case_id: 'case-1', recipient: 'OKX', kind: 'exchange', address: '0xdep', asset: 'ETH' })
  })
})

describe('the front door figures (R14)', () => {
  it('counts exchange wallets apart from customer deposit addresses', async () => {
    const { coverageFromChains } = await import('./ExchangeGlobe')
    const figures = coverageFromChains({
      ethereum: { exchange_labels: 25038, exchange_wallets: 975, deposit_addresses: 24063, risk_labels: { sanctioned: 127, mixer: 0, frozen: 2828, stolen: 11 } },
      tron: { exchange_labels: 41, exchange_wallets: 40, deposit_addresses: 1, risk_labels: { sanctioned: 915, frozen: 6759 } },
    })
    expect(figures).toEqual({ wallets: 1015, deposits: 24064, sanctioned: 1042, frozen: 9587, stolen: 11, mixer: 0, poisoning: 0, flagged: 10640, chains: ['ethereum', 'tron'] })
  })

  it('reads nothing when the backend has nothing', async () => {
    const { coverageFromChains } = await import('./ExchangeGlobe')
    expect(coverageFromChains(undefined)).toEqual({ wallets: 0, deposits: 0, sanctioned: 0, frozen: 0, stolen: 0, mixer: 0, poisoning: 0, flagged: 0, chains: [] })
  })

  it('adds every flagged address, the label store included, into one headline figure', async () => {
    const { coverageFromChains } = await import('./ExchangeGlobe')
    const figures = coverageFromChains({ tron: { risk_labels: { sanctioned: 915, poisoning: 5910444, scam: 664 } }, ethereum: { risk_labels: { poisoning: 3951478, gambling: 19681 } } })
    expect(figures.flagged).toBe(9883182)
    expect(figures.poisoning).toBe(9861922)
  })

  it('counts seizure orders with the government listings (r1-labels-data-12)', async () => {
    const { coverageFromChains } = await import('./ExchangeGlobe')
    expect(coverageFromChains({ tron: { risk_labels: { sanctioned: 49, seized: 488 } } }).sanctioned).toBe(537)
  })
})

describe('what the watchlist says about the watcher (R30)', () => {
  const minutesAgo = (m) => new Date(Date.now() - m * 60_000).toISOString()
  const oneWatch = (watcher) => api({
    'GET /watches': { body: { count: 1, watcher, watches: [{ watch_id: 'w1', address: '0x' + '7'.repeat(40), chain: 'ethereum', asset: 'ETH', note: '', last_checked_at: watcher.last_check_at, unread_alerts: 0 }] } },
    'GET /alerts': { body: { count: 0, alerts: [] } },
  })

  it('says when automatic checks are off', async () => {
    oneWatch({ enabled: false, interval_seconds: 600, last_check_at: null, stale: false })
    inRouter(<Watchlist />)
    expect(await screen.findByText(/automatic checks are off on this site/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says when the last check was, and stays calm when it was recent', async () => {
    oneWatch({ enabled: true, interval_seconds: 600, last_check_at: minutesAgo(4), stale: false })
    inRouter(<Watchlist />)
    expect(await screen.findByText(/about every 10 min · last check of your watches 4 min ago/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('promises no schedule when the watch service cannot be reached', async () => {
    api({
      'GET /watches': { status: 500, body: { detail: 'down' } },
      'GET /alerts': { body: { count: 1, alerts: [{ alert_id: 'a1', kind: 'moved', value: 1, asset: 'ETH', counterparty: '0x' + '9'.repeat(40), counterparty_label: '', tx_time: 1700000000, tx_url: '', tx_hash: '0x1', read: false }] } },
    })
    const { container } = inRouter(<Watchlist />)
    expect(await screen.findByText(/could not reach the watch service/)).toBeInTheDocument()
    expect(container).not.toHaveTextContent(/checked automatically|about every/)
  })

  it('warns when no check has run for too long', async () => {
    oneWatch({ enabled: true, interval_seconds: 600, last_check_at: minutesAgo(180), stale: true })
    inRouter(<Watchlist />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/last automatic check was 3 h ago.*press Check now/)
  })
})

describe('the watch panel when automatic checks are off (R30)', () => {
  const result = { case_id: 'c1', address: '0x' + '1'.repeat(40), chain: 'ethereum', asset: 'ETH', direction: 'outgoing' }

  it('says a watch will be checked only by hand', async () => {
    api({ 'GET /watches': { body: { count: 0, watches: [], watcher: { enabled: false } } } })
    inRouter(<WatchPanel result={result} />)
    expect(await screen.findByText(/Automatic checks are off on this site/)).toBeInTheDocument()
  })

  it('says nothing of the kind when they are on', async () => {
    api({ 'GET /watches': { body: { count: 0, watches: [], watcher: { enabled: true } } } })
    inRouter(<WatchPanel result={result} />)
    await screen.findByText('Watch for movement')
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByText(/Automatic checks are off/)).not.toBeInTheDocument()
  })

  it('promises no schedule when checks run only on Check now', async () => {
    api({ 'GET /watches': { body: { count: 0, watches: [], watcher: { enabled: false, interval_seconds: 600 } } } })
    const { container } = inRouter(<WatchPanel result={result} />)
    await screen.findByText(/Automatic checks are off on this site/)
    expect(container).not.toHaveTextContent(/every ten minutes|about every/)
    expect(container).toHaveTextContent(/Alerts appear on the home page/)
  })

  it('gives the real interval when automatic checks are on', async () => {
    api({ 'GET /watches': { body: { count: 0, watches: [], watcher: { enabled: true, interval_seconds: 300 } } } })
    inRouter(<WatchPanel result={result} />)
    expect(await screen.findByText(/Checked automatically about every 5 min/)).toBeInTheDocument()
  })

  it('claims no schedule when the watch service cannot be reached', async () => {
    api({ 'GET /watches': { status: 500, body: { detail: 'down' } } })
    const { container } = inRouter(<WatchPanel result={result} />)
    expect(await screen.findByText(/Could not reach the watch service/)).toBeInTheDocument()
    expect(container).not.toHaveTextContent(/every ten minutes|about every/)
  })
})
