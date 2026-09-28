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

async function signIn(page) {
  await page.getByText(/click anywhere to log in/i).click()
  await page.getByRole('button', { name: /open the console/i }).click()
}

test('the API is up and the label files are loaded', async ({ request }) => {
  const health = await (await request.get('/health')).json()
  expect(health.status).toBe('ok')
  // Well below today's counts; this catches a deploy that shipped without
  // its data files, not ordinary growth or pruning.
  expect(health.exchange_labels_loaded).toBeGreaterThan(10_000)
  expect(health.risk_labels_loaded).toBeGreaterThan(5_000)
  const notReady = Object.values(health.chains).filter((c) => !c.ready).map((c) => c.name)
  expect(notReady, 'chains that cannot be traced').toEqual([])
})

test('sign-in opens the console with the system operational', async ({ page }) => {
  const errors = watchForErrors(page)
  const started = Date.now()
  await page.goto('/')
  await expect(page).toHaveURL(/\/signin\/investigator/)
  await signIn(page)
  await expect(page.getByLabel('Reported wallet address')).toBeVisible()
  await expect(page.getByText(/SYSTEM OPERATIONAL/)).toBeVisible()
  const loadMs = Date.now() - started
  test.info().annotations.push({ type: 'load', description: `${loadMs} ms to a usable console` })
  expect(loadMs, 'time from first request to a usable console').toBeLessThan(20_000)
  expect(errors).toEqual([])
})

test('a stored case opens without re-tracing', async ({ page, request }) => {
  const { cases } = await (await request.get('/cases?limit=20')).json()
  const known = cases.find((c) => c.exchange)
  test.skip(!known, 'no stored case names an exchange yet')

  const errors = watchForErrors(page)
  const traced = []
  page.on('request', (req) => { if (req.method() === 'POST' && req.url().includes('/trace')) traced.push(req.url()) })

  await page.goto('/signin/investigator')
  await signIn(page)
  await page.goto(`/case/${known.case_id}`)
  await expect(page.getByRole('heading', { name: known.exchange }).first()).toBeVisible()
  expect(traced, 'opening a stored case must not start a new trace').toEqual([])
  expect(errors).toEqual([])
})
