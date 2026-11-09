import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import BulkIntake from './BulkIntake'

const VICTIM = '0x' + '11'.repeat(20)
const SUSPECT = '0x' + '22'.repeat(20)

function api(post) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    calls.push({ method, url: String(url), body: init.body && JSON.parse(init.body) })
    if (method === 'POST') return new Response(JSON.stringify(post.body), { status: post.status })
    return new Response(JSON.stringify({ count: 0, batches: [] }), { status: 200 })
  }))
  return calls
}

async function paste(text) {
  const user = userEvent.setup()
  render(<MemoryRouter><BulkIntake defaultOpen /></MemoryRouter>)
  await user.click(screen.getByLabelText('Complaints CSV'))
  await user.paste(text)
  return user
}

afterEach(() => vi.unstubAllGlobals())

describe('Bulk intake checks the file before it sends anything (3-0, 3-1)', () => {
  it('lists a ragged line by its file line and disables Run', async () => {
    const calls = api({ status: 202, body: { batch_id: 'b1' } })
    await paste(`Acknowledgement No,Victim wallet,Wallet Address\nA-1,${VICTIM},${SUSPECT}\nA-2,PS Cyber, Blr,${VICTIM},${SUSPECT}\n`)
    expect(screen.getByRole('alert')).toHaveTextContent(/Line 3: has 5 cells; the header has 3/)
    expect(screen.getByRole('button', { name: 'Run batch' })).toBeDisabled()
    expect(screen.queryByRole('table', { name: 'Rows to trace' })).not.toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('refuses a file with two possible address columns', async () => {
    api({ status: 202, body: { batch_id: 'b1' } })
    await paste(`Wallet,Crypto Address\n${VICTIM},${SUSPECT}\n`)
    expect(screen.getByRole('alert')).toHaveTextContent("Line 1: Two columns could be the suspect's address")
    expect(screen.getByRole('button', { name: 'Run batch' })).toBeDisabled()
  })

  it('shows the mapping and every row with the full address before Run', async () => {
    const calls = api({ status: 202, body: { batch_id: 'b1' } })
    const user = await paste(`Ack No,Wallet Address,Suspect Wallet Address,Network\n31911250012345; PS Cyber Blr,${VICTIM},${SUSPECT},ethereum\n`)
    expect(screen.getByTestId('bulk-mapping')).toHaveTextContent("address ← 'Suspect Wallet Address' (column 3)")
    expect(screen.getByTestId('bulk-mapping')).toHaveTextContent("not used: 'Wallet Address'")
    const table = screen.getByRole('table', { name: 'Rows to trace' })
    expect(table).toHaveTextContent(SUSPECT)
    expect(table).toHaveTextContent('31911250012345; PS Cyber Blr')
    expect(table).not.toHaveTextContent(VICTIM)
    await user.click(screen.getByRole('button', { name: 'Run batch of 1' }))
    const post = calls.find((c) => c.method === 'POST')
    expect(post.body.rows).toEqual([{ reference: '31911250012345; PS Cyber Blr', address: SUSPECT, chain: 'ethereum' }])
  })

  it('names the file line of a row the server refuses', async () => {
    api({ status: 400, body: { detail: '1 row cannot be traced as written.', row_errors: [{ row: 2, error: 'Ethereum Mainnet has no traceable asset \'XYZ\'.' }] } })
    const user = await paste(`reference,suspect address,asset\n\nA-1,${SUSPECT},ETH\n\nA-2,${SUSPECT},XYZ\n`)
    await user.click(screen.getByRole('button', { name: 'Run batch of 2' }))
    expect(await screen.findByText(/Line 5: Ethereum Mainnet has no traceable asset/)).toBeInTheDocument()
  })
})
