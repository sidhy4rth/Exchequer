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

const recordings = { demos: [{ demo: 6, recorded_at: '2026-10-14T16:44:03+00:00', address: '0x00000000072d54638c2c2a3da3f715360269eea1', exchange: 'Binance', confidence: 0.875 }] }

async function renderHome() {
  stubFetch({ '/health': { body: health }, '/cases': { body: { count: 0, cases: [] } }, '/exchanges': { body: {} }, '/risk-labels': { body: {} }, '/demos/recorded': { body: recordings } })
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/trace/:address" element={<Landed />} />
        <Route path="/demo/:n" element={<Landed />} />
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

  it('offers the recording of a loaded demo, and drops it once the form is edited', async () => {
    const user = userEvent.setup()
    await renderHome()
    await user.selectOptions(screen.getByLabelText('Load a verified example'), '06')
    const link = await screen.findByRole('link', { name: /open it as recorded/i })
    expect(link).toHaveTextContent('2026-10-14')
    await user.type(screen.getByLabelText('Reported wallet address'), 'f')
    expect(screen.queryByRole('link', { name: /open it as recorded/i })).not.toBeInTheDocument()
  })

  it('opens the recording without starting a trace', async () => {
    const user = userEvent.setup()
    await renderHome()
    await user.selectOptions(screen.getByLabelText('Load a verified example'), '06')
    await user.click(await screen.findByRole('link', { name: /open it as recorded/i }))
    expect(screen.getByTestId('landed')).toHaveTextContent('/demo/6')
  })

  it('offers no recording for a demo that has none', async () => {
    const user = userEvent.setup()
    await renderHome()
    await user.selectOptions(screen.getByLabelText('Load a verified example'), '01')
    expect(screen.queryByRole('link', { name: /open it as recorded/i })).not.toBeInTheDocument()
  })
})
