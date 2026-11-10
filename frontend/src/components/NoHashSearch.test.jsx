import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TraceForm from './TraceForm'
import { stubFetch } from '../test/setup'

// New trace's "I don't have the payment hash" path: the officer searches the
// reported wallet for the victim's payment by its exact amount and a time
// window in IST (POST /payments/search), picks the match, and the trace
// starts from it, marked found by officer search.
const health = {
  status: 'ok',
  default_chain: 'tron',
  chains: { tron: { key: 'tron', name: 'Tron', ready: true, address_family: 'tron', assets: [{ symbol: 'USDT' }, { symbol: 'TRX' }] } },
}
const WALLET = 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts'
const SENDER = 'TXYZabcdefghijkmnopqrstuvwxyz12345'
const HASH = 'ab'.repeat(32)
// 9 Nov 2026, 14:30 in India is 09:00 UTC.
const PAID_AT = Date.UTC(2026, 10, 9, 9, 0) / 1000
const MATCH = { tx_hash: HASH, timestamp: PAID_AT, amount: '1500.25', from: SENDER, to: WALLET, chain: 'tron', asset: 'USDT', found_by: 'officer_search' }
const found = (over = {}) => ({ body: { matches: [MATCH], more_matches: false, scanned: 40, complete: true, ...over } })

function Landed() {
  const { pathname, search } = useLocation()
  return <p data-testid="landed">{pathname + search}</p>
}

async function renderForm({ payments = true, search = found(), onUnlock, check = { body: { pass: 'p1' } } } = {}) {
  const fetch = stubFetch({
    '/trace/intake': { body: { payments, lookup_limit: 1000 } }, '/demos/recorded': { body: { demos: [] } },
    '/payments/search': search, '/access/check': check,
  })
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<TraceForm health={health} onUnlock={onUnlock} />} />
        <Route path="/trace/:address" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByLabelText('Wallet the victim paid')
  return fetch
}

const searches = (fetch) => fetch.mock.calls.filter(([url]) => String(url).endsWith('/payments/search'))

/** Open the search and fill it in: the wallet above, then the amount and the time in IST. */
async function fillIn(user, { wallet = WALLET, amount = '1500.25', at = '2026-11-09T14:30' } = {}) {
  await user.type(screen.getByLabelText('Wallet the victim paid'), wallet)
  await user.click(await screen.findByRole('button', { name: "I don't have the payment hash" }))
  if (amount) await user.type(screen.getByLabelText('Exact amount paid'), amount)
  if (at) fireEvent.change(screen.getByLabelText('When the victim paid, in IST'), { target: { value: at } })
}

