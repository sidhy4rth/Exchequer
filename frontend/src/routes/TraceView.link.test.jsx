import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import TraceView from './TraceView'

// A /trace/<address>?… link alone must not start a trace under whoever opens
// it (3-5): it shows what it would run and waits for a click.
const ADDR = '0x' + '7c'.repeat(20)
const HASH = '0x' + 'ab'.repeat(32)

function api() {
  const posts = []
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const path = String(url).replace(/^\/api/, '').split('?')[0]
    const method = init.method || 'GET'
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status })
    if (method === 'POST' && path === '/trace/jobs') { posts.push(JSON.parse(init.body)); return json({ job_id: 'j1', status: 'running', progress: { stage: 'walking' } }, 202) }
    if (method === 'GET' && path === '/trace/jobs/j1') return json({ job_id: 'j1', status: 'running', progress: { stage: 'walking', hop: 1 } })
    return json({ detail: 'not stubbed' }, 404)
  }))
  return posts
}

function open(entry) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes><Route path="/trace/:address" element={<TraceView />} /></Routes>
    </MemoryRouter>,
  )
}

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })

describe('a trace link asks before it runs (3-5)', () => {
  it('shows a confirmation card and sends nothing', async () => {
    const posts = api()
    open(`/trace/${ADDR}?chain=ethereum&asset=ETH&depth=6&direction=outgoing`)
    const card = await screen.findByRole('region', { name: 'Run this trace?' })
    expect(card).toHaveTextContent(ADDR)
    expect(card).toHaveTextContent('6 hops')
    expect(screen.getByRole('checkbox', { name: /Stop after/ })).toBeChecked()
    await new Promise((r) => setTimeout(r, 20))
    expect(posts).toEqual([])
    expect(screen.queryByRole('button', { name: 'Stop this trace' })).not.toBeInTheDocument()
  })

  it('Run starts the trace with a 90 s cap', async () => {
    const posts = api()
    open(`/trace/${ADDR}?chain=ethereum&asset=ETH&depth=6&direction=outgoing`)
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Run this trace' }))
    await screen.findByRole('button', { name: 'Stop this trace' })
    expect(posts).toHaveLength(1)
    expect(posts[0]).toMatchObject({ address: ADDR, max_depth: 6, time_budget_seconds: 90 })
  })

  it('a trace started from the form runs at once', async () => {
    const posts = api()
    open({ pathname: `/trace/${ADDR}`, search: '?chain=ethereum&asset=ETH&depth=3&direction=outgoing', state: { startedHere: true } })
    await screen.findByRole('button', { name: 'Stop this trace' })
    expect(screen.queryByRole('region', { name: 'Run this trace?' })).not.toBeInTheDocument()
    expect(posts).toHaveLength(1)
    expect(posts[0]).not.toHaveProperty('time_budget_seconds')
  })

  it('sends a payment the officer found by search as found by officer search', async () => {
    const posts = api()
    const other = 'cd'.repeat(32)
    open({ pathname: `/trace/${ADDR}`, search: `?chain=ethereum&asset=ETH&depth=3&direction=outgoing&pay=${HASH},0x${other}&found=${HASH}`, state: { startedHere: true } })
    await screen.findByRole('button', { name: 'Stop this trace' })
    expect(posts[0].payments).toEqual([{ tx_hash: HASH, found_by: 'officer_search' }, { tx_hash: `0x${other}` }])
  })

  it('clamps depth and budget from the link to what the backend takes', async () => {
    const posts = api()
    open(`/trace/${ADDR}?chain=ethereum&depth=99&budget=5000`)
    const card = await screen.findByRole('region', { name: 'Run this trace?' })
    expect(card).toHaveTextContent('6 hops')
    expect(card).toHaveTextContent('10:00')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Run this trace' }))
    await screen.findByRole('button', { name: 'Stop this trace' })
    expect(posts[0]).toMatchObject({ max_depth: 6, time_budget_seconds: 600 })
  })

  it('reads depth=abc as 4', async () => {
    api()
    open(`/trace/${ADDR}?chain=ethereum&depth=abc`)
    expect(await screen.findByRole('region', { name: 'Run this trace?' })).toHaveTextContent('4 hops')
  })

  it('lists the payment hashes from the link and refuses a malformed one', async () => {
    api()
    open(`/trace/${ADDR}?chain=ethereum&pay=${HASH},zzzz`)
    const card = await screen.findByRole('region', { name: 'Run this trace?' })
    expect(card).toHaveTextContent('Payments')
    expect(card).toHaveTextContent('not a transaction hash')
    expect(screen.getByRole('button', { name: 'Run this trace' })).toBeDisabled()
  })

  it('a job this tab already runs re-attaches without the card', async () => {
    const posts = api()
    sessionStorage.setItem(`exchequer-job:${JSON.stringify({ address: ADDR, max_depth: 2, chain: 'ethereum', asset: 'ETH', direction: 'outgoing' })}`, 'j1')
    open(`/trace/${ADDR}?chain=ethereum&asset=ETH&depth=2&direction=outgoing`)
    await screen.findByRole('button', { name: 'Stop this trace' })
    expect(screen.queryByRole('region', { name: 'Run this trace?' })).not.toBeInTheDocument()
    expect(posts).toEqual([])
  })
})
