import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CryptoSummary, { NCRP_BLANK, withNcrp } from './CryptoSummary'

// The crypto summary for CFCFRMS (backend sop_summary.py): shown only when
// the server offers it, the officer's answer sent as one word, and the NCRP
// number filled in here, never sent.
const TEXT = `CRYPTO SUMMARY FOR CFCFRMS: SOP 9.4 (VASPs)\n\n${NCRP_BLANK}\n\n3. Is this exchange on CFCFRMS? No\n`
const NCRP = '31234567890123'

function server({ offered = true } = {}) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const path = String(url).replace(/^\/api/, '')
    calls.push({ method, path, body: init.body ?? null })
    if (!offered) return new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 })
    if (method === 'GET' && path === '/sop-summary') return new Response(JSON.stringify({ enabled: true }), { status: 200 })
    if (method === 'POST' && path === '/trace/c1/sop-summary') return new Response(TEXT, { status: 200 })
    return new Response(JSON.stringify({ detail: 'not stubbed' }), { status: 404 })
  }))
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('the crypto summary panel', () => {
  it('shows nothing with the flag off', async () => {
    const calls = server({ offered: false })
    const { container } = render(<CryptoSummary result={{ case_id: 'c1' }} />)
    await vi.waitFor(() => expect(calls).toHaveLength(1))
    expect(container).toBeEmptyDOMElement()
    expect(calls[0].path).toBe('/sop-summary')
  })

  it('shows nothing on a recorded example, and does not ask', async () => {
    const calls = server()
    const { container } = render(<CryptoSummary result={{ case_id: null }} />)
    expect(container).toBeEmptyDOMElement()
    expect(calls).toHaveLength(0)
  })

  it("sends only the officer's answer and copies the text with the typed NCRP number filled in", async () => {
    const calls = server()
    const user = userEvent.setup()
    render(<CryptoSummary result={{ case_id: 'c1' }} />)
    await user.click(await screen.findByText('Crypto summary for CFCFRMS'))
    await user.click(screen.getByRole('radio', { name: 'No' }))
    await user.type(screen.getByLabelText(/NCRP acknowledgement number/), NCRP)
    await user.click(screen.getByRole('button', { name: 'Copy the summary' }))
    expect(await screen.findByText(/^Copied\./)).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST')
    expect(JSON.parse(post.body)).toEqual({ on_cfcfrms: 'no' })
    expect(JSON.stringify(calls)).not.toContain(NCRP) // never in a URL or a body
    const copied = await navigator.clipboard.readText()
    expect(copied).toContain(`NCRP acknowledgement no.: ${NCRP}`)
    expect(copied).not.toContain(NCRP_BLANK)
    expect(screen.getByLabelText("The crypto summary's text")).toHaveValue(copied)
  })

  it('leaves the NCRP line blank when none is typed, and notes a number of an unusual shape', async () => {
    server()
    const user = userEvent.setup()
    render(<CryptoSummary result={{ case_id: 'c1' }} />)
    await user.click(await screen.findByText('Crypto summary for CFCFRMS'))
    const box = screen.getByLabelText(/NCRP acknowledgement number/)
    await user.type(box, '5123')
    expect(box).toHaveAccessibleDescription(/usually 14 digits starting with 2 or 3/)
    await user.clear(box)
    await user.click(screen.getByRole('button', { name: 'Copy the summary' }))
    await screen.findByText(/^Copied\./)
    expect(await navigator.clipboard.readText()).toContain(NCRP_BLANK)
  })
})

describe('withNcrp', () => {
  it('fills the blank only with a typed number', () => {
    expect(withNcrp(TEXT, '  ')).toBe(TEXT)
    expect(withNcrp(TEXT, ` ${NCRP} `)).toContain(`NCRP acknowledgement no.: ${NCRP}\n`)
  })
})
