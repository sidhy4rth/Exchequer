import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TraceView from './TraceView'
import recordings from '../../../backend/data/recorded_demos.json'
import { stubFetch } from '../test/setup'

// Demo 11: Tron USDT, frozen by Tether, Binance-Hot 7 at score 0.80 (high),
// with one amount-split pattern. Traced from the address alone.
const demo = recordings.find((r) => r.demo === 11)

async function openDemo11() {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  stubFetch({ '/demos/recorded/11': { body: { ...demo.result, case_id: null, created_at: demo.recorded_at, recorded_demo: 11 } } })
  render(
    <MemoryRouter initialEntries={['/demo/11']}>
      <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
    </MemoryRouter>,
  )
  await screen.findByText(/Recorded demo 11/)
}

describe('how sure the case is (R10)', () => {
  it('leads with the band, and says it is not a probability', async () => {
    await openDemo11()
    expect(demo.result.confidence).toBeCloseTo(0.8)
    const big = document.querySelector('.sure .big')
    expect(big).toHaveTextContent('High')
    expect(big.textContent).not.toMatch(/\d/)
    expect(screen.getByText('a rule of three inputs, not a probability')).toBeInTheDocument()
  })

  it('keeps the exact score in the working, beside the band rule', async () => {
    await openDemo11()
    const working = document.querySelector('.score-working')
    expect(working).toHaveTextContent('Score 0.80')
    expect(working).toHaveTextContent('read the band, not the decimal')
  })

  it('folds patterns into hints with their measured hit rates', async () => {
    await openDemo11()
    expect(screen.getByText('Hints · 1')).toBeInTheDocument()
    expect(screen.queryByText(/^Patterns ·/)).not.toBeInTheDocument()
    expect(screen.getByText(/6 of 32 documented fraud wallets and 5 of 47 ordinary ones/)).toBeInTheDocument()
    expect(screen.queryByText(/strength/)).not.toBeInTheDocument()
    expect(document.querySelector('details.card.sec:not([open]) .hint-rate')).not.toBeNull()
  })

  it('marks an address-only trace as exploratory', async () => {
    await openDemo11()
    expect(screen.getByText(/Exploratory · traced from the address/)).toBeInTheDocument()
  })
})

describe('three tracing rules side by side (R4)', () => {
  async function openWith(methods) {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    stubFetch({ '/demos/recorded/11': { body: { ...demo.result, tracing_methods: methods, case_id: null, created_at: demo.recorded_at, recorded_demo: 11 } } })
    render(
      <MemoryRouter initialEntries={['/demo/11']}>
        <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
      </MemoryRouter>,
    )
    await screen.findByText(/Recorded demo 11/)
  }

  it('shows the range and the figure a letter states', async () => {
    await openWith({ figures: { fifo: 40, prorata: 20, libr: 0 }, range: { low: 0, high: 40 }, conservative: 0, conservative_method: 'libr' })
    const line = document.querySelector('.method-range')
    expect(line).toHaveTextContent('By tracing rule')
    expect(line).toHaveTextContent('FIFO 40')
    expect(line).toHaveTextContent('LIBR 0')
    expect(line).toHaveTextContent('a letter states the smallest')
  })

  it('says so when the rules agree', async () => {
    await openWith({ figures: { fifo: 5, prorata: 5, libr: 5 }, range: { low: 5, high: 5 }, conservative: 5, conservative_method: 'fifo' })
    expect(document.querySelector('.method-range')).toHaveTextContent('All 3 tracing rules agree')
  })

  it('shows nothing when the trace ran pro-rata alone', async () => {
    await openWith(null)
    expect(document.querySelector('.method-range')).toBeNull()
  })
})

describe('what the walk did not follow (R5)', () => {
  it('states the untraced value under scope and evidence', async () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    const untraced = [{ address: demo.result.address, counterparties: 2, value_native: 6, share_of_outflow: 0.13, rule: 'top_n' }]
    stubFetch({ '/demos/recorded/11': { body: { ...demo.result, untraced, case_id: null, created_at: demo.recorded_at, recorded_demo: 11 } } })
    render(
      <MemoryRouter initialEntries={['/demo/11']}>
        <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
      </MemoryRouter>,
    )
    await screen.findByText(/Recorded demo 11/)
    const row = document.querySelector('.exclusion.untraced')
    expect(row).toHaveTextContent('sent on but not followed')
    expect(row).toHaveTextContent('2 smaller destinations of 1 address')
    expect(row).toHaveTextContent('the ten largest')
  })
})
