// What the accessibility check (a11y.spec.js) opens: every page, and each
// state of one that a person reaches with a click. `as` is the view the tab
// has chosen at the front door (session.js); `click` and `ready` are
// page.getByRole() arguments: what to press, and what shows once the page
// has rendered; `size` checks a state at that size only. src/a11yCheck.test.js
// fails when App.jsx routes to a page, or the sidebar lists one, that is
// neither here nor in NOT_CHECKED.
//
// `unmeasured` pins, per size, how much text axe still cannot measure for
// contrast with the canvases and gradients hidden (a11y.spec.js lists it).
// TODO(Glass): bring these down, never up. The door's card sits under its
// tiles; on a phone the console's Coverage tables (opened) scroll sideways
// inside themselves and axe cannot see the cells they clip, and the
// verified-example rows and a batch's empty cell run under their neighbours;
// a case's transfer rows draw over a pseudo-element;
// text cut by the bottom of the screen at rest (a tall exchange list, the
// signing-key note on Verify inside the console, the Console's wallet bars, a
// coverage row, the Cases page's linked wallet or New trace's direction at
// the fold) cannot be sampled; the graph draws its labels over SVG shapes.

const DOOR = ['button', { name: /click anywhere to enter/i }]

// A real batch needs live traces, so the check answers GET /batches/{id}
// itself with a finished one (the shape routes/batches.py returns).
const BATCH = {
  batch_id: 'a11y-example', name: 'Accessibility check', status: 'done', total: 2, done: 2, failed: 0, interrupted: 0, pending: 0,
  rows: [
    { row: 1, reference: 'NCRP-1', address: `0x${'1'.repeat(40)}`, chain: 'ethereum', asset: 'ETH', status: 'done', same_as: null, case_id: null, exchange: 'Binance', confidence: 0.49, error: null },
    { row: 2, reference: '', address: `0x${'2'.repeat(40)}`, chain: 'ethereum', asset: 'USDT', status: 'done', same_as: null, case_id: null, exchange: null, confidence: null, error: null },
  ],
  exchanges: [['Binance', 1]],
  shared_wallets: [{ address: `0x${'3'.repeat(40)}`, rows: [1, 2], references: ['NCRP-1'], inferred_exchange: 'Binance', risk_category: null }],
}

// The Cases page and the Console's Recent cases need stored cases, so the
// check answers the app's own GET /cases?limit= with two (the shape
// routes/casebook.py returns); the page load of /cases still reaches the server.
// The Cases page also asks GET /cases/correlate, answered with one wallet the
// two meet at and a complaint the browser cannot open, so the Linked
// complaints card is measured with its links (or, empty, with its note).
const CASES = {
  count: 2,
  cases: [
    { case_id: 'a11y-1', address: `0x${'4'.repeat(40)}`, chain: 'ethereum', asset: 'ETH', direction: 'outgoing', exchange: 'Binance', confidence: 0.49, flags: ['amount_split'], hop_count: 2, node_count: 30, created_at: '2026-11-09T10:00:00+00:00', demo: true },
    { case_id: 'a11y-2', address: `0x${'5'.repeat(40)}`, chain: 'ethereum', asset: 'ETH', direction: 'incoming', exchange: null, confidence: null, flags: [], hop_count: 1, node_count: 11, created_at: '2026-11-09T10:00:00+00:00', demo: false },
  ],
}

const member = (c) => ({ case_id: c.case_id, reported_address: c.address, direction: c.direction, asset: c.asset, traced_at: c.created_at, depth: 1, value_in_native: 1, exchange: c.exchange, after_swap_to: null })
const LINKED = {
  cases_examined: 2, cluster_count: 1,
  clusters: [{
    chain: 'ethereum', address: `0x${'6'.repeat(40)}`, inferred_exchange: 'Binance', risk_category: 'frozen', reported_addresses: CASES.cases.map((c) => c.address),
    case_count: 2, max_value_in_native: 1, other_complaints: 1, cases: CASES.cases.map(member),
  }],
}
const CASES_STUB = (linked) => [{ url: /\/cases\?limit=\d+$/, body: CASES }, { url: /\/cases\/correlate$/, body: linked }]

