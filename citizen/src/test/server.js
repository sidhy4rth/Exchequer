import { vi } from 'vitest'

/**
 * A stand-in for the citizen functions: `routes` maps "METHOD /api/name" to
 * [status, body, headers] or to a function of (request) returning one. Each
 * answer is a fresh Response, as the real server's would be. Anything not
 * listed answers 404. The mock records every call, with its body parsed.
 */
export function fakeServer(routes) {
  const calls = []
  const fetch = vi.fn(async (url, init = {}) => {
    const method = init.method ?? 'GET'
    const [path, query = ''] = String(url).split('?')
    const req = { url: String(url), path, method, query: Object.fromEntries(new URLSearchParams(query)),
      headers: init.headers ?? {}, credentials: init.credentials, body: init.body ? JSON.parse(init.body) : undefined }
    calls.push(req)
    const route = routes[`${method} ${path}`]
    const answer = typeof route === 'function' ? await route(req) : route
    if (answer instanceof Error) throw answer
    const [status, body, headers = {}] = answer ?? [404, { error: 'No such address.' }]
    return new Response(typeof body === 'string' ? body : JSON.stringify(body),
      { status, headers: { 'Content-Type': 'application/json', ...headers } })
  })
  fetch.calls = calls
  vi.stubGlobal('fetch', fetch)
  return fetch
}

export const OFFLINE = new TypeError('Failed to fetch')
