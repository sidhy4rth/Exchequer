import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import Home from './Home'
import { stubFetch } from '../test/setup'

// R10 on the console: stored cases show the band, never the decimal; the
// status line counts chains in the right number.
const oneChain = {
  status: 'ok',
  default_chain: 'ethereum',
  chains: { ethereum: { key: 'ethereum', name: 'Ethereum', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }] } },
}
const stored = {
  count: 1,
  cases: [{ case_id: 'c1', address: '0x' + 'ab'.repeat(20), chain: 'ethereum', asset: 'ETH', exchange: 'Binance',
            confidence: 0.875, node_count: 4, flag_count: 0, created_at: '2026-11-04T10:00:00+00:00' }],
}

describe('the console in bands (R10)', () => {
  it('shows a stored case as High, not 0.88, and says 1 CHAIN', async () => {
    stubFetch({ '/chains': { body: oneChain }, '/cases': { body: stored }, '/exchanges': { body: {} },
                '/risk-labels': { body: {} }, '/demos/recorded': { body: { demos: [] } } })
    render(<MemoryRouter initialEntries={['/']}><Routes><Route path="/" element={<Home />} /></Routes></MemoryRouter>)
    expect(await screen.findByText(/SYSTEM OPERATIONAL · 1 CHAIN ·/)).toBeInTheDocument()
    expect(await screen.findByText('High')).toBeInTheDocument()
    expect(screen.queryByText('0.88')).not.toBeInTheDocument()
  })
})