describe("New trace without the payment hash", () => {
  it('opens a small search form and sends nothing until Search is pressed', async () => {
    const user = userEvent.setup()
    const fetch = await renderForm()
    const toggle = await screen.findByRole('button', { name: "I don't have the payment hash" })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await fillIn(user)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const form = screen.getByRole('group', { name: 'Search the wallet for the payment' })
    expect(form).toHaveTextContent('Tron · USDT')
    expect(form).toHaveTextContent(WALLET)
    // ±12 h around the time typed in, unless chosen.
    expect(within(form).getByRole('radio', { name: '12 hours either side' })).toBeChecked()
    expect(form).toHaveTextContent('Searches 9 Nov 2026 02:30 to 10 Nov 2026 02:30 IST')
    expect(searches(fetch)).toEqual([])
  })

  it('searches the wallet for the exact amount, the window sent in UTC', async () => {
    const user = userEvent.setup()
    const fetch = await renderForm()
    await fillIn(user)
    await user.click(screen.getByRole('radio', { name: '3 hours either side' }))
    await user.click(screen.getByRole('button', { name: 'Search the wallet' }))
    await screen.findByRole('list', { name: 'Payments that match exactly' })
    const [[, init]] = searches(fetch)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ chain: 'tron', asset: 'USDT', wallet: WALLET, amount: '1500.25',
      from: '2026-11-09T06:00:00.000Z', to: '2026-11-09T12:00:00.000Z' })
  })

  it('shows only the exact matches: time in IST and UTC, amount, sender and a short hash', async () => {
    const user = userEvent.setup()
    await renderForm()
    await fillIn(user)
    await user.click(screen.getByRole('button', { name: 'Search the wallet' }))
    const list = await screen.findByRole('list', { name: 'Payments that match exactly' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent('9 Nov 2026 14:30 IST')
    expect(rows[0]).toHaveTextContent('2026-11-09 09:00 UTC')
    expect(rows[0]).toHaveTextContent('1500.25 USDT')
    expect(rows[0]).toHaveTextContent('TXYZabcdef…xyz12345')
    expect(rows[0]).toHaveTextContent('abababab…abababab')
    expect(rows[0]).not.toHaveTextContent(HASH)
    expect(screen.getByText('1 transfer of exactly 1500.25 USDT reached this wallet in the window.')).toBeInTheDocument()
  })

  it('puts a chosen match into the payment hashes, marked found by officer search, and the trace carries it', async () => {
    const user = userEvent.setup()
    await renderForm()
    await fillIn(user)
    await user.click(screen.getByRole('button', { name: 'Search the wallet' }))
    await user.click(await screen.findByRole('button', { name: 'Use this payment abababab…abababab' }))
    const hashes = screen.getByLabelText(/victim's payment hashes/i)
    expect(hashes).toHaveValue(HASH)
    expect(hashes).toHaveFocus()
    expect(screen.getByText(/1 found by officer search/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: "I don't have the payment hash" })).toHaveAttribute('aria-expanded', 'false')
    await user.click(screen.getByRole('button', { name: /^start trace$/i }))
    const landed = new URLSearchParams(screen.getByTestId('landed').textContent.split('?')[1])
    expect(landed.get('pay')).toBe(HASH)
    expect(landed.get('found')).toBe(HASH)
  })

  it('says so when more than the matches shown fit, and when the read stopped short', async () => {
    const user = userEvent.setup()
    await renderForm({ search: found({ more_matches: true, complete: false }) })
    await fillIn(user)
    await user.click(screen.getByRole('button', { name: 'Search the wallet' }))
    expect(await screen.findByText(/More transfers match than are shown/)).toBeInTheDocument()
    expect(screen.getByText(/did not reach back to the start of the window/)).toBeInTheDocument()
  })

  it.each([
    [true, /No transfer of exactly 1500\.25 USDT reached this wallet between 9 Nov 2026 02:30 and 10 Nov 2026 02:30 IST/],
    [false, /did not reach back to the start of the window, so a payment there may be missed/],
  ])('says plainly when nothing matches (read complete: %s), with a way on', async (complete, words) => {
    const user = userEvent.setup()
    await renderForm({ search: found({ matches: [], complete }) })
    await fillIn(user)
    await user.click(screen.getByRole('button', { name: 'Search the wallet' }))
    expect(await screen.findByText(words)).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Payments that match exactly' })).not.toBeInTheDocument()
    expect(screen.getByText(/start the trace from the wallet without a hash/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Search the wallet' })).toBeEnabled()
  })

  it('asks for the demo code where the search is, keeping everything typed, and searches again once unlocked', async () => {
    const user = userEvent.setup()
    const onUnlock = vi.fn()
    let calls = 0
    const fetch = await renderForm({ onUnlock, search: () => (calls++ === 0
      ? { status: 403, body: { detail: "This browser's access pass has expired. Enter the code again." } }
      : found()) })
    await fillIn(user)
    await user.click(screen.getByRole('button', { name: 'Search the wallet' }))
    const said = await screen.findByText(/Searching a wallet needs the demo code on this site\./)
    // The backend's own reason, beside the panel's sentence.
    expect(said).toHaveTextContent("This browser's access pass has expired.")
    const code = screen.getByLabelText('Access code')
    expect(code).toHaveFocus()
    await user.type(code, 'letmein')
    await user.click(screen.getByRole('button', { name: 'Unlock and search again' }))
    await screen.findByRole('list', { name: 'Payments that match exactly' })
    expect(onUnlock).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls.some(([url, init]) => String(url).endsWith('/access/check') && init.headers['X-Exchequer-Demo-Code'] === 'letmein')).toBe(true)
    // Nothing the officer typed was lost.
    expect(screen.getByLabelText('Wallet the victim paid')).toHaveValue(WALLET)
    expect(screen.getByLabelText('Exact amount paid')).toHaveValue('1500.25')
    expect(searches(fetch)).toHaveLength(2)
  })

  it('says why a wrong code was refused, and keeps the code box', async () => {
    const user = userEvent.setup()
    await renderForm({ search: { status: 403, body: { detail: 'Live tracing on this site needs an access code.' } },
      check: { status: 403, body: { detail: 'That access code is not right.' } } })
    await fillIn(user)
    await user.click(screen.getByRole('button', { name: 'Search the wallet' }))
    await user.type(await screen.findByLabelText('Access code'), 'wrong{Enter}')
    expect(await screen.findByText('That access code is not right.')).toBeInTheDocument()
    expect(screen.getByLabelText('Access code')).toBeInTheDocument()
    expect(screen.queryByTestId('landed')).not.toBeInTheDocument()
  })

  it('searches on Enter in any of its fields, the window choices too, and never starts the trace', async () => {
    const user = userEvent.setup()
    const fetch = await renderForm()
    await fillIn(user)
    screen.getByRole('radio', { name: '3 hours either side' }).focus()
    await user.keyboard('{Enter}')
    await screen.findByRole('list', { name: 'Payments that match exactly' })
    screen.getByLabelText('Exact amount paid').focus()
    await user.keyboard('{Enter}')
    await vi.waitFor(() => expect(searches(fetch)).toHaveLength(2))
    expect(screen.queryByTestId('landed')).not.toBeInTheDocument()
    expect(fetch.mock.calls.some(([url]) => String(url).includes('/trace/jobs'))).toBe(false)
  })

  it('keeps the keyboard on Search while it searches, so the answer is read out where the officer is', async () => {
    const user = userEvent.setup()
    const fetch = await renderForm({ search: found({ matches: [] }) })
    // Hold the search's answer until the test lets it go.
    let release
    const gate = new Promise((resolve) => { release = resolve })
    const answer = fetch.getMockImplementation()
    fetch.mockImplementation(async (url, init) => {
      if (String(url).endsWith('/payments/search')) await gate
      return answer(url, init)
    })
    await fillIn(user)
    // The answer's live region is in the page, hidden only to the eye, before any answer lands.
    const said = document.querySelector('.nh-said')
    expect(said).toHaveAttribute('role', 'status')
    expect(said).toHaveClass('visually-hidden')
    await user.click(screen.getByRole('button', { name: 'Search the wallet' }))
    const busy = screen.getByRole('button', { name: 'Searching…' })
    expect(busy).toHaveFocus()
    expect(busy).toHaveAttribute('aria-disabled', 'true')
    expect(busy).toBeEnabled()
    // A second press while it searches sends nothing more.
    await user.click(busy)
    release()
    await screen.findByText(/No transfer of exactly 1500\.25 USDT/)
    expect(screen.getByRole('button', { name: 'Search the wallet' })).toHaveFocus()
    expect(said).not.toHaveClass('visually-hidden')
    expect(searches(fetch)).toHaveLength(1)
  })

  it('does not add a payment already typed in another spelling', async () => {
    const user = userEvent.setup()
    await renderForm()
    await user.click(screen.getByRole('button', { name: /Victim's payments/ }))
    const upper = `0x${HASH.toUpperCase()}`
    fireEvent.change(screen.getByLabelText(/victim's payment hashes/i), { target: { value: upper } })
    await fillIn(user)
    await user.click(screen.getByRole('button', { name: 'Search the wallet' }))
    await user.click(await screen.findByRole('button', { name: 'Use this payment abababab…abababab' }))
    expect(screen.getByLabelText(/victim's payment hashes/i)).toHaveValue(upper)
    expect(screen.getByText(/1 payment · .* · 1 found by officer search/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^start trace$/i }))
    const landed = new URLSearchParams(screen.getByTestId('landed').textContent.split('?')[1])
    expect(landed.get('pay')).toBe(upper)
    expect(landed.get('found')).toBe(upper)
  })

  it.each([
    [429, 'This site has started 30 traces in the last hour. Try again in 42 min.', /^The search was refused for now\. This site has started 30 traces in the last hour\. Try again in 42 min\.$/],
    [502, 'The wallet could not be searched: the data provider did not answer. Try again later.', /The wallet could not be read just now\..*the data provider did not answer/],
    [503, "The wallet could not be searched: today's allowance is spent. Try again later.", /The wallet could not be read just now\..*allowance is spent/],
    [400, 'USDT on Tron has 6 decimal places; the amount has more.', /USDT on Tron has 6 decimal places/],
  ])('answers a %s in plain words and lets the officer search again', async (status, detail, words) => {
    const user = userEvent.setup()
    await renderForm({ search: { status, body: { detail } } })
    await fillIn(user)
    await user.click(screen.getByRole('button', { name: 'Search the wallet' }))
    expect(await screen.findByText(words)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Search the wallet' })).toBeEnabled()
  })

  it('on a site that does not trace from a payment hash, says so and offers no search', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: false })
    await user.click(await screen.findByRole('button', { name: "I don't have the payment hash" }))
    expect(screen.getByText(/Tracing from a payment hash is off on this site/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Search the wallet' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Exact amount paid')).not.toBeInTheDocument()
  })

  it('waits for the wallet, the amount and the time before it can search', async () => {
    const user = userEvent.setup()
    const fetch = await renderForm()
    await fillIn(user, { wallet: 'T123', amount: '', at: '' })
    const go = screen.getByRole('button', { name: 'Search the wallet' })
    expect(go).toBeDisabled()
    expect(screen.getByText(/Enter the wallet the victim paid above/)).toBeInTheDocument()
    await user.type(screen.getByLabelText('Exact amount paid'), '12,5')
    expect(screen.getByLabelText('Exact amount paid')).toHaveAttribute('aria-invalid', 'true')
    expect(searches(fetch)).toEqual([])
  })
})
