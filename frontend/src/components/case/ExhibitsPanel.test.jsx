import { createHash } from 'node:crypto'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ExhibitsPanel, { lastCheck, size } from './ExhibitsPanel'

// The exhibit register on the Evidence tab (backend exhibits.py): each forensic
// file by its hashes, a hand-over with its reason, and a file checked against the
// record by hashing it here. The file itself is never sent: only its SHA-256.
const BYTES = new TextEncoder().encode('a forensic image, in miniature')
const SHA = createHash('sha256').update(BYTES).digest('hex')
const ROW = {
  exhibit_id: 'e1', case_id: 'c1', kind: 'phone_extraction', label: "Accused's phone, Samsung A54", tool: 'Cellebrite UFED 7.69',
  file_name: 'A54_full.ufdr', size_bytes: 64_000_000_000, sha256: SHA, sha1: '', md5: '', made_by: 'SI Iyer', made_on: '2026-11-12',
  stored_at: 'Evidence room, shelf 3', holder: 'SI Iyer', status: 'held', notes: '',
  history: [{ at: '2026-11-12T10:00:00Z', action: 'recorded' }],
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

const open = () => render(<ExhibitsPanel result={{ case_id: 'c1' }} />)
const file = (name = 'A54_full.ufdr', bytes = BYTES) => new File([bytes], name)

describe('the exhibit register panel', () => {
  it('shows each exhibit with its tool, size, hash, maker and who holds it', async () => {
    api({ 'GET /trace/c1/exhibits': { body: { exhibits: [ROW] } } })
    open()
    expect(await screen.findByText('Cellebrite UFED 7.69')).toBeInTheDocument()
    expect(screen.getByText(/64.0 GB/)).toBeInTheDocument()
    expect(screen.getByText('Held by SI Iyer')).toBeInTheDocument()
    expect(screen.getByTitle(SHA)).toBeInTheDocument()
  })

  it('fills the SHA-256 from a file hashed here, and sends only the hash', async () => {
    const calls = api({
      'GET /trace/c1/exhibits': { body: { exhibits: [] } },
      'POST /trace/c1/exhibits': (b) => ({ status: 201, body: { ...ROW, ...b, exhibit_id: 'e2' } }),
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Record a forensic file' }))
    const form = screen.getByRole('form', { name: 'Record a forensic file' })
    await user.type(within(form).getByLabelText('What it is'), 'Laptop SSD image')
    await user.type(within(form).getByLabelText('Tool and version'), 'FTK Imager 4.7')
    await user.upload(within(form).getByLabelText(/Fill the SHA-256 from the file/), file('ssd.E01'))
    await waitFor(() => expect(within(form).getByLabelText('SHA-256')).toHaveValue(SHA))
    expect(within(form).getByLabelText('File name')).toHaveValue('ssd.E01')
    await user.click(within(form).getByRole('button', { name: 'Add to the exhibits' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const sent = calls.find((c) => c.method === 'POST').body
    expect(sent).toMatchObject({ label: 'Laptop SSD image', tool: 'FTK Imager 4.7', sha256: SHA, file_name: 'ssd.E01', size_bytes: String(BYTES.length) })
    expect(JSON.stringify(sent)).not.toContain('a forensic image') // never the file's contents
    expect(await screen.findByText(/the file stayed on this computer/)).toBeInTheDocument()
  })

  it('checks a file against an exhibit and says whether it matches', async () => {
    const calls = api({
      'GET /trace/c1/exhibits': { body: { exhibits: [ROW] } },
      'POST /exhibits/e1/check': (b) => ({ body: { result: b.sha256 === SHA ? 'match' : 'mismatch', exhibit: ROW } }),
    })
    const user = userEvent.setup()
    open()
    await user.upload(await screen.findByLabelText('Check a file against this exhibit'), file())
    expect(await screen.findByText(/A54_full.ufdr matches exhibit/)).toBeInTheDocument()
    await user.upload(screen.getByLabelText('Check a file against this exhibit'), file('copy.ufdr', new TextEncoder().encode('altered')))
    expect(await screen.findByText(/copy.ufdr does NOT match/)).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/exhibits/e1/check').map((c) => c.body.sha256)[0]).toBe(SHA)
  })

  it('records a hand-over only with who and why', async () => {
    const calls = api({
      'GET /trace/c1/exhibits': { body: { exhibits: [ROW] } },
      'PATCH /exhibits/e1': (b) => ({ body: { ...ROW, ...b } }),
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Hand over' }))
    const save = screen.getByRole('button', { name: 'Record the hand-over' })
    expect(save).toBeDisabled()
    await user.type(screen.getByLabelText('To whom'), 'Insp. Rao')
    await user.type(screen.getByLabelText('Why'), 'for the s.63 certificate')
    await user.click(save)
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH').body).toEqual({ holder: 'Insp. Rao', note: 'for the s.63 certificate' })
  })

  it('adds a note to an ended exhibit and shows it in the history', async () => {
    const ended = { ...ROW, status: 'released', history: [...ROW.history, { at: '2026-11-13T05:00:00Z', action: 'changed', changed: ['status'], note: "court's order" }] }
    const calls = api({
      'GET /trace/c1/exhibits': { body: { exhibits: [ended] } },
      'PATCH /exhibits/e1': (b) => ({ body: { ...ended, history: [...ended.history, { at: '2026-11-13T06:00:00Z', action: 'noted', note: b.note }] } }),
    })
    const user = userEvent.setup()
    open()
    expect(await screen.findByText(/status changed \(court's order\)/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Hand over' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Add a note' }))
    await user.type(screen.getByLabelText('Note'), 'owner signed the receipt')
    await user.click(screen.getByRole('button', { name: 'Record the note' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH').body).toEqual({ note: 'owner signed the receipt' })
  })

  it('shows a note entry as a note, never as "recorded"', async () => {
    const noted = { ...ROW, history: [...ROW.history, { at: '2026-11-13T06:00:00Z', action: 'noted', note: 'seal intact' }] }
    api({ 'GET /trace/c1/exhibits': { body: { exhibits: [noted] } } })
    open()
    expect(await screen.findByText(/note: seal intact/)).toBeInTheDocument()
    expect(screen.getAllByText(/recorded$/)).toHaveLength(1)
  })

  it('says so when the exhibits cannot be loaded, instead of showing none', async () => {
    api({ 'GET /trace/c1/exhibits': { status: 500, body: { detail: 'boom' } } })
    open()
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be loaded/)
    expect(screen.getByRole('alert').closest('details')).toHaveAttribute('open') // not hidden in a shut panel
  })

  it('says what the server refused', async () => {
    api({
      'GET /trace/c1/exhibits': { body: { exhibits: [] } },
      'POST /trace/c1/exhibits': { status: 409, body: { detail: 'This file is already exhibit e1 of this case.' } },
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Record a forensic file' }))
    await user.click(screen.getByRole('button', { name: 'Add to the exhibits' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already exhibit')
  })
})

describe('helpers', () => {
  it('writes sizes as a person reads them', () => {
    expect([null, 812, 812_000, 64_000_000_000].map(size)).toEqual(['', '812 bytes', '812.0 KB', '64.0 GB'])
  })

  it('names the last check of a file', () => {
    expect(lastCheck(ROW)).toBeNull()
    const checked = { ...ROW, history: [...ROW.history, { at: '2026-11-13T05:00:00Z', action: 'checked', result: 'mismatch' }] }
    expect(lastCheck(checked)).toEqual({ tone: 'red', text: 'File checked 2026-11-13: does NOT match' })
  })
})
