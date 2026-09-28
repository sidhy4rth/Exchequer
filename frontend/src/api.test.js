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
