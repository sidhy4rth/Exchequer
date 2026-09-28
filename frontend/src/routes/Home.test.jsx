import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import Home from './Home'
import { stubFetch } from '../test/setup'

const health = {
  status: 'ok',
  default_chain: 'ethereum',
  chains: {
    ethereum: { key: 'ethereum', name: 'Ethereum', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }] },
    tron: { key: 'tron', name: 'Tron', ready: true, address_family: 'tron', assets: [{ symbol: 'USDT' }] },
  },
}

function Landed() {
  const { pathname, search } = useLocation()
  return <p data-testid="landed">{pathname + search}</p>
}

async function renderHome() {
  stubFetch({ '/health': { body: health }, '/cases': { body: { count: 0, cases: [] } }, '/exchanges': { body: {} }, '/risk-labels': { body: {} } })
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/trace/:address" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByText(/SYSTEM OPERATIONAL/)
}

describe('the trace form', () => {
  it('flags a malformed address and does not start a trace', async () => {
    const user = userEvent.setup()
    await renderHome()
    const field = screen.getByLabelText('Reported wallet address')
    await user.type(field, '0x1234')
    await user.keyboard('{Enter}')
    await user.tab()
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: /trace/i })).toBeDisabled()
    expect(screen.queryByTestId('landed')).not.toBeInTheDocument()
  })

  it('opens a shareable trace URL for a valid address', async () => {
    const user = userEvent.setup()
    await renderHome()
    const addr = '0x' + 'ab'.repeat(20)
    await user.type(screen.getByLabelText('Reported wallet address'), `  ${addr} {Enter}`)
    expect(screen.getByTestId('landed')).toHaveTextContent(
      `/trace/${addr}?chain=ethereum&asset=ETH&depth=4&direction=outgoing`)
  })

  it('holds a Tron address to the Tron format, not the EVM one', async () => {
    const user = userEvent.setup()
    await renderHome()
    await user.selectOptions(screen.getByLabelText('Blockchain'), 'tron')
    const field = screen.getByLabelText('Reported wallet address')
    await user.type(field, '0x' + 'ab'.repeat(20))
    await user.tab()
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: /trace/i })).toBeDisabled()
  })
})