// The Evidence tab's "Second provider" column shows once a recheck answers
// (routes/recheck.py), so the check answers GET /trace/demo-11/recheck with
// one that read four of demo 11's route transfers, each with another word.
const RECHECK = {
  case_id: null, chain: 'tron', asset: 'USDT', provider: 'TronScan', checked_at: '2026-11-10T05:00:00+00:00',
  cited: 22, checked: 4, skipped: 0, counts: { matches: 1, differs: 1, not_found: 1, error: 1 },
  transfers: [
    { hash: '10472b07a294beb300101a4c6f197c4bdff9680daebd677e946514c88f824fce', status: 'matches', differences: [], detail: null },
    { hash: '38ef314819abff3f5c448da6de769fad80821ae06a26f15a8fd134e1645fbdba', status: 'differs', differences: [], detail: 'amount is 1148.7, the report says 1148.688' },
    { hash: 'c69b44b9b87b7d96878a8f71c0a02c918a37d0a2b5f3ec0c69c2b0f70bbfd127', status: 'not_found', differences: [], detail: 'the second provider does not have this transaction' },
    { hash: '821965673662c740fe8b51126bc3dd3e6d53047f2282f7def00ee750c748f974', status: 'error', differences: [], detail: 'the second provider could not be read' },
  ],
}

/** The Amount heading sits over its figures, right-aligned as they are. */
async function amountsAligned(page, size) {
  // Each full hash in the table keeps to two even lines, one per half: the
  // mono glyphs round wider on Linux, and a half that wrapped made its row taller.
  const wrapped = await page.locator('.ev-table .ev-hash > span').evaluateAll((halves) => halves.filter((half) => {
    const text = document.createRange()
    text.selectNodeContents(half)
    return new Set([...text.getClientRects()].map((r) => Math.round(r.top))).size > 1
  }).map((half) => half.textContent))
  if (wrapped.length) throw new Error(`a hash's half wraps onto a second line: ${wrapped.join(', ')}`)
  if (size === 'phone') return // each transfer is a card there, with no heading row
  const edge = (cell) => cell.evaluate((e) => {
    const r = e.firstChild ? (() => { const range = document.createRange(); range.selectNodeContents(e); return range.getBoundingClientRect() })() : e.getBoundingClientRect()
    return Math.round(r.right)
  })
  const [head, figure] = await Promise.all([edge(page.locator('.ev-table th.ev-amt')), edge(page.locator('.ev-table td.ev-amt').first())])
  if (head !== figure) throw new Error(`the Amount heading ends at x=${head}, its figures at x=${figure}`)
}

/** The Timeline tab's lane chart: the day axis spans the same box as the
 * lanes, so a label sits on its grid line; every dot has a hit area of 24 px
 * or more; a tap picks a dot in every lane, and from it Earlier and Later in
 * the strip below reach the rest of the lane (dots on one day can still sit
 * on top of each other). Taps go where elementFromPoint says a finger lands. */
