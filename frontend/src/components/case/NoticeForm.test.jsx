import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import LettersTab from './LettersTab'
import { looksRight } from './NoticeForm'

// Notices to a bank or a phone company in the Letters tab (backend
// notice_letters.py): offered on a stored case beside its letters, drafted only
// once the officer has typed the details and pressed Draft, through a POST whose
// body (never the URL) carries the account or phone number.
const B = '[____________________]'
const NOTICE = (to) => `From      : ${B} (name, rank, unit, official e-mail and phone)\nTo        : ${to}\nDate      : 12 November 2026\n`
const CASE = {
  case_id: 'c1', address: 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts', chain: 'tron', asset: 'USDT', direction: 'outgoing',
  exchange: 'Binance', exchange_address: 'TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf', intake: { mode: 'address', payments: [] },
}

function api(extra = {}) {
  const calls = []
  const routes = {
    'GET /trace/c1/letters': { body: { case_id: 'c1', letters: [{ to: 'exchange', title: 'Request to Binance' }] } },
    'GET /trace/c1/letter': { body: 'To        : Binance\n' },
    'GET /trace/c1/requests': { body: { count: 0, requests: [] } },
    'GET /watches': { body: { count: 0, watches: [] } },
    'GET /demos/recorded/11/letters': { body: { case_id: null, letters: [{ to: 'exchange', title: 'Request to Binance' }] } },
    'GET /demos/recorded/11/letter': { body: 'To        : Binance\n' },
    'POST /trace/c1/notice': (body) => ({ body: NOTICE(body.to === 'telecom' ? body.operator : body.bank) }),
    'POST /requests': (body) => ({ status: 201, body: { ...body, request_id: 'r1', history: [], mine: true } }),
    ...extra,
  }
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const [path, query = ''] = String(url).replace(/^\/api/, '').split('?')
    let body = init.body
    try { body = JSON.parse(body) } catch { /* none */ }
    calls.push({ method, path, query, body, url: String(url) })
    const hit = routes[`${method} ${path}`]
    if (!hit) return new Response(JSON.stringify({ detail: 'not stubbed' }), { status: 404 })
    const { status = 200, body: out } = typeof hit === 'function' ? hit(body) : hit
    return new Response(typeof out === 'string' ? out : JSON.stringify(out), { status })
  }))
  return calls
}

const open = (recorded = null) => render(<MemoryRouter><LettersTab result={recorded ? { ...CASE, case_id: null } : CASE} recorded={recorded} /></MemoryRouter>)
const notices = () => screen.findByRole('group', { name: 'Notice to' })
const sheet = () => screen.getByRole('article', { name: /^Draft: / })

async function fillBank(user) {
  await user.type(screen.getByLabelText('Bank'), 'State Bank of India')
  await user.type(screen.getByLabelText('Account number'), '1234 5678 9012')
  await user.type(screen.getByLabelText('IFSC'), 'SBIN0001234')
  await user.type(screen.getByLabelText('Where it came from'), 'Binance reply LE-2026-0042')
}

