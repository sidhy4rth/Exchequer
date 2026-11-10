import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import indexHtml from '../index.html?raw'
import vercel from '../vercel.json'

const sources = import.meta.glob(['./**/*.{js,jsx}', '!./**/*.test.{js,jsx}'],
  { query: '?raw', import: 'default', eager: true })
// Vitest blanks CSS imports, even ?raw ones, so stylesheets are read from disk.
for (const file of Object.keys(import.meta.glob('./**/*.css'))) {
  sources[file] = readFileSync(fileURLToPath(new URL(file, import.meta.url)), 'utf8')
}
const shipped = [['index.html', indexHtml], ...Object.entries(sources)]
const tests = import.meta.glob('./**/*.test.{js,jsx}', { query: '?raw', import: 'default', eager: true })

describe('what the site loads and says', () => {
  it.each(shipped)('%s loads nothing from another origin', (_, text) => {
    // The only outside address is the official portal, as a link.
    const urls = text.match(/https?:\/\/[^\s'"`)<]+/g) ?? []
    expect(urls.filter((url) => url !== 'https://cybercrime.gov.in')).toEqual([])
  })

  it.each(shipped)('%s is English only and never names a contest', (_, text) => {
    expect(text).not.toMatch(/[ऀ-ॿ]/)
    expect(text).not.toMatch(/\bSIH\b|hackathon/i)
  })

  it.each(shipped.filter(([file]) => file !== './api.js'))('%s makes no network calls and sets no inline styles',
    (_, text) => {
      // Only api.js talks to the server, and style-src 'self' would block
      // style attributes.
      expect(text).not.toMatch(/\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon/)
      expect(text).not.toMatch(/\sstyle=/)
    })

  it('talks to this site\'s own /api/ only, from one place', () => {
    // default-src 'self': a call anywhere else would be blocked, and must
    // not be written in the first place.
    const api = sources['./api.js']
    const calls = [...api.matchAll(/\bfetch\s*\(([^,)]*)/g)].map((m) => m[1].trim())
    expect(calls).toEqual(['`/api/${path}`'])
    expect(api).not.toMatch(/XMLHttpRequest|WebSocket|EventSource|sendBeacon|https?:/)
  })

  it.each(shipped)('%s uses no regex lookbehind, which iPhones before iOS 16.4 cannot parse', (_, text) => {
    expect(text).not.toMatch(/\(\?<[=!]/)
  })

  it.each([...shipped, ...Object.entries(tests)])('%s has no invisible characters', (_, text) => {
    // Zero-width and direction marks hide what code says from a reviewer;
    // write them as escapes (\u200B) instead.
    expect(text).not.toMatch(/[\u00AD\u200B-\u200F\u202A-\u202E\u2060-\u2069\uFEFF]/)
  })

  it('serves IBM Plex from this site', () => {
    for (const face of ['sans/300', 'sans/400', 'sans/500', 'sans/600', 'mono/400', 'serif/600']) {
      expect(sources['./main.jsx']).toContain(`@fontsource/ibm-plex-${face}.css`)
    }
  })
})

describe('styles.css', () => {
  const [phone, laptop] = sources['./styles.css'].split('@media (min-width: 900px)')
  const px = (css, rule, prop) => Number(css.match(new RegExp(`\\n${rule} \\{[^}]*${prop}: (\\d+)px`))[1])

  it('keeps focused things clear of the phone tab bar, and not on a laptop', () => {
    // WCAG 2.4.11: the fixed bar must not hide what keyboard focus scrolls to.
    const bar = px(phone, '\\.tab', 'min-height') + 2 * px(phone, '\\.tabs', 'padding') + 2
    const clear = phone.match(/\nhtml \{[^}]*scroll-padding-bottom: calc\(var\(--tabs-bottom\) \+ (\d+)px\)/)
    expect(Number(clear?.[1])).toBeGreaterThanOrEqual(bar + 8)
    expect(phone).toMatch(/\n\.tabs \{[^}]*bottom: var\(--tabs-bottom\)/)
    expect(laptop).toMatch(/\n {2}html \{ scroll-padding-bottom: 0; \}/)
  })

  it('never hides the live region, so the check is announced', () => {
    // A role="status" region that is display:none until it fills in is often
    // not announced, by VoiceOver on iPhone in particular.
    const rules = [...sources['./styles.css'].matchAll(/([^{}]*)\{([^{}]*)\}/g)]
      .filter(([, selector]) => /\.result\b/.test(selector))
    expect(rules.length).toBeGreaterThan(0)
    for (const [rule] of rules) expect(rule).not.toMatch(/display:\s*none|visibility:\s*hidden/)
  })

  it('prints the tracking code only from its own button, and never with the pack', () => {
    // Save as PDF makes the pack the citizen gives to others: the code, which
    // opens My case, must not be in it.
    const print = sources['./styles.css'].split('@media print')[1]
    const hidden = print.match(/\n {2}([^{}]*)\{ display: none; \}/)[1]
    expect(hidden).toMatch(/\.pack > :not\(\.paper\)(?=[,\s])/)
    expect(print).toMatch(/\n {2}\.print-code \.pack > \.is-sent \{ display: block; \}/)
    expect(print).toMatch(/\n {2}\.print-code \.paper[^{]*\{ display: none; \}/)
  })

  it('gives the paste box 16px text on a phone, so iPhone does not zoom in on it', () => {
    expect(px(phone, 'textarea', 'font')).toBeGreaterThanOrEqual(16)
  })
})

describe('vercel.json', () => {
  const headers = Object.fromEntries(vercel.headers.find((h) => h.source === '/(.*)').headers
    .map(({ key, value }) => [key, value]))

  it('sends every route but /api/ to the app', () => {
    expect(vercel.rewrites).toEqual([{ source: '/((?!api/).*)', destination: '/index.html' }])
    const [rule] = vercel.rewrites
    const matches = (path) => new RegExp(`^${rule.source}$`).test(path)
    expect(['/', '/report/pack', '/my-case', '/apiary'].every(matches)).toBe(true)
    expect(['/api/session', '/api/my-case'].some(matches)).toBe(false)
  })

  it('runs the citizen functions near India', () => {
    expect(vercel.regions).toEqual(['sin1'])
  })

  it('sends a strict content policy and the other security headers', () => {
    const csp = Object.fromEntries(headers['Content-Security-Policy'].split(';')
      .map((part) => part.trim().split(/\s+/)).map(([name, ...values]) => [name, values.join(' ')]))
    expect(csp).toEqual({
      'default-src': "'self'", 'img-src': "'self' data:", 'font-src': "'self'", 'style-src': "'self'",
      'script-src': "'self'", 'frame-ancestors': "'none'", 'base-uri': "'none'", 'form-action': "'self'",
    })
    expect(headers['X-Content-Type-Options']).toBe('nosniff')
    expect(headers['Referrer-Policy']).toBe('no-referrer')
    expect(headers['Permissions-Policy']).toBe('camera=(), microphone=(), geolocation=()')
  })

  it('installs without install scripts', () => {
    expect(vercel.installCommand).toBe('npm ci --ignore-scripts')
  })
})
