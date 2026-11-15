import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TraceView from './TraceView'
import recordings from '../../../backend/data/recorded_demos.json'
import wording from '../../../backend/tests/fixtures/store_basis_lines.json'
import { stubFetch } from '../test/setup'

// Demo 11 (Binance, from a label file: no attribution_basis), and the same
// case as if its address had come from a label-store deposit row (#336).
const demo = recordings.find((r) => r.demo === 11)
const deposit = wording.cases[1]

async function open(overrides = {}) {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  stubFetch({ '/demos/recorded/11': { body: { ...demo.result, case_id: null, created_at: demo.recorded_at, recorded_demo: 11, ...overrides } } })
  render(
    <MemoryRouter initialEntries={['/demo/11']}>
      <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
    </MemoryRouter>,
  )
  await screen.findByText(/Verified example 11/)
}

describe("the trace screen and a label-store row's basis", () => {
  it('shows nothing new for a case from a label file', async () => {
    expect(demo.result.matches.some((m) => m.attribution_basis)).toBe(false)
    await open()
    expect(document.querySelector('.store-basis')).toBeNull()
    expect(screen.queryByText(/in its own published address list/)).not.toBeInTheDocument()
  })

  it("shows a deposit row's basis under the address to ask the exchange about", async () => {
    const matches = demo.result.matches.map((m) => (m.address === demo.result.exchange_address
      ? { ...m, attribution_basis: deposit.basis } : m))
    await open({ matches, exchange: deposit.exchange, attribution_inferred: true })
    const group = screen.getByRole('group', { name: 'What this attribution stands on' })
    expect(document.querySelector('.answer .cite + .store-basis')).toBe(group)
    deposit.lines.forEach((line) => expect(group).toHaveTextContent(line))
  })
})
