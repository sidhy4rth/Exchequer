import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TraceView from '../../routes/TraceView'
import recordings from '../../../../backend/data/recorded_demos.json'
import { stubFetch } from '../../test/setup'

// The Timeline tab (pack 2-glass-05) on demo 11: the stat cards, the lane
// chart and its selected transfer above the blocks it already had.
const demo = recordings.find((r) => r.demo === 11)

async function openTimeline(overrides = {}) {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  stubFetch({ '/demos/recorded/11': { body: { ...demo.result, case_id: null, created_at: demo.recorded_at, recorded_demo: 11, ...overrides } } })
  render(
    <MemoryRouter initialEntries={['/demo/11?tab=timeline']}>
      <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
    </MemoryRouter>,
  )
  await screen.findByText(/Verified example 11/)
  return screen.getByRole('tabpanel')
}

describe('the Timeline tab', () => {
  it('opens with the four stat cards, worked from the case', async () => {
    const panel = await openTimeline()
    const cards = within(panel).getByRole('list', { name: 'When the money moved' })
    expect(within(cards).getAllByRole('listitem').map((c) => c.textContent)).toEqual([
      '69.6%left the wallet within 45 h',
      '3 h 26 mfrom hop 1 to Binance',
      '10 daysuntil the wallet was empty',
      '11 Sep 2026Tether froze both wallets',
    ])
  })

  it('leaves out a card with no data, and the list when none has any', async () => {
    const panel = await openTimeline({ statement: null, risk_matches: [], exchange: null })
    expect(within(panel).queryByRole('list', { name: 'When the money moved' })).not.toBeInTheDocument()
  })

  it('draws the lane chart and the selected transfer above the transfers feed', async () => {
    const panel = await openTimeline()
    const chart = within(panel).getByRole('listbox', { name: 'Every transfer, in IST' })
    const strip = within(panel).getByRole('region', { name: 'Selected transfer' })
    const feed = within(panel).getByText(/^Transfers that matter · /)
    expect(chart.compareDocumentPosition(feed) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(strip).toHaveTextContent('340 USDT')
    expect(within(panel).getByText(/^Wallet statement · USDT$/)).toBeInTheDocument()
  })
})
