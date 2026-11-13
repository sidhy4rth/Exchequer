import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import IdentifiersPanel, { Lookup, daysBetween, historyText, shown } from './IdentifiersPanel'

// What the victim reported besides the wallet (backend identifiers.py): each
// identifier as kept, where it was seen, withdrawn with a reason, never deleted.
const ROW = {
  identifier_id: 'i1', case_id: 'c1', kind: 'domain', value: 'scam-shop.in', entered: 'https://www.scam-shop.in/pay',
  context: 'link sent on WhatsApp', notes: '', status: 'active',
  history: [{ at: '2026-11-13T10:00:00Z', action: 'recorded' }],
}

// The example.com lookup as recorded in backend/tests/fixtures/osint/responses.json.
const LOOKUP = {
  lookup_id: 'l1', identifier_id: 'i1', case_id: 'c1', queried: 'example.com', created_at: '2026-11-13T10:00:00Z', by: 'demo',
  rdap: {
    name: 'example.com', registrar: 'RESERVED-Internet Assigned Numbers Authority', registrar_iana_id: '376',
    registered_on: '1995-08-14', expires_on: '2027-08-13', changed_on: '2026-08-14', abuse_email: '', abuse_phone: '',
    status: [], name_servers: ['elliott.ns.cloudflare.com', 'hera.ns.cloudflare.com'],
  },
  rdap_note: '', dns: { A: ['104.20.23.154', '172.66.147.243'], AAAA: [], NS: [] }, dns_note: '',
  sources: [
    { source: 'rdap', provider: 'rdap.verisign.com', request: 'https://rdap.verisign.com/com/v1/domain/example.com', status: 200, fetched_at: '2026-11-13T10:00:00Z', sha256: 'e38fb301b55d200d1ffdf18c631c905b8b747fbe8198bd5b8e74e0824896972a', bytes: 2440 },
    { source: 'dns', provider: 'cloudflare-dns.com', request: 'https://cloudflare-dns.com/dns-query?name=example.com&type=A', status: 200, fetched_at: '2026-11-13T10:00:00Z', sha256: '9cc458718f83279bc77e5d394dff6863886bf15f602eb3baa05122504048cd93', bytes: 251 },
  ],
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

const open = () => render(<MemoryRouter><IdentifiersPanel result={{ case_id: 'c1' }} /></MemoryRouter>)

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

  it('offers a lookup only for an active domain, and only when the server has lookups on', async () => {
    const phone = { ...ROW, identifier_id: 'i3', kind: 'phone', value: '+919876543210', entered: '+919876543210', context: '' }
    api({ 'GET /trace/c1/identifiers': { body: { identifiers: [ROW, phone], lookups_enabled: false } } })
    const first = open()
    await screen.findByText('scam-shop.in')
    expect(screen.queryByRole('button', { name: /Look up/ })).not.toBeInTheDocument()
    first.unmount()
    api({ 'GET /trace/c1/identifiers': { body: { identifiers: [ROW, phone], lookups_enabled: true } } })
    open()
    await screen.findByText('scam-shop.in')
    expect(screen.getAllByRole('button', { name: 'Look up public records' })).toHaveLength(1)
  })

  it('tells a caller who is not signed in why there is no lookup button', async () => {
    const note = "Sign in as an officer to look up a domain's public records."
    api({ 'GET /trace/c1/identifiers': { body: { identifiers: [ROW], lookups_enabled: false, lookups_note: note } } })
    open()
    expect(await screen.findByText(note)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Look up/ })).not.toBeInTheDocument()
  })

  it('looks a domain up and shows what the registry and DNS said, with their sources', async () => {
    let rows = [ROW]
    const calls = api({
      'GET /trace/c1/identifiers': () => ({ body: { identifiers: rows, lookups_enabled: true } }),
      'POST /identifiers/i1/lookup': () => { rows = [{ ...ROW, lookup: LOOKUP }]; return { body: LOOKUP } },
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Look up public records' }))
    expect(await screen.findByText(/RESERVED-Internet Assigned Numbers Authority/)).toBeInTheDocument()
    expect(screen.getByText('1995-08-14')).toBeInTheDocument()
    expect(screen.getByText('104.20.23.154, 172.66.147.243')).toBeInTheDocument()
    expect(screen.getByText(/Where this came from \(2 responses\)/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Look up again' })).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it('marks a young domain by its age when looked up, and says why a record is missing', () => {
    const young = { ...LOOKUP, created_at: '2026-11-13T10:00:00Z', rdap: { ...LOOKUP.rdap, registered_on: '2026-11-01' } }
    const { unmount } = render(<Lookup lookup={young} />)
    expect(screen.getByText('12 days old when looked up')).toHaveClass('red')
    unmount()
    render(<Lookup lookup={{ ...LOOKUP, rdap: null, rdap_note: 'The .xyz registry offers no RDAP service.' }} />)
    expect(screen.getByText(/offers no RDAP service/)).toBeInTheDocument()
    expect(screen.queryByText(/old when looked up/)).not.toBeInTheDocument()
  })

  it('counts days between two dates', () => {
    expect(daysBetween('2026-11-01', '2026-11-13T10:00:00Z')).toBe(12)
    expect(daysBetween('', '2026-11-13')).toBeNull()
  })

  it('links an identifier to the other cases that reported it, and says it is a lead', async () => {
    const others = [
      { case_id: 'c2aaaaaaaa-0000', identifier_id: 'x1', recorded_at: '2026-11-10T09:00:00Z', context: 'second complaint' },
      { case_id: 'c3bbbbbbbb-0000', identifier_id: 'x2', recorded_at: '2026-11-11T09:00:00Z', context: '' },
    ]
    api({ 'GET /trace/c1/identifiers': { body: { identifiers: [{ ...ROW, also_in: others }] } } })
    open()
    expect(await screen.findByText('Also in 2 other cases')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'case c2aaaaaa' })).toHaveAttribute('href', '/case/c2aaaaaaaa-0000?tab=evidence')
    expect(screen.getByText(/second complaint/)).toBeInTheDocument()
    expect(screen.getByText(/a lead that they reached the same people, not proof/)).toBeInTheDocument()
  })

  it('shows no link for an identifier no other case has, or one that was withdrawn', async () => {
    const other = [{ case_id: 'c2', identifier_id: 'x1', recorded_at: '2026-11-10T09:00:00Z', context: '' }]
    api({ 'GET /trace/c1/identifiers': { body: { identifiers: [
      { ...ROW, also_in: [] },
      { ...ROW, identifier_id: 'i9', value: 'gone.in', entered: 'gone.in', status: 'withdrawn', also_in: other },
    ] } } })
    open()
    await screen.findByText('gone.in')
    expect(screen.queryByText(/Also in/)).not.toBeInTheDocument()
  })
})
