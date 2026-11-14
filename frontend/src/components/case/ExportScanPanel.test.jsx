import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ExportScanPanel, { seedLine } from './ExportScanPanel'

// The export scan on the Evidence tab: hidden unless the server offers it, the
// file read here, and only counts sent. Values from DEMO.md and the contract
// fixtures; the twelve words are the list's first, not a valid mnemonic.
const EVM = '0x7c3e9bab6715e4040f013e865b193b0209642e36'
const TRON = 'THWYhwUQnBcKpwSxaXjqv18RPtSoK4C5Ph'
const TX_TRON = '657b48486605d40ee51f6e36df243ed0fb9a1460b5a53f61080d51eaadf6b1d5'
const SEED = 'abandon ability able about above absent absorb abstract absurd abuse access accident'

function api(routes) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const [path] = String(url).replace(/^\/api/, '').split('?')
    let body = init.body
    try { body = JSON.parse(body) } catch { /* none */ }
    calls.push({ method, path, body })
    const hit = routes[`${method} ${path}`]
    if (!hit) return new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 })
    return new Response(JSON.stringify(hit.body ?? {}), { status: hit.status ?? 200, headers: { 'Content-Type': 'application/json' } })
  }))
  return calls
}

const ON = {
  'GET /trace/c1/export-scan': { body: { case_id: 'c1', enabled: true } },
  'POST /trace/c1/export-scan': { status: 201, body: { case_id: 'c1', recorded: true } },
}
const show = () => render(<MemoryRouter><ExportScanPanel result={{ case_id: 'c1' }} /></MemoryRouter>)

afterEach(() => { vi.unstubAllGlobals() })

describe('ExportScanPanel', () => {
  it('stays hidden while the server does not offer the scan', async () => {
    const calls = api({})
    const { container } = show()
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(container).toBeEmptyDOMElement()
  })

  it('lists what it found, hides the seed words, and sends counts only', async () => {
    const calls = api(ON)
    show()
    const input = await screen.findByLabelText('Export file')
    const text = `from,message\nRahul,"pay ${TRON}"\nRahul,"tx ${TX_TRON}"\nme,"${SEED}"\nme,"or ${EVM}"\n`
    await userEvent.upload(input, new File([text], 'chats.csv', { type: 'text/csv' }))

    expect(await screen.findByText(/chats\.csv: 5 lines read/)).toBeInTheDocument()
    expect(screen.getByText('12 BIP-39 words at line 4, hidden')).toBeInTheDocument()
    for (const word of SEED.split(' ')) expect(document.body.textContent.toLowerCase()).not.toMatch(new RegExp(`\\b${word}\\b`))

    expect(screen.getByText(TRON, { selector: 'td' })).toBeInTheDocument()
    expect(screen.getByText(EVM, { selector: 'td' })).toBeInTheDocument()
    expect(screen.getByText(TX_TRON, { selector: 'td' })).toBeInTheDocument()
    expect(screen.getAllByRole('link').map((l) => [l.textContent, l.getAttribute('href')])).toEqual([
      [`Trace ${TRON}`, `/trace/${TRON}?chain=tron&asset=USDT`],
      [`Trace ${EVM}`, `/trace/${EVM}?chain=ethereum&asset=ETH`],
      [`Trace from this payment ${TX_TRON}`, `/trace/new?pay=${TX_TRON}&chain=tron`],
    ])

    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1))
    const sent = calls.find((c) => c.method === 'POST')
    expect(sent.body).toEqual({ lines: 5, bytes: text.length, addresses: 2, tx_hashes: 1, seed_runs: 1 })
    const everything = JSON.stringify(calls)
    for (const value of [TRON, EVM, TX_TRON, 'abandon', 'chats.csv']) expect(everything).not.toContain(value)
  })

  it('says so when a file holds none of these', async () => {
    api(ON)
    show()
    await userEvent.upload(await screen.findByLabelText('Export file'), new File(['just a note about lunch\n'], 'note.txt'))
    expect(await screen.findByText('Nothing of these kinds was found in this file.')).toBeInTheDocument()
  })

  it('calls a 64-hex value what it may be, not a transaction hash, and names its tables', async () => {
    api(ON)
    show()
    await userEvent.upload(await screen.findByLabelText('Export file'), new File([`pay ${TRON}\nsha256 ${TX_TRON}\n`], 'n.txt'))
    expect(await screen.findByText(/1 64-hex value \(may be a transaction hash\)/)).toBeInTheDocument()
    expect(screen.queryByText(/transaction hashes?\b(?! \()/)).toBeNull()
    expect(screen.getByRole('table', { name: 'Addresses' })).toBeInTheDocument()
    const hashes = screen.getByRole('table', { name: '64-hex values' })
    expect(hashes.textContent).toMatch(/may be a Tron transaction hash, a file's SHA-256 or a private key/)
  })

  it('lists two seed runs on the same line once each, without a React key clash', async () => {
    api(ON)
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
    show()
    await userEvent.upload(await screen.findByLabelText('Export file'), new File([`${SEED} qq ${SEED}\n`], 's.txt'))
    expect(await screen.findAllByText('12 BIP-39 words at line 1, hidden')).toHaveLength(2)
    expect(errors.mock.calls.flat().join(' ')).not.toMatch(/same key/)
    errors.mockRestore()
  })

  it('says a seed run spanning lines by its first and last line', () => {
    expect(seedLine({ line: 2, endLine: 13, words: 12 })).toBe('12 BIP-39 words at lines 2 to 13, hidden')
  })
})
