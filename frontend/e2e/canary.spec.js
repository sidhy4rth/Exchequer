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
  expect(await (await request.get('/health')).json()).toEqual({ status: 'ok' })
  const { chains } = await (await request.get('/chains')).json()
  // Well below today's counts; this catches a deploy that shipped without
  // its data files, not ordinary growth or pruning.
  expect(chains.ethereum.exchange_labels).toBeGreaterThan(10_000)
  expect(Object.values(chains.ethereum.risk_labels).reduce((a, b) => a + b, 0)).toBeGreaterThan(5_000)
  const notReady = Object.values(chains).filter((c) => !c.ready).map((c) => c.name)
  expect(notReady, 'chains that cannot be traced').toEqual([])
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
