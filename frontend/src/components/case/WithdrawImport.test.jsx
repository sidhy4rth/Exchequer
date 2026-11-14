import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import CdrPanel from './CdrPanel'
import StatementPanel from './StatementPanel'

// Withdrawing a saved import entered by mistake (backend statement_imports.withdraw).
// Every row is synthetic: a test narration, a reference shaped like an NEFT UTR,
// an IMEI that starts with a run of zeros.
const ROW = { date: '2026-03-12', time: '', direction: 'debit', amount: '250000', reference: 'SBINN26071000001',
  narration: 'TEST', counterparty: '', reasons: ['utr'], exchange: '' }
const STANDING = { import_id: 's1', title: 'Victim statement (test)', source_label: 'Bank statement', currency: 'INR',
  row_count: 1, created_at: '2026-11-14T10:00:00Z', rows: [ROW], withdrawn: null }
const GONE = { ...STANDING, import_id: 's2', title: 'Wrong case (test)',
  withdrawn: { at: '2026-11-14T11:00:00Z', by: 'officer-1', reason: 'Saved against the wrong case' } }

// Answers by method and path; `list(url)` answers the GET, so a test sees the query string.
function api(list, posts = {}) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const path = String(url).replace(/^\/api/, '')
    calls.push({ method, path, body: init.body ? JSON.parse(init.body) : undefined })
    if (method === 'GET' && path.startsWith('/trace/c1/identifiers')) return new Response(JSON.stringify({ identifiers: [] }))
    const hit = method === 'GET' ? { body: list(path) } : posts[path]
    if (!hit) return new Response(JSON.stringify({ detail: 'not stubbed' }), { status: 404 })
    return new Response(JSON.stringify(hit.body), { status: hit.status ?? 200 })
  }))
  return calls
}

const statements = (imports, more = {}) => ({ enabled: true, exchange_names: [], imports, withdrawn_count: 0, can_withdraw: true, ...more })

describe('withdrawing a saved statement import', () => {
  it('asks for a reason, sends it, and reloads the list without the withdrawn import', async () => {
    let withdrawn = false
    const calls = api(() => (withdrawn ? statements([], { withdrawn_count: 1 }) : statements([STANDING])), {
      '/trace/c1/statements/s1/withdraw': { body: { ...STANDING, withdrawn: GONE.withdrawn } },
    })
    render(<StatementPanel result={{ case_id: 'c1' }} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Withdraw these rows…' }))
    await userEvent.click(screen.getByRole('button', { name: 'Withdraw' }))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([]) // no reason, nothing sent
    await userEvent.type(screen.getByLabelText(/Why is it withdrawn/), 'Saved against the wrong case')
    withdrawn = true
    await userEvent.click(screen.getByRole('button', { name: 'Withdraw' }))
    await waitFor(() => expect(screen.queryByText(/Victim statement \(test\)/)).toBeNull())
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/trace/c1/statements/s1/withdraw', body: { reason: 'Saved against the wrong case' } }])
    expect(screen.getByLabelText('Show withdrawn (1)')).toBeTruthy()
  })

  it('shows the withdrawn imports struck through with the reason only when asked, and offers no second withdrawal', async () => {
    const calls = api((path) => (path.includes('withdrawn=1') ? statements([STANDING, GONE], { withdrawn_count: 1 })
      : statements([STANDING], { withdrawn_count: 1 })))
    render(<StatementPanel result={{ case_id: 'c1' }} />)
    await screen.findByText(/Victim statement \(test\)/)
    expect(screen.queryByText(/Wrong case \(test\)/)).toBeNull()
    await userEvent.click(screen.getByLabelText('Show withdrawn (1)'))
    const gone = await screen.findByText(/Wrong case \(test\)/)
    expect(gone.closest('details').className).toContain('withdrawn-import')
    expect(screen.getByText(/Withdrawn 2026-11-14 by officer-1: Saved against the wrong case/)).toBeTruthy()
    expect(screen.getAllByRole('button', { name: 'Withdraw these rows…' })).toHaveLength(1) // only the standing one
    expect(calls.map((c) => c.path)).toContain('/trace/c1/statements?withdrawn=1')
    expect(screen.getByText(/Bank and exchange statements · 1/)).toBeTruthy() // the count is of standing imports
  })

  it('offers no withdrawal to a caller who has not signed in', async () => {
    api(() => statements([STANDING], { can_withdraw: false }))
    render(<StatementPanel result={{ case_id: 'c1' }} />)
    await screen.findByText(/Victim statement \(test\)/)
    expect(screen.queryByRole('button', { name: /Withdraw/ })).toBeNull()
  })

  it("shows the server's refusal and leaves the import listed", async () => {
    api(() => statements([STANDING]), {
      '/trace/c1/statements/s1/withdraw': { status: 409, body: { detail: 'This import was already withdrawn on 2026-11-14.' } },
    })
    render(<StatementPanel result={{ case_id: 'c1' }} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Withdraw these rows…' }))
    await userEvent.type(screen.getByLabelText(/Why is it withdrawn/), 'Duplicate')
    await userEvent.click(screen.getByRole('button', { name: 'Withdraw' }))
    expect((await screen.findByRole('alert')).textContent).toContain('already withdrawn')
    expect(screen.getByText(/Victim statement \(test\)/)).toBeTruthy()
  })
})

describe('withdrawing a saved CDR summary', () => {
  const SUMMARY = { import_id: 'x1', title: 'CDR (test)', row_count: 1, created_at: '2026-11-14T10:00:00Z', withdrawn: null,
    rows: [{ kind: 'imei', value: '000000000000011', events: 3, first: '2026-03-01', last: '2026-03-03' }] }
  const cdr = (imports, more = {}) => ({ enabled: true, imports, rows_max: 200, check_max: 50, withdrawn_count: 0, can_withdraw: true, ...more })

  it('sends the reason to the CDR route and announces it', async () => {
    let withdrawn = false
    const calls = api(() => (withdrawn ? cdr([], { withdrawn_count: 1 }) : cdr([SUMMARY])), {
      '/trace/c1/cdr/x1/withdraw': { body: { ...SUMMARY, withdrawn: GONE.withdrawn } },
    })
    render(<MemoryRouter><CdrPanel result={{ case_id: 'c1' }} /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: 'Withdraw this summary…' }))
    await userEvent.type(screen.getByLabelText(/Why is it withdrawn/), 'Wrong CDR file')
    withdrawn = true
    await userEvent.click(screen.getByRole('button', { name: 'Withdraw' }))
    expect(await screen.findByText(/Summary withdrawn; it stays in the case record/)).toBeTruthy()
    expect(calls.find((c) => c.method === 'POST')).toEqual({ method: 'POST', path: '/trace/c1/cdr/x1/withdraw', body: { reason: 'Wrong CDR file' } })
    expect(screen.queryByText(/CDR \(test\)/)).toBeNull()
  })
})