describe('bank and phone company notices in the Letters tab', () => {
  it('offers Bank and Phone company on a stored case, and drafts nothing until asked', async () => {
    const calls = api()
    const user = userEvent.setup()
    open()
    await user.click(within(await notices()).getByRole('button', { name: 'Bank' }))
    expect(screen.getByRole('form', { name: 'Bank details' })).toBeInTheDocument()
    expect(within(sheet()).getByText(/press Draft the letter/)).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/trace/c1/notice')).toBe(false)
  })

  it('posts the details in the body, never the URL, and shows the draft', async () => {
    const calls = api()
    const user = userEvent.setup()
    open()
    await user.click(within(await notices()).getByRole('button', { name: 'Bank' }))
    await fillBank(user)
    await user.type(screen.getByLabelText('From'), '2026-10-01')
    await user.type(screen.getByLabelText('To'), '2026-11-10')
    await user.click(screen.getByRole('button', { name: 'Draft the letter' }))
    expect(await within(sheet()).findByText(/State Bank of India/)).toBeInTheDocument()
    const post = calls.find((c) => c.path === '/trace/c1/notice')
    expect(post.body).toMatchObject({ to: 'bank-info', bank: 'State Bank of India', account: '1234 5678 9012', ifsc: 'SBIN0001234',
      period_from: '2026-10-01', period_to: '2026-11-10' })
    expect(calls.every((c) => !c.url.includes('9012') && !c.url.includes('SBIN'))).toBe(true)
  })

  it('an urgent hold asks for the Magistrate\'s order and waits for a second officer', async () => {
    const calls = api()
    const user = userEvent.setup()
    open()
    await user.click(within(await notices()).getByRole('button', { name: 'Bank' }))
    await user.click(screen.getByRole('button', { name: 'Urgent hold' }))
    expect(screen.getByText('needed for a hold')).toBeInTheDocument()
    await fillBank(user)
    await user.type(screen.getByLabelText("Magistrate's order"), 'Order 17/2026, JMFC Court')
    await user.type(screen.getByLabelText('Amount (₹)'), '2,50,000')
    await user.click(screen.getByRole('button', { name: 'Draft the letter' }))
    await within(sheet()).findByText(/State Bank of India/)
    expect(calls.find((c) => c.path === '/trace/c1/notice').body).toMatchObject({ to: 'bank-freeze', order: 'Order 17/2026, JMFC Court', amount: '2,50,000' })
    expect(screen.getByRole('heading', { name: 'Second officer' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mark as sent' })).toHaveAttribute('aria-disabled', 'true')
  })

  it('switching to an urgent hold drafts nothing until the officer presses Draft', async () => {
    const calls = api()
    const user = userEvent.setup()
    open()
    await user.click(within(await notices()).getByRole('button', { name: 'Bank' }))
    await fillBank(user)
    await user.click(screen.getByRole('button', { name: 'Draft the letter' }))
    await within(sheet()).findByText(/State Bank of India/)
    await user.click(screen.getByRole('button', { name: 'Urgent hold' }))
    expect(within(sheet()).getByText(/press Draft the letter/)).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/trace/c1/notice').map((c) => c.body.to)).toEqual(['bank-info'])
  })

  it('changing a detail after drafting asks for a fresh draft', async () => {
    api()
    const user = userEvent.setup()
    open()
    await user.click(within(await notices()).getByRole('button', { name: 'Phone company' }))
    await user.type(screen.getByLabelText('Phone company'), 'Example Telecom')
    await user.type(screen.getByLabelText('Mobile number'), '9876543210')
    await user.click(screen.getByRole('button', { name: 'Draft the letter' }))
    await within(sheet()).findByText(/Example Telecom/)
    await user.type(screen.getByLabelText('Mobile number'), '1')
    expect(within(sheet()).getByText(/press Draft the letter/)).toBeInTheDocument()
  })

  it('says why the server refused the details', async () => {
    api({ 'POST /trace/c1/notice': { status: 400, body: { detail: 'Enter the IFSC: four letters, a zero, then six letters or digits.' } } })
    const user = userEvent.setup()
    open()
    await user.click(within(await notices()).getByRole('button', { name: 'Bank' }))
    await user.click(screen.getByRole('button', { name: 'Draft the letter' }))
    await waitFor(() => expect(within(sheet()).getByRole('alert')).toHaveTextContent('Enter the IFSC'))
  })

  it('logs a sent notice under its own kind, to the bank the officer named', async () => {
    const calls = api()
    const user = userEvent.setup()
    open()
    await user.click(within(await notices()).getByRole('button', { name: 'Bank' }))
    await fillBank(user)
    await user.click(screen.getByRole('button', { name: 'Draft the letter' }))
    await within(sheet()).findByText(/State Bank of India/)
    await user.click(screen.getByRole('button', { name: 'Mark as sent' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/requests')).toBe(true))
    expect(calls.find((c) => c.path === '/requests' && c.method === 'POST').body)
      .toMatchObject({ case_id: 'c1', recipient: 'State Bank of India', kind: 'bank-info', address: '', asset: '', status: 'sent' })
  })

  it('a case with no letter still offers the notices, opened only when picked', async () => {
    api({ 'GET /trace/c1/letters': { body: { case_id: 'c1', letters: [] } } })
    const user = userEvent.setup()
    open()
    await user.click(within(await notices()).getByRole('button', { name: 'Phone company' }))
    expect(screen.getByRole('form', { name: 'Phone company details' })).toBeInTheDocument()
  })

  it('a recorded example offers no notices', async () => {
    api()
    open(11)
    await screen.findByRole('group', { name: 'Letter to' })
    expect(screen.queryByRole('group', { name: 'Notice to' })).not.toBeInTheDocument()
  })
})

describe('looksRight', () => {
  it('ticks a well-formed IFSC, account and mobile number, and nothing else', () => {
    expect(looksRight('ifsc', 'sbin0001234')).toBe(true)
    expect(looksRight('ifsc', 'SBIN1001234')).toBe(false)
    expect(looksRight('account', '1234 5678 9012')).toBe(true)
    expect(looksRight('account', '12-ab')).toBe(false)
    expect(looksRight('phone', '+91 98765 43210')).toBe(true)
    expect(looksRight('phone', '12345')).toBe(false)
    expect(looksRight('bank', 'State Bank')).toBe(false)
  })
})
