import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import TraceForm, { parseHashes } from './TraceForm'
import { stubFetch } from '../test/setup'

const health = {
  status: 'ok',
  default_chain: 'ethereum',
  chains: {
    ethereum: { key: 'ethereum', name: 'Ethereum', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }] },
    tron: { key: 'tron', name: 'Tron', ready: true, address_family: 'tron', assets: [{ symbol: 'USDT' }] },
  },
}
const ADDR = '0x' + 'ab'.repeat(20)
const HASH = '0x' + 'cd'.repeat(32)

function Landed() {
  const { pathname, search, state } = useLocation()
  return <p data-testid="landed" data-ncrp={state?.ncrpAck ?? ''} data-victim={state?.victimAddress ?? ''} data-started={String(state?.startedHere === true)}>{pathname + search}</p>
}

async function renderForm({ payments }) {
  stubFetch({ '/trace/intake': { body: { payments, lookup_limit: 1000 } }, '/demos/recorded': { body: { demos: [] } } })
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<TraceForm health={health} />} />
        <Route path="/trace/:address" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByLabelText('Reported wallet address')
}

describe('payment hashes on the trace form (R1)', () => {
  it('are not offered when the backend has them switched off', async () => {
    await renderForm({ payments: false })
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.queryByLabelText(/payment transaction hash/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Victim's payments/ })).not.toBeInTheDocument()
  })

  it('go into the trace URL; the NCRP number does not', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: true })
    await user.type(screen.getByLabelText('Reported wallet address'), ADDR)
    await user.click(await screen.findByRole('button', { name: /Victim's payments/ }))
    await user.type(await screen.findByLabelText(/payment transaction hash/i), HASH)
    await user.type(screen.getByLabelText(/NCRP acknowledgement number/i), '31911250012345')
    await user.click(screen.getByRole('button', { name: /^trace$/i }))
    const landed = screen.getByTestId('landed')
    expect(landed).toHaveTextContent(`/trace/${ADDR}?chain=ethereum&asset=ETH&depth=4&direction=outgoing&pay=${HASH}`)
    expect(landed.textContent).not.toContain('31911250012345')
    expect(landed).toHaveAttribute('data-ncrp', '31911250012345')
    // The trace page runs a trace started here at once; a pasted link asks first (3-5).
    expect(landed).toHaveAttribute('data-started', 'true')
  })

  it('refuse a malformed hash and keep the button disabled', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: true })
    await user.type(screen.getByLabelText('Reported wallet address'), ADDR)
    await user.click(await screen.findByRole('button', { name: /Victim's payments/ }))
    await user.type(await screen.findByLabelText(/payment transaction hash/i), '0x1234')
    expect(screen.getByText(/Not a valid Ethereum transaction hash/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^trace$/i })).toBeDisabled()
  })

  it('are only offered for a trace of where the money went', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: true })
    await user.click(await screen.findByRole('button', { name: /Victim's payments/ }))
    await screen.findByLabelText(/payment transaction hash/i)
    await user.selectOptions(screen.getByLabelText('Trace direction'), 'incoming')
    expect(screen.queryByLabelText(/payment transaction hash/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Victim's payments/ })).not.toBeInTheDocument()
  })
})

describe('only an open payments panel is sent (5-6, 5-5, 5-3)', () => {
  const VICTIM = '0x' + '11'.repeat(20)

  async function withPayment(user, hash = HASH) {
    await renderForm({ payments: true })
    await user.type(screen.getByLabelText('Reported wallet address'), ADDR)
    await user.click(await screen.findByRole('button', { name: /Victim's payments/ }))
    await user.type(await screen.findByLabelText(/payment transaction hash/i), hash)
  }

  it('collapsing the payments panel stops sending the hashes', async () => {
    const user = userEvent.setup()
    await withPayment(user)
    await user.type(screen.getByLabelText(/NCRP acknowledgement number/i), '31911250012345')
    await user.click(screen.getByRole('button', { name: /Victim's payments/ }))
    await user.click(screen.getByRole('button', { name: /^trace$/i }))
    const landed = screen.getByTestId('landed')
    expect(landed.textContent).not.toContain('pay=')
    expect(landed).toHaveAttribute('data-ncrp', '')
  })

  it('a bad hash in a collapsed panel does not disable Trace', async () => {
    const user = userEvent.setup()
    await withPayment(user, '0x1234')
    expect(screen.getByRole('button', { name: /^trace$/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /Victim's payments/ }))
    expect(screen.queryByText(/Not a valid Ethereum transaction hash/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^trace$/i })).toBeEnabled()
  })

  it('the pill counts hashes that will not be sent, and an open panel says how many are attached', async () => {
    const user = userEvent.setup()
    await withPayment(user)
    expect(screen.getByRole('status')).toHaveTextContent('1 payment attached')
    await user.click(screen.getByRole('button', { name: /Victim's payments/ }))
    expect(screen.getByRole('button', { name: /Victim's payments/ })).toHaveTextContent("Victim's payments · 1 entered, not sent")
    expect(screen.queryByText(/payment attached/)).not.toBeInTheDocument()
  })

  it('an NCRP number that is not 10 to 20 digits shows a warning and disables Trace', async () => {
    const user = userEvent.setup()
    await withPayment(user)
    await user.type(screen.getByLabelText(/NCRP acknowledgement number/i), 'FIR 12')
    expect(screen.getByText(/An NCRP acknowledgement number is 10 to 20 digits/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^trace$/i })).toBeDisabled()
  })

  it("the victim's wallet travels in the navigation state, never the URL", async () => {
    const user = userEvent.setup()
    await withPayment(user)
    await user.type(screen.getByLabelText(/Victim's own wallet/i), VICTIM)
    await user.click(screen.getByRole('button', { name: /^trace$/i }))
    const landed = screen.getByTestId('landed')
    expect(landed.textContent).not.toContain(VICTIM)
    expect(landed).toHaveAttribute('data-victim', VICTIM)
  })

  it("refuses a victim's wallet that is malformed or is the reported wallet", async () => {
    const user = userEvent.setup()
    await withPayment(user)
    const box = screen.getByLabelText(/Victim's own wallet/i)
    await user.type(box, '0x12')
    expect(screen.getByText(/The victim's wallet is not a valid Ethereum address/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^trace$/i })).toBeDisabled()
    await user.clear(box)
    await user.type(box, ADDR.toUpperCase().replace('0X', '0x'))
    expect(screen.getByText(/The victim's wallet is the reported wallet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^trace$/i })).toBeDisabled()
  })
})

describe('parseHashes', () => {
  it('splits on lines, commas and spaces, and drops repeats', () => {
    expect(parseHashes(` a\nb, c  a \n`)).toEqual(['a', 'b', 'c'])
  })
})
