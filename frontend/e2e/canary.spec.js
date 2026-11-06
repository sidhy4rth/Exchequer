import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

// What a judge does first: open the link, sign in, look at a case. If any of
// that is broken the demo-health job would not notice -- it talks to the API
// only -- so this walks the same path in a real browser.

/** Fail the test on any uncaught page error or console error. */
function watchForErrors(page) {
  const errors = []
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(`console: ${msg.text()}`) })
  return errors
}

async function enter(page) {
  await page.getByText(/click anywhere to enter/i).click()
  await page.getByRole('button', { name: /open the console/i }).click()
}

test('the API is up and the label files are loaded', async ({ request }) => {
  const health = await (await request.get('/health')).json()
  expect(health.status).toBe('ok')
  // "open" means anyone can start live traces; once the code is set, say so
  // with the repository variable EXPECT_DEMO_CODE and losing it turns this red.
  if (process.env.EXPECT_DEMO_CODE) expect(health.access, 'live tracing must need the demo code').toBe('code')
  const { chains } = await (await request.get('/chains')).json()
  // Well below today's counts; this catches a deploy that shipped without
  // its data files, not ordinary growth or pruning.
  expect(chains.ethereum.exchange_labels).toBeGreaterThan(10_000)
  expect(Object.values(chains.ethereum.risk_labels).reduce((a, b) => a + b, 0)).toBeGreaterThan(5_000)
  // The label store carries most of the ~10.9M labels; without it the total
  // is well under a million. A deploy that lost it fails here.
  const screened = Object.values(chains)
    .flatMap((c) => Object.values(c.risk_labels || {}))
    .reduce((a, b) => a + b, 0)
  expect(screened, 'risk labels across every chain (is the label store in?)').toBeGreaterThan(5_000_000)
  const notReady = Object.values(chains).filter((c) => !c.ready).map((c) => c.name)
  expect(notReady, 'chains that cannot be traced').toEqual([])
})

// render.yaml's values reach Render only through a Blueprint sync or by hand,
// and the live service once ran for days without the ones added after it was
// created: no health token, the watcher on. The workflow says what to expect
// (repository variables EXPECT_HEALTH_TOKEN and EXPECT_WATCHER).
test('the service runs with the settings render.yaml gives it', async ({ request }) => {
  if (process.env.EXPECT_HEALTH_TOKEN === '1') {
    // 404 means EXCHEQUER_HEALTH_TOKEN is unset there; 401 is the endpoint refusing a stranger.
    expect((await request.get('/health/detail')).status(), 'EXCHEQUER_HEALTH_TOKEN is set on the service').toBe(401)
  }
  if (process.env.EXPECT_WATCHER === '0' || process.env.EXPECT_WATCHER === '1') {
    const { watcher } = await (await request.get('/watches')).json()
    expect(watcher.enabled, 'EXCHEQUER_WATCHER on the service').toBe(process.env.EXPECT_WATCHER === '1')
  }
})

test('the front door opens the console with every chain live', async ({ page }) => {
  const errors = watchForErrors(page)
  const started = Date.now()
  await page.goto('/')
  await expect(page).toHaveURL(/\/signin\/investigator/)
  await enter(page)
  // With EXCHEQUER_DEMO_CODE set, the public console asks for the access code instead.
  await expect(page.getByLabel('Reported wallet address').or(page.getByLabel('Access code'))).toBeVisible()
  // The status chip: "Live · 5 chains" (console v2).
  await expect(page.getByText(/^Live · \d+ chains?$/)).toBeVisible()
  const loadMs = Date.now() - started
  test.info().annotations.push({ type: 'load', description: `${loadMs} ms to a usable console` })
  expect(loadMs, 'time from first request to a usable console').toBeLessThan(20_000)
  expect(errors).toEqual([])
})

test('the front door and the console load nothing from another site', async ({ page, baseURL }) => {
  // R27: fonts included. A request elsewhere tells that site who opened a
  // police tracing tool, and fails on networks that block outside hosts.
  const own = new URL(baseURL).origin
  const elsewhere = []
  page.on('request', (req) => {
    const url = new URL(req.url())
    if (url.protocol.startsWith('http') && url.origin !== own) elsewhere.push(req.url())
  })
  await page.goto('/')
  await enter(page)
  await expect(page.getByLabel('Reported wallet address').or(page.getByLabel('Access code'))).toBeVisible()
  await page.waitForLoadState('networkidle')
  // The bundled fonts are the ones in use, not a fallback.
  expect(await page.evaluate(() => document.fonts.check('13px "IBM Plex Sans"') && document.fonts.check('13px "IBM Plex Mono"'))).toBe(true)
  expect(elsewhere).toEqual([])
})

test('a stored case opens without re-tracing', async ({ page, request }) => {
  const { cases } = await (await request.get('/cases?limit=20')).json()
  const known = cases.find((c) => c.exchange)
  test.skip(!known, 'no stored case names an exchange yet')

  const errors = watchForErrors(page)
  const traced = []
  page.on('request', (req) => { if (req.method() === 'POST' && req.url().includes('/trace')) traced.push(req.url()) })

  await page.goto('/signin/investigator')
  await enter(page)
  await page.goto(`/case/${known.case_id}`)
  await expect(page.getByRole('heading', { name: known.exchange }).first()).toBeVisible()
  expect(traced, 'opening a stored case must not start a new trace').toEqual([])
  expect(errors).toEqual([])
})

// Every report names the key that signed it (SECURITY.md, "Report signing
// key"); a reader tells Exchequer's reports from a copy's by that key. The
// live site must sign with a current official key from the committed list,
// or every report it issues reads as unofficial.
test('the site signs reports with an official Exchequer key', async ({ request }) => {
  const listed = JSON.parse(readFileSync(new URL('../../backend/data/signing_keys.json', import.meta.url), 'utf8')).keys
  test.skip(!listed.length, 'no official signing key recorded yet in backend/data/signing_keys.json')
  const live = await (await request.get('/signing-key')).json()
  const current = listed.filter((k) => !k.retired && !k.revoked).map((k) => k.fingerprint_sha256)
  expect(current, 'the live key is the current official key').toContain(live.fingerprint_sha256)
  expect(live.persistent, 'the live key survives a restart').toBe(true)
})
