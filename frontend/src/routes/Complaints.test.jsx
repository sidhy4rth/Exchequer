import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Complaints from './Complaints'
import { stubFetch } from '../test/setup'

// The Complaints page (/complaints): the officers' review queue of what
// citizens sent from their own site (backend/app/routes/complaints.py). The
// list masks the NCRP number; a complaint opens with its text, payments, a
// status control and the message box, whose words are the only thing that
// goes back to the citizen. A trace starts only from the officer's click.

const WALLET = 'TJ' + 'a'.repeat(32)
const HASH = 'ab'.repeat(32)
const ZWSP = '​'

const QUEUE = {
  count: 2, total: 2,
  complaints: [
    // 20:00 UTC is 01:30 the next morning in India.
    { reference: 'EXQ-NEWER222', received_at: '2026-11-04T20:00:00+00:00', ncrp: '••••0123', status: 'investigating',
      payments: 2, totals: [{ token: 'ETH', amount: '0.5' }, { token: 'USDT', amount: '1200' }], in_other_complaints: true, in_stored_case: false },
    { reference: 'EXQ-OLDER111', received_at: '2026-11-01T05:00:00+00:00', ncrp: '••••9876', status: 'received',
      payments: 0, totals: [], in_other_complaints: false, in_stored_case: false },
  ],
}

const ONE = {
  reference: 'EXQ-NEWER222', received_at: '2026-11-04T20:00:00+00:00', updated_at: '2026-11-04T20:00:00+00:00',
  status: 'investigating', ncrp: '31234567890123', in_other_complaints: true, in_stored_case: false, case_id: null,
  details: { name: `A ${ZWSP}Citizen`, mobile: '9876543210', started: '2026-10-30', app: 'QuickTrade', link: '', contacts: '', upi: '',
    story: 'They promised returns.\nThen they asked for a fee.' },
  payments: [{ hash: HASH, amount: '1200', token: 'USDT', network: 'Tron (TRC20)', paid_at: '2026-11-01T10:30', wallet: WALLET }],
  messages: [{ from: 'citizen', body: 'Is there any news?', at: '2026-11-05T04:00:00+00:00' }],
}

// What this site traces (GET /chains): Tron and Ethereum on, Polygon off.
const chain = (key, name, ready) => ({ key, name, ready, address_family: key === 'tron' ? 'tron' : 'evm', assets: [] })
const CHAINS = { status: 'ok', chains: { tron: chain('tron', 'Tron', true), ethereum: chain('ethereum', 'Ethereum', true), polygon: chain('polygon', 'Polygon', false) } }

function Landed() {
  const { pathname, search, state } = useLocation()
  return <p data-testid="landed" data-prefill={JSON.stringify(state?.prefill ?? null)}>{pathname + search}</p>
}

function open(path, routes = {}) {
  const fetch = stubFetch({ '/complaints': { body: QUEUE }, '/complaints/EXQ-NEWER222': { body: ONE }, '/chains': { body: CHAINS }, ...routes })
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/complaints" element={<Complaints />} />
        <Route path="/complaints/:reference" element={<Complaints />} />
        <Route path="/trace/new" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
  return fetch
}

const screenOf = (width) => vi.stubGlobal('matchMedia', (query) => ({
  matches: Number(/max-width:\s*(\d+)px/.exec(query)?.[1] ?? -1) >= width, addEventListener: () => {}, removeEventListener: () => {},
}))

