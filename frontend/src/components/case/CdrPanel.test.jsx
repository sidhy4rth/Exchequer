import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import CdrPanel from './CdrPanel'

// A CDR read in the browser against the case (backend cdr_imports.py). Every number is
// synthetic, and none can be a real Indian mobile: India's mobiles start 6 to 9 and India sets
// aside no range for fiction, while the panel, like the identifier register, reads a 10-digit
// number as an Indian mobile only when it starts 6 to 9, on purpose. So the numbers are in
// Ofcom's range for drama (+44 7700 900000 to 900999), set aside so that no subscriber holds
// one. The IMEI is made up and starts with zeros.
const IMEI = '000000000000011'
const CSV = [
  'A Party,B Party,Date,Time,Duration,Call Type,IMEI',
  `+447700900001,+447700900002,01/03/2026,10:15,120,MO,${IMEI}`,
  `+447700900001,+44 (0)7700 900002,02/03/2026,11:00,90,MT,${IMEI}`,
  `+447700900001,0044 7700 900003,03/03/2026,12:00,30,MO,${IMEI}`,
].join('\n')

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

const ON = { body: { enabled: true, imports: [], rows_max: 200, check_max: 50 } }
const IDS = { body: { identifiers: [{ kind: 'phone', value: '+447700900003', status: 'active' }] } }
const show = (result = { case_id: 'c1' }) => render(<MemoryRouter><CdrPanel result={result} /></MemoryRouter>)
const file = () => new File([CSV], 'cdr.csv', { type: 'text/csv' })

describe('the CDR panel', () => {
  it('shows nothing while the server has the feature off, and asks for nothing else', async () => {
    const calls = api({ 'GET /trace/c1/cdr': { body: { enabled: false, imports: [] } } })
    const { container } = show()
    await waitFor(() => expect(calls.length).toBe(1))
    expect(container.innerHTML).toBe('')
  })

  it("reads the CDR here, marks the case's own number, checks only the chosen number, and saves a summary", async () => {
    const calls = api({
      'GET /trace/c1/cdr': ON,
      'GET /trace/c1/identifiers': IDS,
      'POST /trace/c1/cdr/check': (body) => ({ body: { results: body.numbers.map((n) => ({ number: n, on_this_case: false,
        also_in: [{ case_id: 'c2-0000-0000', recorded_at: '2026-11-01', context: '' }] })) } }),
      'POST /trace/c1/cdr': { status: 201, body: { import_id: 'x1' } },
    })
    show()
    await userEvent.upload(await screen.findByLabelText(/CDR file/), file())

    const table = await screen.findByRole('table', { name: 'Top contacts' })
    const [first, second] = within(table).getAllByRole('row').slice(1)
    expect(first.textContent).toContain('+447700900002') // two calls: the top contact
    expect(second.textContent).toContain('This case') // the case's own phone identifier
    expect(first.textContent).not.toContain('This case') // silent on a number the case does not have
    expect(screen.getByText(/changed 0 times/)).toBeTruthy()
    expect(calls.filter((c) => c.method === 'POST')).toEqual([]) // nothing sent on reading

    await userEvent.click(screen.getByLabelText('Check +447700900002'))
    await userEvent.click(screen.getByRole('button', { name: /Check 1 chosen number/ }))
    await waitFor(() => expect(first.textContent).toContain('case c2-0000-'))
    expect(screen.getByRole('status').textContent).toMatch(/Checked 1 number: 1 on another case you can read/)
    expect(calls.find((c) => c.path === '/trace/c1/cdr/check').body).toEqual({ numbers: ['+447700900002'] })

    await userEvent.click(screen.getByLabelText('Keep +447700900002'))
    await userEvent.click(screen.getByLabelText('Keep +447700900003'))
    await userEvent.click(screen.getByRole('button', { name: /Save the summary/ }))
    await waitFor(() => expect(calls.some((c) => c.path === '/trace/c1/cdr' && c.method === 'POST')).toBe(true))
    const sent = calls.find((c) => c.path === '/trace/c1/cdr' && c.method === 'POST').body
    expect(sent.rows).toEqual([
      { kind: 'subject', value: '+447700900001', calls: 3, sms: 0, seconds: 240, first: '2026-03-01', last: '2026-03-03', reasons: [] },
      { kind: 'number', value: '+447700900002', calls: 2, sms: 0, seconds: 210, first: '2026-03-01', last: '2026-03-02', reasons: ['top_contact', 'other_case'] },
      { kind: 'number', value: '+447700900003', calls: 1, sms: 0, seconds: 30, first: '2026-03-03', last: '2026-03-03', reasons: ['top_contact', 'case_identifier'] },
    ])
    expect(JSON.stringify(sent)).not.toContain(IMEI) // a handset not ticked is not sent
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/Summary saved/))
  })

  it('puts the wide contacts table in a named region a keyboard can scroll, and keeps it a table', async () => {
    api({ 'GET /trace/c1/cdr': ON, 'GET /trace/c1/identifiers': { body: { identifiers: [] } } })
    show()
    await userEvent.upload(await screen.findByLabelText(/CDR file/), file())
    const region = await screen.findByRole('region', { name: /Top contacts/ })
    expect(region.getAttribute('tabindex')).toBe('0')
    expect(within(region).getByRole('table', { name: 'Top contacts' }).classList.contains('cdr-contacts')).toBe(true)
    expect(screen.getByRole('status').textContent).toBe('') // nothing announced until something is done
  })

  it('lists the summaries already saved to the case', async () => {
    api({ 'GET /trace/c1/cdr': { body: { ...ON.body, imports: [{ import_id: 'x1', title: 'CDR (test)', row_count: 1,
      created_at: '2026-11-14T10:00:00Z', rows: [{ kind: 'imei', value: IMEI, events: 3, first: '2026-03-01', last: '2026-03-03' }] }] } },
    'GET /trace/c1/identifiers': { body: { identifiers: [] } } })
    show()
    expect(await screen.findByText(/CDR \(test\) · 1 row/)).toBeTruthy()
  })
})
