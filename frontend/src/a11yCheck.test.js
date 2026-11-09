import { afterEach, describe, expect, it, vi } from 'vitest'
import appSource from './App.jsx?raw'
import pkg from '../package.json'
import { NOT_CHECKED, PAGES } from '../e2e/a11y.pages.js'
import { GROUPS } from './components/AppShell'
import flow11 from './test/victim-flow-11.json'

// The accessibility check (npm run a11y, e2e/a11y.spec.js) opens every page
// of a running Exchequer in a real browser. These keep it pointed at a site
// someone chose, never the live one by default, and keep a page the app
// gains from slipping past it.

async function a11yConfig(env) {
  vi.resetModules()
  for (const [name, value] of Object.entries(env)) vi.stubEnv(name, value)
  return (await import('../playwright.a11y.config.js')).default
}

afterEach(() => vi.unstubAllEnvs())

describe('the accessibility check', () => {
  it('will not start without EXCHEQUER_URL: it has no live-site default', async () => {
    await expect(a11yConfig({ EXCHEQUER_URL: '' })).rejects.toThrow(/EXCHEQUER_URL/)
  })

  it('opens the site it is given, at a desktop and a phone size, and a tablet size where asked', async () => {
    const config = await a11yConfig({ EXCHEQUER_URL: 'http://127.0.0.1:8123', A11Y_BROWSER: '' })
    expect(config.use.baseURL).toBe('http://127.0.0.1:8123')
    expect(config.projects.map((p) => [p.name, p.use.viewport])).toEqual([
      ['desktop', { width: 1280, height: 900 }],
      ['phone', { width: 390, height: 844 }],
      ['tablet', { width: 1024, height: 768 }],
    ])
    expect(config.use.launchOptions?.executablePath).toBeUndefined()
  })

  it("opens the case's Evidence tab at the tablet size, where its table outgrows the card", () => {
    const evidence = PAGES.filter((p) => p.path.endsWith('tab=evidence'))
    expect(evidence.length).toBeGreaterThan(0)
    for (const p of evidence) expect(p.tablet, p.name).toBe(true)
  })

  it('can use a Chromium-based browser already on the machine', async () => {
    const config = await a11yConfig({ EXCHEQUER_URL: 'http://127.0.0.1:8123', A11Y_BROWSER: '/opt/brave/brave' })
    expect(config.use.launchOptions.executablePath).toBe('/opt/brave/brave')
  })

  it('opens every page the app routes to, or says why not', () => {
    const routes = [...appSource.matchAll(/<Route path="([^"]+)"/g)].map((m) => m[1])
    expect(routes.length).toBeGreaterThan(8)
    const pattern = (route) => new RegExp(`^${route.replace(/:\w+/g, '[^/]+')}$`)
    const unchecked = routes.filter((route) => !(route in NOT_CHECKED)
      && !PAGES.some((p) => pattern(route).test(p.path.split('?')[0])))
    expect(unchecked).toEqual([])
  })

  it('opens every page in the sidebar as an officer sees it, and More on a phone', () => {
    const paths = GROUPS.flatMap(([, items]) => items.map((item) => item.to))
    for (const path of paths) expect(PAGES.some((p) => p.path === path && p.as === 'investigator'), path).toBe(true)
    const more = PAGES.find((p) => p.click?.[1]?.name === 'More')
    expect(more?.size).toBe('phone')
  })

  it('opens the Flow tab drawn from the victim flow, on a backend whose recording has none', () => {
    const drawn = PAGES.find((p) => p.name === 'recorded case 11, Flow drawn')
    expect(drawn?.stub.url).toBe('**/demos/recorded/11')
    const answered = drawn.stub.extend({ demo: 11, victim_flow: undefined })
    expect(answered.demo).toBe(11)
    expect(answered.victim_flow.status).toBe('estimated')
    expect(answered.victim_flow).toEqual(flow11)
    // and the card a case without one keeps: the recording answered without the flow the backend adds
    const card = PAGES.find((p) => p.name === 'recorded case 11, Flow')
    expect(card.stub.extend({ demo: 11, victim_flow: flow11 })).toEqual({ demo: 11 })
  })

  it('opens the locked console a public site shows without the demo code', () => {
    const locked = PAGES.find((p) => p.path === '/' && p.stub?.url === '**/access')
    expect(locked?.stub.body).toEqual({ demo_code_required: true })
    expect(locked.ready).toEqual(['heading', { name: 'Verified examples' }])
  })

  it('opens the console with recent cases in it, so their rows are measured too', () => {
    const console = PAGES.find((p) => p.name === 'Console')
    expect(console.ready).toEqual(['heading', { level: 1, name: 'Follow a payment to the exchange that can freeze it' }])
    expect(console.stub.url.test('http://127.0.0.1:8123/cases?limit=5')).toBe(true)
    expect(console.stub.body.cases.length).toBeGreaterThan(0)
  })

  it('opens the Cases page with stored cases and a linked complaint, so their rows and links are measured', () => {
    const answer = (name, url) => [PAGES.find((p) => p.name === name).stub].flat().find((s) => s.url.test(url))?.body
    expect(answer('Cases', 'http://127.0.0.1:8123/cases?limit=50').cases.length).toBeGreaterThan(1)
    expect(answer('Cases', 'http://127.0.0.1:8123/cases/correlate').clusters.length).toBeGreaterThan(0)
    expect(answer('Cases, one filter pressed', 'http://127.0.0.1:8123/cases/correlate').clusters).toEqual([])
  })

  it('pins, per page and size, how much text axe cannot measure for contrast', async () => {
    // A typo in a size would pin nothing; a zero is the default already.
    const sizes = (await a11yConfig({ EXCHEQUER_URL: 'http://127.0.0.1:8123' })).projects.map((p) => p.name)
    const pinned = PAGES.filter((p) => p.unmeasured)
    expect(pinned.length).toBeGreaterThan(0)
    for (const [size, n] of pinned.flatMap((p) => Object.entries(p.unmeasured))) {
      expect(sizes).toContain(size)
      expect(Number.isInteger(n) && n > 0).toBe(true)
    }
  })

  it('runs as npm run a11y, with axe at an exact version', () => {
    expect(pkg.scripts.a11y).toBe('playwright test -c playwright.a11y.config.js')
    expect(pkg.devDependencies['@axe-core/playwright']).toMatch(/^\d+\.\d+\.\d+$/)
  })

  it('is left out of the live-site canary', async () => {
    const canary = (await import('../playwright.config.js')).default
    const ignored = [canary.testIgnore].flat()
    expect(ignored.some((rule) => rule.test('/repo/frontend/e2e/a11y.spec.js'))).toBe(true)
    expect(ignored.some((rule) => rule.test('/repo/frontend/e2e/canary.spec.js'))).toBe(false)
  })
})
