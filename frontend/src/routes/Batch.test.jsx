import { act, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Batch, { STALL_POLLS } from './Batch'

// The batch page polls while a batch runs. A batch that stopped moving
// (its server gone, a store that cannot be written) used to be polled every
// 3 s for as long as the tab stayed open.

const row = (n, extra = {}) => ({
  row: n, reference: '', address: '0x' + String(n).repeat(40), chain: 'ethereum', asset: 'ETH',
  status: 'pending', same_as: null, case_id: null, exchange: null, confidence: null, error: null, ...extra,
})

function stubBatches(next) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    calls.push(String(url))
    return new Response(JSON.stringify(next(calls.length)), { status: 200 })
  }))
  return calls
}

function show() {
  render(
    <MemoryRouter initialEntries={['/batch/b1']}>
      <Routes><Route path="/batch/:batchId" element={<Batch />} /></Routes>
    </MemoryRouter>,
  )
}

const running = (done) => ({
  batch_id: 'b1', name: 'Bank export', status: 'running', total: 3, done, failed: 0, interrupted: 0, pending: 3 - done,
  rows: [row(1, { status: done ? 'done' : 'running' }), row(2), row(3)], exchanges: [], shared_wallets: [],
})

async function poll(times) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  }
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('the batch page', () => {
  it('stops polling a batch that makes no progress', async () => {
    vi.useFakeTimers()
    const calls = stubBatches(() => running(0))
    show()
    await poll(STALL_POLLS + 20)
    expect(calls.length).toBe(STALL_POLLS + 1)
    expect(screen.getByText(/No row has finished for 10 minutes/)).toBeInTheDocument()
  })

  it('keeps polling while rows finish', async () => {
    vi.useFakeTimers()
    const calls = stubBatches((n) => running(n % 2))
    show()
    await poll(STALL_POLLS + 20)
    expect(calls.length).toBeGreaterThan(STALL_POLLS + 1)
    expect(screen.queryByText(/No row has finished for 10 minutes/)).toBeNull()
  })

  it('shows a repeated row as the same as the row it repeats', async () => {
    stubBatches(() => ({
      ...running(0),
      rows: [row(1, { status: 'running' }), row(2, { status: 'same', same_as: 1 })],
      total: 2,
    }))
    show()
    expect(await screen.findByText('same as row 1')).toBeInTheDocument()
  })
})
