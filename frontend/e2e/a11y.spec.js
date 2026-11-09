import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { PAGES } from './a11y.pages.js'

// WCAG 2.0, 2.1 and 2.2 at levels A and AA, checked by axe on every page in
// both themes (run by playwright.a11y.config.js at a desktop and a phone
// size). The guard before the Glass restyle: a broken label, landmark or
// contrast fails here first. Read-only: it starts no trace, batch or watch.
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

// axe cannot tell the colour behind text drawn over a canvas or a gradient,
// so it files that text as "needs review" instead of failing it: most of the
// sign-in door sits over the globe. A second pass hides the canvases and
// gradients and measures that text against the solid colour
// beneath them (a gradient behind text keeps one: its lightest stop, as
// styles.css .gate does). What axe still cannot measure, such as text that
// overlaps other text or labels inside the graph, is listed and may not grow
// past the page's `unmeasured` pin in a11y.pages.js. The phone's tab bar
// (and its More menu) floats over the page; the first pass measured it on its
// own solid panel, so the second hides it to measure the text beneath it.
const DECOR_HIDDEN = 'canvas, .shell-tabs { visibility: hidden !important } *, *::before, *::after { background-image: none !important }'

const message = (n) => (n.any[0] ?? n.all[0] ?? n.none[0])?.message ?? ''
/** Each finding as one line a person can act on: the rule, where, and why
 * (for contrast, the two colours and the ratio). */
const explain = (v) => `${v.id} (${v.impact}): ${v.help} -- ${v.nodes.map((n) => `${n.target.join(' ')}: ${message(n)}`).join('; ')}`

/** The network quiet and every finite animation over, so axe reads colours
 * as they rest, not halfway through a fade. */
async function settle(page) {
  await page.waitForLoadState('networkidle')
  await page.evaluate(() => Promise.all(document.getAnimations()
    .filter((a) => a.effect?.getComputedTiming().endTime !== Infinity)
    .map((a) => a.finished.catch(() => {}))))
}

/** How far down the page `el` sits, however far it is scrolled. */
const depth = (el) => el.evaluate((e) => Math.round(window.scrollY + e.getBoundingClientRect().top))

async function open(page, p, theme) {
  // The keys theme.js and session.js keep, set before the app reads them.
  await page.addInitScript(([chosen, as]) => {
    localStorage.setItem('exchequer-theme', chosen)
    if (as) sessionStorage.setItem('exchequer-demo-session', as)
  }, [theme, p.as])
  await page.route('**/*', (route) => (['GET', 'HEAD'].includes(route.request().method()) ? route.fallback() : route.abort()))
  for (const stub of [p.stub ?? []].flat()) await page.route(stub.url, (route) => route.fulfill({ json: stub.body }))

  await page.goto(p.path)
  // A click scrolls what it presses into view, so it waits for the page to
  // load: content landing above it later would leave the page at rest in a
  // different place on each run, with other text under the see-through top
  // bar on a phone. The check fails if what it pressed moved all the same.
  const pressed = p.click && page.getByRole(...p.click).first()
  let clickedAt
  if (pressed) {
    await settle(page)
    clickedAt = await depth(pressed)
    await pressed.click()
  }
  await expect(page.getByRole(...p.ready).first()).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
  await settle(page)
  await expect(page.getByText('Backend unreachable'), 'the pages cannot reach the backend: build with VITE_API_BASE= (empty), as CI does').toHaveCount(0)
  if (pressed) expect(await depth(pressed), 'what the check pressed moved down the page: it was pressed before the page had loaded').toBe(clickedAt)
}

/** Controls that a hidden overflow cuts off sideways: no pointer can reach
 * them, and focusing one scrolls the box and leaves it shifted. A control in
 * a scrolling box is fine; the box itself is measured instead. */
const cutOff = (page) => page.evaluate(() => [...document.querySelectorAll('a[href], button, input, select, textarea, summary, [tabindex]')]
  .filter((el) => el.getClientRects().length && !el.closest('.visually-hidden'))
  .flatMap((el) => {
    const r = el.getBoundingClientRect()
    for (let box = el.parentElement; box && box !== document.body; box = box.parentElement) {
      const overflow = getComputedStyle(box).overflowX
      if (overflow === 'auto' || overflow === 'scroll') return []
      const b = box.getBoundingClientRect()
      if ((overflow === 'hidden' || overflow === 'clip') && (r.left < b.left - 1 || r.right > b.right + 1)) {
        return [`${el.tagName.toLowerCase()} "${el.textContent.trim().slice(0, 40)}" cut off by ${box.tagName.toLowerCase()}.${box.className}`]
      }
    }
    return []
  }))

/** Contrast with the decorative layers hidden: what fails, and the text axe
 * still cannot measure (an icon glyph such as + is not text). */
async function contrast(page) {
  await page.addStyleTag({ content: DECOR_HIDDEN })
  await settle(page)
  const { violations, incomplete } = await new AxeBuilder({ page }).withRules(['color-contrast']).analyze()
  const unmeasured = incomplete.flatMap((r) => r.nodes).filter((n) => n.any[0]?.data?.messageKey !== 'nonBmp')
  return { failed: violations.map(explain), unmeasured: unmeasured.map((n) => `${n.target.join(' ')}: ${message(n)}`) }
}

for (const theme of ['dark', 'light']) {
  test.describe(`${theme} theme`, () => {
    for (const p of PAGES) {
      test(p.name, async ({ page }, info) => {
        test.skip(Boolean(p.size) && p.size !== info.project.name, `checked at ${p.size} size only`)
        test.skip(info.project.name === 'tablet' && !p.tablet, 'checked at the tablet size only where the page asks')
        await open(page, p, theme)
        expect(await cutOff(page)).toEqual([])
        if (p.layout) await p.layout(page, info.project.name)

        // Needs-review fails too, for every rule but contrast (measured
        // below): a name on a div with no role is as real as a violation.
        const { violations, incomplete } = await new AxeBuilder({ page }).withTags(TAGS).analyze()
        expect([...violations, ...incomplete.filter((r) => r.id !== 'color-contrast')].map(explain)).toEqual([])

        const { failed, unmeasured } = await contrast(page)
        expect(failed).toEqual([])
        if (unmeasured.length) info.annotations.push({ type: 'contrast not measured', description: unmeasured.join('\n') })
        // At the tablet size a wide table scrolls, and axe cannot measure text
        // scrolled out of view: the same text is measured at the desktop size.
        const pin = info.project.name === 'tablet' ? Infinity : p.unmeasured?.[info.project.name] ?? 0
        expect(unmeasured.length, `axe cannot measure the contrast of more text than the ${pin} pinned:\n${unmeasured.join('\n')}`).toBeLessThanOrEqual(pin)
      })
    }
  })
}

// The check itself: text turned near-black over the globe must fail it. axe
// alone files that text as needs-review and lets it pass. Only the sign-in
// doors draw the globe now (the console dropped it), and a page with no
// canvas would test nothing here, so the case asks for one first.
test.describe('the contrast pass', () => {
  for (const [name, over] of [['investigator sign-in', '.gate-hint span']]) {
    test(`fails dark text over the globe: ${name}`, async ({ page }, info) => {
      test.skip(info.project.name === 'tablet', 'checked at desktop and phone')
      await open(page, PAGES.find((p) => p.name === name), 'dark')
      await expect(page.locator('canvas'), `${name} draws no globe: this case would check plain text`).not.toHaveCount(0)
      await page.addStyleTag({ content: `${over} { color: #1a1a1a !important }` })
      expect((await contrast(page)).failed.join('\n')).toContain('foreground color: #1a1a1a')
    })
  }
})
