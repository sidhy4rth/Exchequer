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
  return <p data-testid="landed" data-ncrp={state?.ncrpAck ?? ''}>{pathname + search}</p>
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
  })

  it('go into the trace URL; the NCRP number does not', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: true })
    await user.type(screen.getByLabelText('Reported wallet address'), ADDR)
    await user.type(await screen.findByLabelText(/payment transaction hash/i), HASH)
    await user.type(screen.getByLabelText(/NCRP acknowledgement number/i), '31911250012345')
    await user.click(screen.getByRole('button', { name: /^trace$/i }))
    const landed = screen.getByTestId('landed')
    expect(landed).toHaveTextContent(`/trace/${ADDR}?chain=ethereum&asset=ETH&depth=4&direction=outgoing&pay=${HASH}`)
    expect(landed.textContent).not.toContain('31911250012345')
    expect(landed).toHaveAttribute('data-ncrp', '31911250012345')
  })

  it('refuse a malformed hash and keep the button disabled', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: true })
    await user.type(screen.getByLabelText('Reported wallet address'), ADDR)
    await user.type(await screen.findByLabelText(/payment transaction hash/i), '0x1234')
    expect(screen.getByText(/Not a valid Ethereum transaction hash/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^trace$/i })).toBeDisabled()
  })

  it('are only offered for a trace of where the money went', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: true })
    await screen.findByLabelText(/payment transaction hash/i)
    await user.selectOptions(screen.getByLabelText('Trace direction'), 'incoming')
    expect(screen.queryByLabelText(/payment transaction hash/i)).not.toBeInTheDocument()
  })
})

describe('parseHashes', () => {
  it('splits on lines, commas and spaces, and drops repeats', () => {
    expect(parseHashes(` a\nb, c  a \n`)).toEqual(['a', 'b', 'c'])
  })
})
