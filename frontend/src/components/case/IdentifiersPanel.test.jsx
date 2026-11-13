import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import IdentifiersPanel, { historyText, shown } from './IdentifiersPanel'

// What the victim reported besides the wallet (backend identifiers.py): each
// identifier as kept, where it was seen, withdrawn with a reason, never deleted.
const ROW = {
  identifier_id: 'i1', case_id: 'c1', kind: 'domain', value: 'scam-shop.in', entered: 'https://www.scam-shop.in/pay',
  context: 'link sent on WhatsApp', notes: '', status: 'active',
  history: [{ at: '2026-11-13T10:00:00Z', action: 'recorded' }],
}

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

const open = () => render(<IdentifiersPanel result={{ case_id: 'c1' }} />)

describe('the reported identifiers panel', () => {
  it('shows each identifier as kept, what was typed, and where it was seen', async () => {
    api({ 'GET /trace/c1/identifiers': { body: { identifiers: [ROW] } } })
    open()
    expect(await screen.findByText('scam-shop.in')).toBeInTheDocument()
    expect(screen.getByText('https://www.scam-shop.in/pay')).toBeInTheDocument()
    expect(screen.getByText('link sent on WhatsApp')).toBeInTheDocument()
    expect(screen.getByText(/Reported identifiers · 1/)).toBeInTheDocument()
  })

  it('does not repeat the value as typed when it was typed as kept', async () => {
    api({ 'GET /trace/c1/identifiers': { body: { identifiers: [{ ...ROW, entered: 'scam-shop.in', context: '' }] } } })
    open()
    await screen.findByText('scam-shop.in')
    expect(screen.queryByText('As typed')).not.toBeInTheDocument()
  })

  it('adds one with its kind, value and where it was seen', async () => {
    const calls = api({
      'GET /trace/c1/identifiers': { body: { identifiers: [] } },
      'POST /trace/c1/identifiers': (b) => ({ status: 201, body: { ...ROW, ...b, identifier_id: 'i2' } }),
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Add a reported identifier' }))
    const form = screen.getByRole('form', { name: 'Add a reported identifier' })
    await user.selectOptions(within(form).getByLabelText('What it is'), 'telegram')
    await user.type(within(form).getByLabelText('Telegram username'), '@crypto_help')
    await user.type(within(form).getByLabelText('Where the victim saw it'), 'first contact')
    await user.click(within(form).getByRole('button', { name: 'Add to the case' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST').body).toEqual({ kind: 'telegram', value: '@crypto_help', context: 'first contact', notes: '' })
  })

  it("shows the server's refusal and keeps the form", async () => {
    api({
      'GET /trace/c1/identifiers': { body: { identifiers: [] } },
      'POST /trace/c1/identifiers': { status: 400, body: { detail: "Enter the website's domain name, not an IP address." } },
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Add a reported identifier' }))
    await user.type(screen.getByLabelText('Website domain'), '127.0.0.1')
    await user.click(screen.getByRole('button', { name: 'Add to the case' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('not an IP address')
    expect(screen.getByRole('form', { name: 'Add a reported identifier' })).toBeInTheDocument()
  })

  it('withdraws only with a reason, and the row stays', async () => {
    let rows = [ROW]
    const calls = api({
      'GET /trace/c1/identifiers': () => ({ body: { identifiers: rows } }),
      'PATCH /identifiers/i1': (b) => {
        rows = [{ ...ROW, status: 'withdrawn', history: [...ROW.history, { at: '2026-11-13T11:00:00Z', action: 'changed', changed: ['status'], note: b.note }] }]
        return { body: rows[0] }
      },
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Withdraw' }))
    const go = screen.getByRole('button', { name: 'Withdraw it' })
    expect(go).toBeDisabled()
    await user.type(screen.getByLabelText('Why'), 'typed wrongly')
    await user.click(go)
    expect(await screen.findByText('Withdrawn')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PATCH').body).toEqual({ status: 'withdrawn', note: 'typed wrongly' })
    expect(screen.getByText('scam-shop.in')).toBeInTheDocument()
    expect(screen.getByText(/Reported identifiers · 0/)).toBeInTheDocument()
  })

  it('says when the list could not be loaded instead of showing it empty', async () => {
    api({ 'GET /trace/c1/identifiers': { status: 500, body: { detail: 'boom' } } })
    open()
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded')
  })

  it('words history and usernames plainly', () => {
    expect(historyText({ action: 'changed', changed: ['status'], note: 'typo' })).toBe('status changed (typo)')
    expect(historyText({ action: 'noted', note: 'site down' })).toBe('note: site down')
    expect(historyText({ action: 'recorded' })).toBe('recorded')
    expect(shown({ kind: 'telegram', value: 'crypto_help' })).toBe('@crypto_help')
    expect(shown({ kind: 'phone', value: '+919876543210' })).toBe('+919876543210')
  })
})
