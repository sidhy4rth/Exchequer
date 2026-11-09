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
})

describe('vercel.json', () => {
  const headers = Object.fromEntries(vercel.headers.find((h) => h.source === '/(.*)').headers
    .map(({ key, value }) => [key, value]))

  it('sends every route to the app', () => {
    expect(vercel.rewrites).toEqual([{ source: '/(.*)', destination: '/index.html' }])
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
