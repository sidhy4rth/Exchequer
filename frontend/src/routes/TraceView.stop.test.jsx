import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TraceView from './TraceView'

// A running trace can be stopped by the browser that started it
// (DELETE /trace/jobs/{id}); the slot it held is then free for the next one.
describe('stopping a running trace', () => {
  it('offers Stop while the trace runs, and shows it stopped', async () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    let stopped = false
    const calls = []
    vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
      const path = String(url).replace(/^\/api/, '').split('?')[0]
      const method = init.method || 'GET'
      calls.push(`${method} ${path}`)
      const json = (body, status = 200) => new Response(JSON.stringify(body), { status })
      if (method === 'POST' && path === '/trace/jobs') return json({ job_id: 'j1', status: 'running', progress: { stage: 'walking' } }, 202)
      if (method === 'DELETE' && path === '/trace/jobs/j1') { stopped = true; return json({ job_id: 'j1', stopping: true }, 202) }
      if (method === 'GET' && path === '/trace/jobs/j1') {
        return json(stopped
          ? { job_id: 'j1', status: 'failed', progress: { stage: 'failed' }, error: { status_code: 409, detail: 'The trace was stopped by the person who started it.' } }
          : { job_id: 'j1', status: 'running', progress: { stage: 'walking', hop: 1, level_size: 2, level_read: 1 } })
      }
      return json({ detail: 'not stubbed' }, 404)
    }))
    render(
      <MemoryRouter initialEntries={[{ pathname: '/trace/0x' + '1'.repeat(40), state: { startedHere: true } }]}>
        <Routes><Route path="/trace/:address" element={<TraceView />} /></Routes>
      </MemoryRouter>,
    )
    const stop = await screen.findByRole('button', { name: 'Stop this trace' })
    await userEvent.setup().click(stop)
    expect(calls).toContain('DELETE /trace/jobs/j1')
    expect(await screen.findByText(/stopped by the person who started it/, {}, { timeout: 4000 })).toBeInTheDocument()
  })
})
