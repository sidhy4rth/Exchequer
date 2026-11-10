import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import BulkIntake from './BulkIntake'
import TraceForm from './TraceForm'
import WatchPanel from './WatchPanel'
import { forgetSignIn } from './CaseRefField'
import TraceView from '../routes/TraceView'
import recordings from '../../../backend/data/recorded_demos.json'

// Every place a signed-in officer can start provider spending lets them give
// the case reference the server asks for (backend/app/case_refs.py): a trace
// link or Home search (the confirmation card), Re-trace of a case kept under
// none, the Evidence tab's recheck and a watch. Officer states stub GET /auth/me.
const OFFICER = { id: 2, name: 'Om Officer', role: 'officer', unit: { id: 1, name: 'Cyber Cell North' }, must_change_password: false }
const REF = 'FIR 0457/2026'
const ADDR = '0x' + '7c'.repeat(20)
const demo = recordings.find((r) => r.demo === 11)

/** fetch answering "METHOD /path"; records each call with its JSON body. */
function serve(routes, me = OFFICER) {
  const calls = []
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const path = String(url).replace(/^\/api/, '').split('?')[0]
    calls.push({ method, path, url: String(url), body: init.body ? JSON.parse(init.body) : undefined })
    if (path === '/auth/me') return me instanceof Promise ? me.then((m) => new Response(JSON.stringify(m))) : new Response(JSON.stringify(me))
    const hit = routes[`${method} ${path}`]
    if (!hit) return new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 })
    return new Response(JSON.stringify(hit.body), { status: hit.status ?? 200 })
  }))
  return calls
}

function at(entry) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/trace/:address" element={<TraceView />} />
        <Route path="/case/:caseId" element={<TraceView />} />
        <Route path="/demo/:demoNo" element={<TraceView />} />
      </Routes>
    </MemoryRouter>,
  )
}

const JOB = { 'POST /trace/jobs': { status: 202, body: { job_id: 'j1', status: 'running', progress: { stage: 'walking' } } },
  'GET /trace/jobs/j1': { body: { job_id: 'j1', status: 'running', progress: { stage: 'walking', hop: 1 } } } }

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); forgetSignIn() })

describe('a trace link or Home search opened by an officer', () => {
  it('asks for the case reference on the confirmation card and sends it in the body only', async () => {
    const user = userEvent.setup()
    const calls = serve(JOB)
    at(`/trace/${ADDR}?chain=ethereum&asset=ETH&depth=3&direction=outgoing`)
    const field = await screen.findByLabelText('Case reference')
    const run = screen.getByRole('button', { name: 'Run this trace' })
    expect(run).toBeDisabled()
    await user.type(field, REF)
    await user.click(run)
    await screen.findByRole('button', { name: 'Stop this trace' })
    const post = calls.find((c) => c.method === 'POST')
    expect(post.body.case_ref).toBe(REF)
    expect(calls.every((c) => !c.url.includes('0457'))).toBe(true)
  })

  it('shows a demo visitor no field', async () => {
    serve(JOB, { demo: true })
    at(`/trace/${ADDR}?chain=ethereum&asset=ETH&depth=3&direction=outgoing`)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run this trace' })).toBeEnabled())
    expect(screen.queryByLabelText('Case reference')).not.toBeInTheDocument()
  })
})

describe('Re-trace by an officer', () => {
  it('of a case kept under no reference asks first, with the field, instead of a refusal', async () => {
    const user = userEvent.setup()
    const calls = serve({ 'GET /trace/case-1': { body: { ...demo.result, case_id: 'case-1', created_at: demo.recorded_at } }, ...JOB })
    at('/case/case-1')
    await user.click(await screen.findByRole('button', { name: /Re-trace/ }))
    expect(await screen.findByRole('region', { name: 'Run this trace?' })).toBeInTheDocument()
    expect(screen.getByLabelText('Case reference')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })
})

describe("the Evidence tab's recheck by an officer", () => {
  it('takes a case reference when the case holds none, and sends it', async () => {
    const user = userEvent.setup()
    const calls = serve({
      'GET /demos/recorded/11': { body: { ...demo.result, created_at: demo.recorded_at, recorded_demo: 11 } },
      'GET /trace/demo-11/recheck': { body: { case_id: null, checked_at: null, transfers: [] } },
      'POST /trace/demo-11/recheck': { body: { case_id: null, checked_at: null, cited: 1, checked: 0, counts: {}, transfers: [] } },
    })
    at('/demo/11?tab=evidence')
    const reread = await screen.findByRole('button', { name: 'Re-read from a second provider' })
    const field = await screen.findByLabelText('Case reference')
    expect(reread).toBeDisabled()
    await user.type(field, REF)
    await user.click(reread)
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ case_ref: REF }))
  })
})

