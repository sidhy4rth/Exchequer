import { describe, expect, it, vi } from 'vitest'
import { fetchCase, fetchRecheck, runRecheck, traceAddress } from './api'
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

  it('reads a stored case by its id once the job no longer holds the result', async () => {
    const address = '0x' + '5a'.repeat(20)
    sessionStorage.setItem(`exchequer-job:${JSON.stringify({ address })}`, 'j3')
    server([
      ['GET', /\/trace\/jobs\/j3$/, () => [200, { job_id: 'j3', status: 'done', progress: {}, case_id: 'c3' }]],
      ['GET', /\/trace\/c3$/, () => [200, { case_id: 'c3', exchange: 'Binance' }]],
    ])
    const { runTrace } = await import('./api')
    expect(await runTrace({ address })).toEqual({ case_id: 'c3', exchange: 'Binance' })
  })

  it('never keeps the NCRP number in sessionStorage, and still re-attaches after a reload', async () => {
    const address = '0x' + '6'.repeat(40)
    const posted = []
    let resolveJob
    const finished = new Promise((r) => { resolveJob = r })
    globalThis.fetch = vi.fn(async (url, init = {}) => {
      if ((init.method || 'GET') === 'POST') {
        posted.push(JSON.parse(init.body))
        return new Response(JSON.stringify({ job_id: 'j9', status: 'running', progress: {} }), { status: 202 })
      }
      await finished
      return new Response(JSON.stringify({ job_id: 'j9', status: 'done', progress: {}, result: { case_id: 'c9' } }))
    })
    const { runTrace } = await import('./api')
    const victim = '0x' + 'b1c7'.repeat(10)
    const running = runTrace({ address, payments: ['0x' + 'a'.repeat(64)], ncrpAck: '31911250012345', victimAddress: victim })
    const stored = () => Array.from({ length: sessionStorage.length }, (_, i) => sessionStorage.key(i))
      .map((k) => k + sessionStorage.getItem(k)).join('|')
    await vi.waitFor(() => expect(stored()).toContain('j9'))
    expect(posted[0].ncrp_ack).toBe('31911250012345')  // the server still gets it
    expect(stored()).not.toContain('31911250012345')
    expect(posted[0].victim_address).toBe(victim)  // the victim's wallet is a particular too
    expect(stored()).not.toContain(victim)
    resolveJob()
    expect(await running).toEqual({ case_id: 'c9' })
  })

  // A stand-in for the browser's EventSource: the test fires its events.
  class FakeSource {
    static CLOSED = 2
    static last = null
    constructor(url) { this.url = url; this.readyState = 0; this.listeners = {}; FakeSource.last = this }
    addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn) }
    close() { this.readyState = 2 }
  }

  it('falls back to polling when the event stream closes after two errors', async () => {
    // The server restarted: the stream drops (error, CONNECTING), the
    // reconnect gets a 404 (error, CLOSED) and the browser stops retrying.
    vi.stubGlobal('EventSource', FakeSource)
    FakeSource.last = null
    server([['POST', /\/trace\/jobs$/, () => [202, { job_id: 'j-lost', status: 'running', progress: {} }]]])
    const { runTrace } = await import('./api')
    const outcome = runTrace({ address: '0x' + '6'.repeat(40) }).then(() => 'resolved', (e) => e.message)
    await vi.waitFor(() => expect(FakeSource.last).not.toBeNull())
    const source = FakeSource.last
    source.onerror()
    source.readyState = 2
    source.onerror()
    expect(await outcome).toMatch(/lost/)
  })

  it('falls back to polling when the stream goes silent', async () => {
    vi.useFakeTimers()
    try {
      vi.stubGlobal('EventSource', FakeSource)
      FakeSource.last = null
      const calls = server([
        ['POST', /\/trace\/jobs$/, () => [202, { job_id: 'j-quiet', status: 'running', progress: {} }]],
        ['GET', /\/trace\/jobs\/j-quiet$/, () => [200, { job_id: 'j-quiet', status: 'done', progress: {}, result: { case_id: 'c9' } }]],
      ])
      const { runTrace } = await import('./api')
      const outcome = runTrace({ address: '0x' + '7'.repeat(40) })
      await vi.waitFor(() => expect(FakeSource.last).not.toBeNull())
      // A heartbeat keeps the stream alive; then nothing at all for 45 s.
      await vi.advanceTimersByTimeAsync(30_000)
      FakeSource.last.listeners.heartbeat.forEach((fn) => fn({ data: '{}' }))
      await vi.advanceTimersByTimeAsync(40_000)
      expect(calls.some((c) => c.startsWith('GET') && c.includes('j-quiet'))).toBe(false)
      await vi.advanceTimersByTimeAsync(6_000)
      expect(await outcome).toEqual({ case_id: 'c9' })
      expect(FakeSource.last.readyState).toBe(2)
    } finally {
      vi.useRealTimers()
    }
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

describe("the victim's wallet (5-3)", () => {
  it('goes to the backend with the payments, and never without them', async () => {
    const bodies = []
    globalThis.fetch = vi.fn(async (url, init = {}) => {
      if ((init.method || 'GET') === 'POST') { bodies.push(JSON.parse(init.body)); return new Response(JSON.stringify({ job_id: `v${bodies.length}`, status: 'running' }), { status: 202 }) }
      return new Response(JSON.stringify({ status: 'done', result: { case_id: 'c' } }), { status: 200 })
    })
    const { runTrace } = await import('./api')
    const victim = '0x' + '1'.repeat(40)
    const hash = '0x' + 'c'.repeat(64)
    await runTrace({ address: '0x' + '8'.repeat(40), payments: [hash], ncrpAck: '31911250012345', victimAddress: victim })
    await runTrace({ address: '0x' + '9'.repeat(40), victimAddress: victim })
    expect(bodies[0]).toMatchObject({ payments: [{ tx_hash: hash }], ncrp_ack: '31911250012345', victim_address: victim })
    expect(bodies[1]).not.toHaveProperty('victim_address')
  })
})

describe('the demo code', () => {
  it('is sent only once the visitor has entered one', async () => {
    const { fetchCases } = await import('./api')
    const { forgetDemoCode, rememberDemoCode } = await import('./demoCode')
    const fetch = stubFetch({ '/cases': { body: { count: 0, cases: [] } } })
    await fetchCases()
    expect(new Headers(fetch.mock.calls[0][1].headers).has('X-Exchequer-Demo-Code')).toBe(false)
    rememberDemoCode('river-otter-42')
    await fetchCases()
    expect(new Headers(fetch.mock.calls[1][1].headers).get('X-Exchequer-Demo-Code')).toBe('river-otter-42')
    forgetDemoCode()
    await fetchCases()
    expect(new Headers(fetch.mock.calls[2][1].headers).has('X-Exchequer-Demo-Code')).toBe(false)
  })

  it('sends the pass instead of the code once the site has issued one', async () => {
    const { fetchCases } = await import('./api')
    const { forgetDemoCode, rememberDemoCode, rememberDemoPass } = await import('./demoCode')
    const fetch = stubFetch({ '/cases': { body: { count: 0, cases: [] } } })
    rememberDemoCode('river-otter-42')
    rememberDemoPass('v1.1999999999.nonce.mac')
    await fetchCases()
    const sent = new Headers(fetch.mock.calls[0][1].headers)
    expect(sent.get('X-Exchequer-Demo-Pass')).toBe('v1.1999999999.nonce.mac')
    expect(sent.has('X-Exchequer-Demo-Code')).toBe(false)
    expect(sessionStorage.getItem('exchequer-demo-code')).toBeNull()
    forgetDemoCode()
  })

  it('forgets a pass the site no longer accepts, and nothing else', async () => {
    const { apiFetch } = await import('./api/client')
    const { demoPass, forgetDemoCode, rememberDemoPass } = await import('./demoCode')
    rememberDemoPass('v1.1.nonce.mac')
    stubFetch({ '/trace/jobs/j1': { status: 403, body: { detail: 'Only the browser that started this trace can stop it.' } } })
    await apiFetch('/api/trace/jobs/j1', { method: 'DELETE' })
    expect(demoPass()).toBe('v1.1.nonce.mac')  // a 403 from the route itself
    stubFetch({ '/trace/jobs': { status: 403, body: { detail: 'expired' }, headers: { 'X-Exchequer-Demo-Pass-Invalid': '1' } } })
    await apiFetch('/api/trace/jobs', { method: 'POST' })
    expect(demoPass()).toBe('')
    forgetDemoCode()
  })
})

// POST/GET /trace/{id}/recheck (routes/recheck.py). A server without them
// answers 404 (GET) or 405 (POST): null, so the page hides the column.
describe('the second-provider recheck', () => {
  const kept = { case_id: 'c1', checked_at: '2026-11-10T05:00:00+00:00', transfers: [{ hash: 'h', status: 'matches' }] }

  it('reads the last recheck, and runs one with a POST', async () => {
    const fetch = stubFetch({ '/trace/c1/recheck': { body: kept } })
    expect(await fetchRecheck('c1')).toEqual(kept)
    expect(await runRecheck('c1')).toEqual(kept)
    expect(fetch.mock.calls.map(([, init]) => init?.method ?? 'GET')).toEqual(['GET', 'POST'])
  })

  it.each([404, 405])('reads a %s as no recheck on this server', async (status) => {
    stubFetch({ '/trace/c1/recheck': { status, body: { detail: 'Not Found' } } })
    expect(await fetchRecheck('c1')).toBeNull()
    expect(await runRecheck('c1')).toBeNull()
  })

  it("carries the server's reason when a recheck is refused", async () => {
    stubFetch({ '/trace/c1/recheck': { status: 503, body: { detail: "This site has used today's TronScan allowance." } } })
    await expect(runRecheck('c1')).rejects.toThrow("today's TronScan allowance")
  })
})
