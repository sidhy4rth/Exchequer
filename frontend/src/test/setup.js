import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import { resetAccount } from '../session'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  sessionStorage.clear()
  resetAccount() // the officer signed in by one test is never the next one's
})

/** A fetch stub answering by path; anything unlisted is a 404. */
export function stubFetch(routes) {
  const fetch = vi.fn(async (url) => {
    const path = String(url).replace(/^\/api/, '').split('?')[0]
    const hit = routes[path]
    if (!hit) return new Response(JSON.stringify({ detail: 'not stubbed' }), { status: 404 })
    const { status = 200, body, headers } = typeof hit === 'function' ? hit(url) : hit
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, headers })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}
