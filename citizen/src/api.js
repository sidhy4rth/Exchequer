// The one place the site talks to its server: its own /api/ functions
// (citizen/api/), on the same origin, as the content policy allows. Every
// call carries X-Citizen, which the functions require, and the session
// cookie. An answer is {ok: true, status, data} or {ok: false, status,
// error, retryAfter?}, where error is words to show as they are.
const OFFLINE = 'We could not reach the site. Check your connection and try again.'
const SORRY = 'Something went wrong. Please try again later.'

async function call(path, body) {
  const init = { method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
    headers: { 'X-Citizen': '1' } }
  if (body) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  let res
  try {
    res = await fetch(`/api/${path}`, init)
  } catch {
    return { ok: false, status: 0, error: OFFLINE }
  }
  let data = null
  try { data = await res.json() } catch { /* a gateway's page, not ours */ }
  if (res.ok && data && typeof data === 'object') return { ok: true, status: res.status, data }
  const wait = Number(res.headers.get('Retry-After'))
  return { ok: false, status: res.status, error: typeof data?.error === 'string' ? data.error : SORRY,
    ...(wait > 0 ? { retryAfter: wait } : {}) }
}

export const sendComplaint = (pack) => call('complaints', pack)
export const signIn = (ncrp, code) => call('session', { ncrp, code })
export const myCase = () => call('my-case')
export const sendMessage = (text) => call('messages', { body: text })
export const signOut = () => call('logout', {})
export const checkPayment = (network, hash) => call(`payment?${new URLSearchParams({ network, hash })}`)

/** The networks the payment lookup reads, by the name hash.js gives them. */
export const NETWORK_KEYS = { Tron: 'tron', Ethereum: 'ethereum', 'BNB Smart Chain': 'bsc', Polygon: 'polygon',
  Arbitrum: 'arbitrum' }

/** "in about 4 minutes", for a Retry-After in seconds. */
export function waitText(seconds) {
  if (!(seconds > 0)) return 'a little later'
  if (seconds <= 60) return 'in about a minute'
  if (seconds < 3600) return `in about ${Math.ceil(seconds / 60)} minutes`
  return 'in about an hour'
}

/** The server's words, with how long to wait when it said. */
export const refusal = (res) => (res.retryAfter ? `${res.error} You can try again ${waitText(res.retryAfter)}.` : res.error)

export const NCRP_NEEDED = 'Give the NCRP acknowledgement number you got from 1930 or cybercrime.gov.in: 8 to 20 '
  + 'letters and digits.'

/** "2,500" or "1,00,000.25" for an amount as written, exactly: it is never rounded. */
export function amountText(amount) {
  const text = String(amount ?? '')
  const parts = /^(\d+)(\.\d+)?$/.exec(text)
  return parts ? BigInt(parts[1]).toLocaleString('en-IN') + (parts[2] ?? '') : text
}

/** The NCRP number as the server reads it, or '' when it cannot be one. */
export function ncrpShape(text) {
  const plain = text.replace(/[\s-]/g, '').toUpperCase()
  return /^[A-Z0-9]{8,20}$/.test(plain) ? plain : ''
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "9 Nov 2026, 10:30 am IST" for a time the server sent (India has no summer time). */
export function istTime(iso) {
  const t = new Date(Date.parse(iso) + 5.5 * 3600 * 1000)
  if (Number.isNaN(t.getTime())) return ''
  const hour = t.getUTCHours() % 12 || 12
  const minute = String(t.getUTCMinutes()).padStart(2, '0')
  return `${t.getUTCDate()} ${MONTHS[t.getUTCMonth()]} ${t.getUTCFullYear()}, ${hour}:${minute} `
    + `${t.getUTCHours() < 12 ? 'am' : 'pm'} IST`
}

/** The same time as a date-and-time field takes it, in India's time. */
export const istField = (iso) => new Date(Date.parse(iso) + 5.5 * 3600 * 1000).toISOString().slice(0, 16)