async function timelineReachable(page) {
  const problems = await page.evaluate(async () => {
    const out = []
    const rest = window.scrollY
    const axis = document.querySelector('.tl-axis').getBoundingClientRect()
    for (const track of document.querySelectorAll('.tl-track')) {
      const r = track.getBoundingClientRect()
      if (Math.abs(axis.left - r.left) > 0.5 || Math.abs(axis.right - r.right) > 0.5) out.push(`the day axis runs x=${axis.left}–${axis.right}, a lane x=${r.left}–${r.right}`)
    }
    const at = [0.5, 0.1, 0.3, 0.7, 0.9]
    for (const lane of document.querySelectorAll('.tl-lane')) {
      lane.scrollIntoView({ block: 'center' })
      const name = lane.getAttribute('aria-label')
      let reached = 0
      for (const d of lane.querySelectorAll('.tl-dot')) {
        const r = d.getBoundingClientRect()
        if (r.width < 24 || r.height < 24) out.push(`a dot in "${name}" is ${r.width}×${r.height} px`)
        tap: for (const fx of at) for (const fy of at) {
          const [x, y] = [r.left + fx * r.width, r.top + fy * r.height]
          const el = document.elementFromPoint(x, y)
          if (el?.closest('.tl-lane') !== lane) continue
          el.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x, clientY: y }))
          await new Promise((done) => setTimeout(done))
          if (d.getAttribute('aria-selected') === 'true') { reached += 1; break tap }
        }
      }
      if (!reached) out.push(`no dot in "${name}" can be tapped`)
    }
    for (const label of ['Earlier transfer in this lane', 'Later transfer in this lane']) {
      const b = document.querySelector(`.tl-picked button[aria-label="${label}"]`)
      const r = b?.getBoundingClientRect()
      if (!r || r.width < 24 || r.height < 24) out.push(`"${label}" is missing or under 24 px`)
    }
    window.scrollTo(0, rest) // the contrast check reads the page at rest
    return out
  })
  if (problems.length) throw new Error(problems.join('\n'))
}

const H1 = (name) => ['heading', { level: 1, name }]
const CASE_TAB = (name) => ['tab', { name, selected: true }]
const FILL = ['region', { name: /^For you to fill · \d+$/ }] // shows once the letter is drafted

/** What Mark as sent says shows beside the button, in view, not a letter's
 * height below it. */
async function saidBesideButton(page) {
  const [button, said] = await Promise.all([
    page.getByRole('button', { name: 'Mark as sent' }).boundingBox(),
    page.getByRole('link', { name: 'Open a stored case' }).boundingBox(),
  ])
  const gap = said.y - (button.y + button.height)
  if (gap < 0 || gap > 160) throw new Error(`the prompt sits ${Math.round(gap)} px below Mark as sent`)
  const height = page.viewportSize().height
  const top = await page.getByRole('link', { name: 'Open a stored case' }).evaluate((e) => e.getBoundingClientRect().top)
  if (top < 0 || top > height) throw new Error(`the prompt is out of view (top ${Math.round(top)} px)`)
}

// On a phone the open sign-in card is drawn from tiles, and the "Preview"
// paragraph sits over a seam between two of them. On Linux (CI) the card's
// text wraps a few pixels lower than on a Mac, so that paragraph crosses the
// seam too and axe cannot pick one background for it: five lines it cannot
// measure instead of four. Nothing changes on screen.
const PHONE_DOOR = 5

