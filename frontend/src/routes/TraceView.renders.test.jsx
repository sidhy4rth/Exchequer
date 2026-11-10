import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import TraceView from './TraceView'
import recordings from '../../../backend/data/recorded_demos.json'
import flow from '../test/victim-flow-11.json'
import { stubFetch } from '../test/setup'
import { victimFlowLayout } from '../components/case/victimFlowLayout'
import { timelineStats } from '../components/case/timelineStats'

// A dense case (1,500 transfers) once kept the page busy for about 90 s after
// it opened: the reveal re-rendered the whole case once per transfer, and
// each render redid the Flow layout and the Timeline. Only the short list of
// transfers that matter is revealed, and the tab bodies skip a render whose
// case has not changed.
vi.mock('../components/case/victimFlowLayout', async (actual) => {
  const real = await actual()
  return { ...real, victimFlowLayout: vi.fn(real.victimFlowLayout) }
})
vi.mock('../components/case/timelineStats', async (actual) => {
  const real = await actual()
  return { ...real, timelineStats: vi.fn(real.timelineStats) }
})

const demo = recordings.find((r) => r.demo === 11)

async function open(search = '') {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  stubFetch({ '/demos/recorded/11': { body: { ...demo.result, case_id: null, created_at: demo.recorded_at, recorded_demo: 11, victim_flow: flow } } })
  render(
    <MemoryRouter initialEntries={[`/demo/11${search}`]}>
      <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
    </MemoryRouter>,
  )
  await screen.findByText(/Verified example 11/)
  // Longer than the old reveal took for this case's 34 transfers.
  await new Promise((resolve) => setTimeout(resolve, 900))
}

afterEach(() => vi.clearAllMocks())

describe('opening a case', () => {
  it('works out the Flow layout once, not once per transfer revealed', async () => {
    await open()
    expect(demo.result.graph.edges.length).toBeGreaterThan(30)
    expect(victimFlowLayout.mock.calls.length).toBeLessThanOrEqual(3)
  })

  it('draws the Timeline once, not once per transfer revealed', async () => {
    await open('?tab=timeline')
    expect(screen.getByRole('tab', { selected: true })).toHaveTextContent('Timeline')
    expect(timelineStats.mock.calls.length).toBeLessThanOrEqual(3)
  })
})
