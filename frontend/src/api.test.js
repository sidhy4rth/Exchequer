import { describe, expect, it, vi } from 'vitest'
import { fetchCase, traceAddress } from './api'
import { stubFetch } from './test/setup'

describe('error messages', () => {
  it("carries the backend's own detail when it gives one", async () => {
    stubFetch({ '/trace/abc': { status: 404, body: { detail: 'Case abc was pruned.' } } })
    await expect(fetchCase('abc')).rejects.toThrow('Case abc was pruned.')
  })

  it('joins FastAPI validation errors into one sentence', async () => {
    stubFetch({ '/trace/abc': { status: 422, body: { detail: [{ msg: 'bad depth' }, { msg: 'bad chain' }] } } })
    await expect(fetchCase('abc')).rejects.toThrow('bad depth; bad chain')
  })

  it('falls back to a plain explanation of a rate limit', async () => {
    stubFetch({ '/trace/abc': { status: 429, body: 'not json' } })
    await expect(fetchCase('abc')).rejects.toThrow(/rate limiting us/)
  })
})

describe('traceAddress', () => {
  const addr = '0x' + 'a'.repeat(40)

  it('says the backend is unreachable rather than showing a fetch TypeError', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    await expect(traceAddress(addr, 3, 'ethereum', 'ETH')).rejects.toThrow(/Cannot reach the Exchequer backend/)
  })

  it('sends one request for two identical traces in flight', async () => {
    const fetch = stubFetch({ '/trace': { body: { case_id: 'c1' } } })
    const [a, b] = await Promise.all([
      traceAddress(addr, 3, 'ethereum', 'ETH', 'outgoing'),
      traceAddress(addr, 3, 'ethereum', 'ETH', 'outgoing'),
    ])
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(a).toEqual(b)
  })

  it('lets the same trace run again once the first has finished', async () => {
    const fetch = stubFetch({ '/trace': { body: { case_id: 'c1' } } })
    await traceAddress(addr, 3, 'ethereum', 'ETH')
    await traceAddress(addr, 3, 'ethereum', 'ETH')
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('leaves out options that were not chosen, so the backend default stands', async () => {
    const fetch = stubFetch({ '/trace': { body: {} } })
    await traceAddress(addr)
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ address: addr })
  })
})

describe('owner key', () => {
  it('sends the same well-formed owner key on every request', async () => {
    const seen = []
    globalThis.fetch = vi.fn(async (url, init) => {
      seen.push(init?.headers?.['X-Exchequer-Owner'])
      return new Response(JSON.stringify({ count: 0, cases: [] }), { status: 200 })
    })
    const { fetchCases, fetchHealth } = await import('./api')
    await fetchCases(5)
    await fetchHealth().catch(() => {})
    expect(seen).toHaveLength(2)
    expect(seen[0]).toMatch(/^[A-Za-z0-9_-]{43}$/)
    expect(seen[1]).toBe(seen[0])
  })
})

describe('background traces', () => {
  function server(routes) {
    const calls = []
    globalThis.fetch = vi.fn(async (url, init = {}) => {
      const method = init.method || 'GET'
      calls.push(`${method} ${url}`)
      const handler = routes.find(([m, re]) => m === method && re.test(url))
      if (!handler) return new Response('{}', { status: 404 })
      const [status, body] = handler[2](calls)
      return new Response(JSON.stringify(body), { status })
    })
    return calls
  }

  it('starts a job, reports progress and resolves with the result', async () => {
    const calls = server([
      ['POST', /\/trace\/jobs$/, () => [202, { job_id: 'j1', status: 'running', progress: { stage: 'starting' } }]],
      ['GET', /\/trace\/jobs\/j1$/, () => [200, { job_id: 'j1', status: 'done', progress: { stage: 'done' }, result: { case_id: 'c1' } }]],
    ])
    const { runTrace } = await import('./api')
    const seen = []
    const result = await runTrace({ address: '0x' + '3'.repeat(40) }, (s) => seen.push(s.progress.stage))
    expect(result).toEqual({ case_id: 'c1' })
    expect(seen[0]).toBe('starting')
    expect(calls.filter((c) => c.startsWith('POST'))).toHaveLength(1)
  })

  it('re-attaches to a job remembered from before a reload instead of starting another', async () => {
    const address = '0x' + '4'.repeat(40)
    sessionStorage.setItem(`exchequer-job:${JSON.stringify({ address })}`, 'j2')
    const calls = server([
      ['GET', /\/trace\/jobs\/j2$/, () => [200, { job_id: 'j2', status: 'done', progress: {}, result: { case_id: 'c2' } }]],
    ])
    const { runTrace } = await import('./api')
    expect(await runTrace({ address })).toEqual({ case_id: 'c2' })
    expect(calls.some((c) => c.startsWith('POST'))).toBe(false)
  })

  it('surfaces a failed job as an error with the backend detail', async () => {
    server([
      ['POST', /\/trace\/jobs$/, () => [202, { job_id: 'j3', status: 'running', progress: {} }]],
      ['GET', /\/trace\/jobs\/j3$/, () => [200, { job_id: 'j3', status: 'failed', progress: {}, error: { status_code: 502, detail: 'provider down' } }]],
    ])
    const { runTrace } = await import('./api')
    await expect(runTrace({ address: '0x' + '5'.repeat(40) })).rejects.toThrow('provider down')
  })
})