describe('the complaints queue', () => {
  it('lists each complaint with its reference, IST date, masked NCRP, payments, total and status', async () => {
    screenOf(1440)
    open('/complaints')
    const table = await screen.findByRole('table', { name: 'Complaints' })
    const row = within(table).getByRole('link', { name: 'EXQ-NEWER222' }).closest('tr')
    expect(row).toHaveTextContent('5 Nov 2026')
    expect(row).toHaveTextContent('••••0123')
    expect(row).toHaveTextContent('0.5 ETH + 1,200 USDT')
    expect(row).toHaveTextContent('Under investigation')
    expect(within(row).getByText('Wallet also in other complaints')).toBeInTheDocument()
    const older = within(table).getByRole('link', { name: 'EXQ-OLDER111' }).closest('tr')
    expect(older).toHaveTextContent('Received')
    expect(older).not.toHaveTextContent('other complaints')
  })

  it('shows a card per complaint on a phone', async () => {
    screenOf(390)
    open('/complaints')
    const list = await screen.findByRole('list', { name: 'Complaints' })
    expect(within(list).getAllByRole('link').map((a) => a.textContent)).toEqual([
      expect.stringContaining('EXQ-NEWER222'), expect.stringContaining('EXQ-OLDER111')])
  })

  it('asks the backend for one status at a time', async () => {
    screenOf(1440)
    const user = userEvent.setup()
    const fetch = open('/complaints')
    await screen.findByRole('table', { name: 'Complaints' })
    await user.click(screen.getByRole('button', { name: 'Under investigation' }))
    expect(screen.getByRole('button', { name: 'Under investigation' })).toHaveAttribute('aria-pressed', 'true')
    expect(fetch.mock.calls.map(([url]) => String(url)).at(-1)).toMatch(/\/complaints\?limit=100&status=investigating$/)
  })

  it('says how many complaints there are and loads the older ones, never dropping them quietly', async () => {
    screenOf(1440)
    const user = userEvent.setup()
    const older = { reference: 'EXQ-OLDEST33', received_at: '2026-10-20T05:00:00+00:00', ncrp: '••••4444', status: 'received',
      payments: 0, totals: [], in_other_complaints: false, in_stored_case: false }
    const fetch = open('/complaints', { '/complaints': (url) => ({
      body: /offset=2/.test(url) ? { count: 1, total: 3, complaints: [older] } : { ...QUEUE, total: 3 } }) })
    await screen.findByRole('table', { name: 'Complaints' })
    expect(screen.getByText('Showing the newest 2 of 3 complaints.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Show older complaints' }))
    expect(await screen.findByRole('link', { name: 'EXQ-OLDEST33' })).toBeInTheDocument()
    expect(fetch.mock.calls.map(([url]) => String(url)).at(-1)).toMatch(/\/complaints\?limit=100&offset=2$/)
    expect(screen.getAllByRole('link').map((a) => a.textContent)).toEqual(['EXQ-NEWER222', 'EXQ-OLDER111', 'EXQ-OLDEST33'])
    expect(screen.queryByRole('button', { name: 'Show older complaints' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Showing the newest/)).not.toBeInTheDocument()
  })

  // An older page asked for under one filter must not land in another.
  async function heldOlder(order) {
    screenOf(1440)
    const user = userEvent.setup()
    const stray = { reference: 'EXQ-STRAY999', received_at: '2026-10-20T05:00:00+00:00', ncrp: '••••4444', status: 'received',
      payments: 0, totals: [], in_other_complaints: false, in_stored_case: false }
    let release, ask
    const held = new Promise((done) => { release = done })
    const asked = new Promise((done) => { ask = done })
    const fetch = open('/complaints', { '/complaints': (url) => ({
      body: /status=closed/.test(url) ? { count: 0, total: 0, complaints: [] } : { ...QUEUE, total: 3 } }) })
    const answer = fetch.getMockImplementation()
    fetch.mockImplementation(async (url) => {
      if (/offset=2/.test(url)) { ask(); await held; return new Response(JSON.stringify({ count: 1, total: 3, complaints: [stray] })) }
      if (order === 'older first' && /status=closed/.test(url)) await asked.then(() => held).then(() => new Promise((r) => setTimeout(r, 20)))
      return answer(url)
    })
    await screen.findByRole('table', { name: 'Complaints' })
    await user.click(screen.getByRole('button', { name: 'Show older complaints' }))
    await asked
    await user.click(screen.getByRole('button', { name: 'Closed' }))
    if (order === 'filter first') await screen.findByText('No complaint is marked closed.')
    release()
    expect(await screen.findByText('No complaint is marked closed.')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.getByText('No complaint is marked closed.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'EXQ-STRAY999' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Showing the newest/)).not.toBeInTheDocument()
  }

  it('drops an older page that comes back after the filter changed and its list arrived', () => heldOlder('filter first'))
  it('drops an older page that comes back while the new filter is still being read', () => heldOlder('older first'))

  it('says so when the queue cannot be read', async () => {
    open('/complaints', { '/complaints': { status: 403, body: { detail: 'The complaints queue opens only to signed-in officers.' } } })
    expect(await screen.findByText('The complaints queue opens only to signed-in officers.')).toBeInTheDocument()
  })
})

describe('a complaint', () => {
  it('shows what the citizen wrote, the payments and the thread', async () => {
    open('/complaints/EXQ-NEWER222')
    expect(await screen.findByRole('heading', { level: 1, name: 'EXQ-NEWER222' })).toBeInTheDocument()
    expect(screen.getByText('A Citizen')).toBeInTheDocument() // a zero-width space taken out
    expect(screen.getByText(/They promised returns\./)).toHaveTextContent('They promised returns. Then they asked for a fee.')
    expect(screen.getByText(WALLET)).toBeInTheDocument()
    expect(screen.getByText('Wallet also in other complaints')).toBeInTheDocument()
    expect(screen.getByText('Is there any news?')).toBeInTheDocument()
    // The NCRP number shows masked until asked.
    expect(screen.queryByText('31234567890123')).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Show the NCRP number' }))
    expect(screen.getByText('31234567890123')).toBeInTheDocument()
  })

  it('starts a trace only from the officer\'s click, with the hash, the wallet and the NCRP number kept out of the link', async () => {
    const user = userEvent.setup()
    open('/complaints/EXQ-NEWER222')
    await user.click(await screen.findByRole('button', { name: 'Start a trace from this payment' }))
    const landed = screen.getByTestId('landed')
    expect(landed).toHaveTextContent(`/trace/new?pay=${HASH}&chain=tron&asset=USDT`)
    expect(landed.textContent).not.toContain('31234567890123')
    expect(JSON.parse(landed.dataset.prefill)).toEqual({ address: WALLET, ncrpAck: '31234567890123' })
  })

  it('leaves out an NCRP number New trace would refuse, rather than block the trace with it', async () => {
    // The citizen site takes 8 to 20 letters and digits; New trace and the
    // pipeline take 10 to 20 digits.
    const user = userEvent.setup()
    open('/complaints/EXQ-NEWER222', { '/complaints/EXQ-NEWER222': { body: { ...ONE, ncrp: 'AB12345678' } } })
    expect(await screen.findByText(/New trace opens without the NCRP number/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Start a trace from this payment' }))
    expect(JSON.parse(screen.getByTestId('landed').dataset.prefill)).toEqual({ address: WALLET, ncrpAck: '' })
  })

  it('offers a trace only on a chain this site traces', async () => {
    const evm = '0x' + 'c'.repeat(40)
    const payments = [{ ...ONE.payments[0], network: 'Polygon', wallet: evm }, { ...ONE.payments[0], network: 'Ethereum (ERC20)', wallet: evm }]
    open('/complaints/EXQ-NEWER222', { '/complaints/EXQ-NEWER222': { body: { ...ONE, payments } } })
    expect(await screen.findByText('Exchequer does not trace Polygon on this site.')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Start a trace from this payment' })).toHaveLength(1)
  })

  it('sends the officer\'s message and shows it in the thread, reminding them the citizen reads it', async () => {
    const user = userEvent.setup()
    const fetch = open('/complaints/EXQ-NEWER222', {
      '/complaints/EXQ-NEWER222/messages': { status: 201, body: { from: 'officer', body: 'We wrote to the exchange.', at: '2026-11-06T04:00:00+00:00' } },
    })
    const box = await screen.findByLabelText('Message to the citizen')
    expect(screen.getByText(/The citizen sees only what you write here/)).toBeInTheDocument()
    await user.type(box, 'We wrote to the exchange.')
    await user.click(screen.getByRole('button', { name: 'Send to the citizen' }))
    const sent = fetch.mock.calls.find(([url, init]) => String(url).endsWith('/messages') && init?.method === 'POST')
    expect(JSON.parse(sent[1].body)).toEqual({ body: 'We wrote to the exchange.' })
    expect(await screen.findByText('We wrote to the exchange.')).toBeInTheDocument()
    expect(box).toHaveValue('')
  })

  it('saves a new status', async () => {
    const user = userEvent.setup()
    const fetch = open('/complaints/EXQ-NEWER222', {
      '/complaints/EXQ-NEWER222/status': { body: { reference: 'EXQ-NEWER222', status: 'closed' } },
    })
    await user.selectOptions(await screen.findByLabelText('Status'), 'closed')
    await user.click(screen.getByRole('button', { name: 'Save status' }))
    const sent = fetch.mock.calls.find(([url]) => String(url).endsWith('/status'))
    expect(JSON.parse(sent[1].body)).toEqual({ status: 'closed' })
    expect(await screen.findByRole('status')).toHaveTextContent('Status saved: Closed')
  })

  it('links a stored case and then opens it', async () => {
    const user = userEvent.setup()
    open('/complaints/EXQ-NEWER222', {
      '/complaints/EXQ-NEWER222/link-case': { body: { reference: 'EXQ-NEWER222', case_id: 'case-9' } },
    })
    await user.type(await screen.findByLabelText('Stored case ID'), 'case-9')
    await user.click(screen.getByRole('button', { name: 'Link case' }))
    expect(await screen.findByRole('link', { name: 'Open case case-9' })).toHaveAttribute('href', '/case/case-9')
  })
})