describe('a watch added by an officer', () => {
  const result = { address: ADDR, chain: 'ethereum', asset: 'ETH', direction: 'outgoing', case_id: null }

  it('takes a case reference when the case holds none, and sends it', async () => {
    const user = userEvent.setup()
    const calls = serve({ 'GET /watches': { body: { watches: [] } }, 'POST /watches': { status: 201, body: {} } })
    render(<MemoryRouter><WatchPanel result={result} /></MemoryRouter>)
    const field = await screen.findByLabelText('Case reference')
    const watch = screen.getByRole('button', { name: 'Watch' })
    expect(watch).toBeDisabled()
    await user.type(field, REF)
    await user.click(watch)
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body.case_ref).toBe(REF))
  })

  it("needs none of its own on an officer's case kept under one", async () => {
    serve({ 'GET /watches': { body: { watches: [] } } })
    render(<MemoryRouter><WatchPanel result={{ ...result, intake: { case_ref: REF } }} /></MemoryRouter>)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Watch' })).toBeEnabled())
    expect(screen.queryByLabelText('Case reference')).not.toBeInTheDocument()
  })
})

describe('before GET /auth/me has answered', () => {
  it('keeps Start trace disabled, so no officer starts one without a reference', async () => {
    const user = userEvent.setup()
    let answer
    const me = new Promise((resolve) => { answer = resolve })
    serve({ 'GET /trace/intake': { body: { payments: false } }, 'GET /demos/recorded': { body: { demos: [] } } }, me)
    const health = { status: 'ok', default_chain: 'ethereum', chains: { ethereum: { key: 'ethereum', name: 'Ethereum', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }] } } }
    render(<MemoryRouter><TraceForm health={health} /></MemoryRouter>)
    await user.type(await screen.findByLabelText('Wallet the victim paid'), ADDR)
    expect(screen.getByRole('button', { name: /^start trace/i })).toBeDisabled()
    answer({ demo: true })
    await waitFor(() => expect(screen.getByRole('button', { name: /^start trace/i })).toBeEnabled())
  })
})

describe("Bulk intake: each complaint's own reference", () => {
  async function paste(csv) {
    const calls = serve({ 'GET /batches': { body: { count: 0, batches: [] } }, 'POST /batches': { status: 202, body: { batch_id: 'b1' } } })
    const user = userEvent.setup()
    render(<MemoryRouter><BulkIntake defaultOpen /></MemoryRouter>)
    await user.click(screen.getByLabelText('Complaints CSV'))
    await user.paste(csv)
    return { calls, user }
  }

  it('needs no batch reference when every row carries its own', async () => {
    const { calls, user } = await paste(`reference,address,chain\nNCRP-2026-0001,${ADDR},ethereum\nNCRP-2026-0002,0x${'8d'.repeat(20)},ethereum\n`)
    const run = screen.getByRole('button', { name: 'Run batch of 2' })
    await waitFor(() => expect(run).toBeEnabled())
    expect(screen.queryByLabelText('Case reference')).not.toBeInTheDocument()
    await user.click(run)
    expect(calls.find((c) => c.method === 'POST').body).not.toHaveProperty('case_ref')
  })

  it('asks for one only for the rows without, and says so', async () => {
    await paste(`reference,address,chain\nNCRP-2026-0001,${ADDR},ethereum\n,0x${'8d'.repeat(20)},ethereum\n`)
    await screen.findByLabelText('Case reference')
    expect(screen.getByText(/1 row has no reference of its own/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run batch of 2' })).toBeDisabled()
  })
})