export const PAGES = [
  { name: 'investigator sign-in', path: '/signin/investigator', ready: DOOR },
  { name: 'investigator sign-in, door open', path: '/signin/investigator', click: DOOR, ready: ['dialog', { name: /enter as investigator/i }], unmeasured: { desktop: 3, phone: PHONE_DOOR } },
  { name: 'citizen sign-in', path: '/signin/citizen', ready: DOOR },
  { name: 'citizen sign-in, door open', path: '/signin/citizen', click: DOOR, ready: ['dialog', { name: /enter as citizen/i }], unmeasured: { desktop: 4, phone: PHONE_DOOR } },
  // The console's pages, each inside the shell (sidebar, header, phone tab bar).
  // With stored cases (CASES, below), so the Recent cases rows are measured too.
  { name: 'Console', path: '/', as: 'investigator', stub: { url: /\/cases\?limit=\d+$/, body: CASES }, ready: H1('Follow a payment to the exchange that can freeze it'), unmeasured: { phone: 2 } },
  // The coverage tables wait behind a disclosure (a closed <details> is all summary).
  { name: 'Console, coverage open', path: '/', as: 'investigator', click: ['group', { name: 'Coverage' }], ready: ['table', { name: 'Exchange labels per chain' }], unmeasured: { desktop: 3, phone: 12 } },
  // What a public site shows until the demo code is given (render.yaml sets
  // one): the verified examples, and no way to start a trace.
  { name: 'Console, locked (demo code)', path: '/', as: 'investigator', stub: { url: '**/access', body: { demo_code_required: true } }, ready: ['heading', { name: 'Verified examples' }], unmeasured: { desktop: 2, phone: 1 } },
  { name: 'More, on a phone', path: '/', as: 'investigator', size: 'phone', click: ['button', { name: 'More' }], ready: ['link', { name: 'Verify a report' }] },
  { name: 'New trace', path: '/trace/new', as: 'investigator', ready: H1('New trace'), unmeasured: { phone: 1 } },
  // The victim's payments opened: the hashes, the victim's wallet and the
  // masked NCRP number (on a site that traces from payment hashes).
  { name: 'New trace, payments open', path: '/trace/new', as: 'investigator', stub: { url: '**/trace/intake', body: { payments: true } }, click: ['button', { name: /Victim's payments/ }], ready: ['textbox', { name: "The victim's payment hashes, one per line" }] },
  // A searched hash on a site that cannot trace from one says so.
  { name: 'New trace, hash with payments off', path: `/trace/new?pay=0x${'c'.repeat(64)}`, as: 'investigator', stub: { url: '**/trace/intake', body: { payments: false } }, ready: H1('New trace') },
  // The table on a desktop, a card per case on a phone; a pressed filter, and
  // the Linked complaints card both linked and empty.
  { name: 'Cases', path: '/cases', as: 'investigator', stub: CASES_STUB(LINKED), ready: ['link', { name: CASES.cases[0].address }], unmeasured: { phone: 1 } },
  { name: 'Cases, one filter pressed', path: '/cases', as: 'investigator', stub: CASES_STUB({ ...LINKED, cluster_count: 0, clusters: [] }), click: ['button', { name: /^No exchange/ }], ready: ['button', { name: /^No exchange/, pressed: true }] },
  { name: 'Bulk intake', path: '/batch', as: 'investigator', ready: H1('Bulk intake') },
  { name: 'Watchlist', path: '/watchlist', as: 'investigator', ready: H1('Watchlist') },
  { name: 'Requests', path: '/requests', as: 'investigator', ready: H1('Requests') },
  // A recorded trace: the case view, read from the recording, no chain
  // consulted. It opens on Flow, and each tab has a URL of its own. On a
  // phone a line of the finding sits at the foot of the screen at rest.
  { name: 'recorded case 11', path: '/demo/11', as: 'investigator', ready: ['heading', { level: 2 }], unmeasured: { desktop: 8, phone: 9 } },
  { name: 'recorded case 11, Flow', path: '/demo/11?tab=flow', as: 'investigator', ready: CASE_TAB('Flow'), unmeasured: { desktop: 8, phone: 9 } },
  { name: 'recorded case 11, Timeline', path: '/demo/11?tab=timeline', as: 'investigator', ready: CASE_TAB('Timeline'), unmeasured: { desktop: 11, phone: 21 }, layout: timelineReachable },
  // The lane chart opens on its first 14 days; the whole trace is a press away.
  { name: 'recorded case 11, Timeline, every day', path: '/demo/11?tab=timeline', as: 'investigator', click: ['button', { name: /^All \d+ days$/ }], ready: ['button', { name: /^All \d+ days$/, pressed: true }], unmeasured: { desktop: 11, phone: 21 }, layout: timelineReachable },
  { name: 'recorded case 11, Entities', path: '/demo/11?tab=entities', as: 'investigator', ready: CASE_TAB('Entities'), unmeasured: { phone: 1 } },
  // Entities opens on the groups with the split wallet's card; its wallets
  // open on request, and Every wallet shows the graph beside the flow by hop,
  // whose labels sit over SVG shapes as on Flow (on a phone the graph's own
  // panels also overlap inside its stage).
  { name: 'recorded case 11, Entities, a group\'s wallets', path: '/demo/11?tab=entities', as: 'investigator', click: ['button', { name: /^(Open|Hide) the 8 wallets$/ }], ready: ['button', { name: 'Hide the 8 wallets', expanded: true }], unmeasured: { phone: 1 } },
  { name: 'recorded case 11, Entities, every wallet', path: '/demo/11?tab=entities', as: 'investigator', click: ['button', { name: 'Every wallet' }], ready: ['img', { name: 'Money flow by hop' }], unmeasured: { desktop: 8, phone: 18 }, layout: graphPanelsApart },
  { name: 'recorded case 11, Evidence', path: '/demo/11?tab=evidence', as: 'investigator', ready: CASE_TAB('Evidence'), unmeasured: { phone: 1 }, tablet: true, layout: amountsAligned },
  { name: 'recorded case 11, Evidence, rechecked', path: '/demo/11?tab=evidence', as: 'investigator', stub: { url: '**/trace/demo-11/recheck', body: RECHECK }, ready: ['button', { name: 'Re-read from a second provider' }], unmeasured: { phone: 1 }, tablet: true, layout: amountsAligned },
  // The Letters tab drafts a recording's letters as a case's: the first one
  // listed opens on its sheet; a press switches it; Mark as sent asks, beside
  // the button, for a stored case, since a recording logs nothing. A line of
  // the letter sits at the foot of the screen at rest.
  { name: 'recorded case 11, Letters', path: '/demo/11?tab=letters', as: 'investigator', ready: FILL, unmeasured: { desktop: 1, phone: 1 } },
  { name: 'recorded case 11, Letters, to Tether', path: '/demo/11?tab=letters', as: 'investigator', click: ['button', { name: 'Request to Tether' }], ready: ['article', { name: 'Draft: Request to Tether' }], unmeasured: { desktop: 1, phone: 1 } },
  { name: 'recorded case 11, Letters, marked as sent', path: '/demo/11?tab=letters', as: 'investigator', click: ['button', { name: 'Mark as sent' }], ready: ['link', { name: 'Open a stored case' }], unmeasured: { desktop: 1, phone: 1 }, layout: saidBesideButton },
  // Opened from a link, a trace asks before it runs.
  { name: 'trace link', path: '/trace/0x7c3e9bab6715e4040f013e865b193b0209642e36?chain=ethereum&asset=ETH&depth=3&direction=outgoing', as: 'investigator', ready: ['button', { name: 'Run this trace' }] },
  { name: 'batch', path: '/batch/a11y-example', as: 'investigator', stub: { url: '**/batches/a11y-example', body: BATCH }, ready: ['heading', { level: 1, name: BATCH.name }], unmeasured: { phone: 1 } },
  { name: 'verify a report', path: '/verify', ready: ['heading', { level: 1 }] },
  { name: 'verify a report, in the console', path: '/verify', as: 'investigator', ready: ['heading', { level: 1 }], unmeasured: { phone: 1 } },
  { name: 'citizen page', path: '/citizen', as: 'citizen', ready: ['heading', { level: 1 }] },
]

export const NOT_CHECKED = {
  '/signin': 'sends the browser on to /signin/investigator',
  '/case/:caseId': 'needs a stored case; /demo/11 opens the same case view from a recording',
  '*': 'any other path shows the console',
}

/** Entities, every wallet: the graph's panels along its top (the hint, the
 * counts, the zoom buttons) never cover one another, however narrow its
 * stage: the hint once covered the counts' first figures, and on Linux axe
 * could not measure them. */
async function graphPanelsApart(page) {
  const clashes = await page.locator('.ent-every .stage').evaluate((stage) => {
    const panels = ['.graph-hint', '.graph-stats', '.graph-controls'].map((s) => [s, stage.querySelector(s).getBoundingClientRect()])
    return panels.flatMap(([a, ra], i) => panels.slice(i + 1)
      .filter(([, rb]) => ra.left < rb.right && rb.left < ra.right && ra.top < rb.bottom && rb.top < ra.bottom)
      .map(([b]) => `${a} covers ${b}`))
  })
  if (clashes.length) throw new Error(`the graph's panels overlap: ${clashes.join('; ')}`)
}
