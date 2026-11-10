import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import BulkIntake from './BulkIntake'
import TraceForm from './TraceForm'
import { forgetSignIn } from './CaseRefField'
import { stubFetch } from '../test/setup'

// A signed-in officer works only under a case reference (backend/app/case_refs.py):
// the New trace form and Bulk intake ask for one. Demo visitors see neither.
const health = {
  status: 'ok', default_chain: 'ethereum',
  chains: { ethereum: { key: 'ethereum', name: 'Ethereum', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }] } },
}
const ADDR = '0x' + 'ab'.repeat(20)
const OFFICER = { id: 2, name: 'Om Officer', role: 'officer', unit: { id: 1, name: 'Cyber Cell North' }, must_change_password: false }
const REF = 'FIR 0457/2026'

function Landed() {
  const { pathname, search, state } = useLocation()
  return <p data-testid="landed" data-ref={state?.caseRef ?? ''}>{pathname + search}</p>
}

async function renderForm(me) {
  stubFetch({ '/trace/intake': { body: { payments: false } }, '/demos/recorded': { body: { demos: [] } }, ...(me ? { '/auth/me': { body: me } } : {}) })
  render(
    <MemoryRouter>
      <Routes>
        <Route path="/" element={<TraceForm health={health} />} />
        <Route path="/trace/:address" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByLabelText('Wallet the victim paid')
}

afterEach(() => { vi.unstubAllGlobals(); forgetSignIn() })

describe('the case reference on New trace', () => {
  it('asks a signed-in officer for one, masked, and starts only with it', async () => {
    const user = userEvent.setup()
    await renderForm(OFFICER)
    const field = await screen.findByLabelText('Case reference')
    expect(field).toHaveClass('masked')
    expect(field).toBeRequired()
    expect(screen.getByText(/FIR, NCRP or GD number · never in links or logs/)).toBeInTheDocument()
    await user.type(screen.getByLabelText('Wallet the victim paid'), ADDR)
    expect(screen.getByRole('button', { name: /^start trace/i })).toBeDisabled()
    await user.type(field, 'FIR')
    expect(screen.getByRole('button', { name: /^start trace/i })).toBeDisabled()
    await user.type(field, ' 0457/2026')
    await user.click(screen.getByRole('button', { name: 'Show the case reference' }))
    expect(field).not.toHaveClass('masked')
    await user.click(screen.getByRole('button', { name: /^start trace/i }))
    const landed = screen.getByTestId('landed')
    expect(landed.dataset.ref).toBe(REF) // in the navigation state
    expect(landed.textContent).not.toContain('0457') // never in the URL
  })

  it('shows no field to a demo visitor, nor when the server has no accounts', async () => {
    for (const me of [{ demo: true }, null]) {
      await renderForm(me)
      expect(screen.queryByLabelText('Case reference')).not.toBeInTheDocument()
      document.body.innerHTML = ''
      forgetSignIn()
    }
  })
})

describe('the case reference on Bulk intake', () => {
  it('is required of an officer and sent with the batch', async () => {
    const calls = []
    vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
      const method = init.method || 'GET'
      calls.push({ method, url: String(url), body: init.body && JSON.parse(init.body) })
      if (String(url).endsWith('/auth/me')) return new Response(JSON.stringify(OFFICER))
      if (method === 'POST') return new Response(JSON.stringify({ batch_id: 'b1' }), { status: 202 })
      return new Response(JSON.stringify({ count: 0, batches: [] }))
    }))
    const user = userEvent.setup()
    render(<MemoryRouter><BulkIntake defaultOpen /></MemoryRouter>)
    await user.click(screen.getByLabelText('Complaints CSV'))
    await user.paste(`address,chain\n${ADDR},ethereum\n`)
    const run = screen.getByRole('button', { name: 'Run batch of 1' })
    await screen.findByLabelText('Case reference')
    expect(run).toBeDisabled()
    await user.type(screen.getByLabelText('Case reference'), REF)
    await user.click(run)
    expect(calls.find((c) => c.method === 'POST').body.case_ref).toBe(REF)
  })
})
