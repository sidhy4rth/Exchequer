import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SopSteps from './SopSteps'

// The CFCFRMS SOP steps (backend sop_steps.py): shown only when the server
// offers them, fetched only when opened, every quote with its section and page.
const STEPS = {
  note: 'The SOP\'s steps, quoted from one copy, for the officer to check.',
  source: 'MHA SOP for NCRP-CFCFRMS, copy dated 11 Feb 2026: https://example.invalid/sop.pdf',
  steps: [{ id: 'submit', title: 'The police officer submits the complaint to CFCFRMS',
    cites: [{ section: '§6.1(f)', page: 12, quote: 'she shall submit the complaint to CFCFRMS.' }],
    case: 'A step on the portal or with the bank: Exchequer cannot see the portal, so it shows nothing here.' }],
}

function server({ offered = true } = {}) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    const path = String(url).replace(/^\/api/, '')
    calls.push(path)
    if (!offered) return new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 })
    if (path === '/sop-steps') return new Response(JSON.stringify({ enabled: true }), { status: 200 })
    if (path === '/trace/c1/sop-steps') return new Response(JSON.stringify(STEPS), { status: 200 })
    return new Response(JSON.stringify({ detail: 'not stubbed' }), { status: 404 })
  }))
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('the SOP steps panel', () => {
  it('shows nothing with the flag off, and nothing on a recorded example', async () => {
    const calls = server({ offered: false })
    const { container } = render(<SopSteps result={{ case_id: 'c1' }} />)
    await vi.waitFor(() => expect(calls).toEqual(['/sop-steps']))
    expect(container).toBeEmptyDOMElement()
    const { container: demo } = render(<SopSteps result={{ case_id: null }} />)
    expect(demo).toBeEmptyDOMElement()
    expect(calls).toHaveLength(1)
  })

  it('reads the case only when opened, and shows each quote with its section and page', async () => {
    const calls = server()
    const user = userEvent.setup()
    render(<SopSteps result={{ case_id: 'c1' }} />)
    const summary = await screen.findByText('CFCFRMS SOP steps')
    expect(calls).toEqual(['/sop-steps'])
    await user.click(summary)
    expect(await screen.findByText('SOP §6.1(f), PDF page 12')).toBeInTheDocument()
    expect(screen.getByText(/she shall submit the complaint to CFCFRMS/)).toBeInTheDocument()
    expect(screen.getByText(/Exchequer cannot see the portal/)).toBeInTheDocument()
    expect(calls).toEqual(['/sop-steps', '/trace/c1/sop-steps'])
  })
})
