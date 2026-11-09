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
// text cut by the bottom of the screen at rest (a tall exchange list, the
// signing-key note on Verify inside the console, the Console's wallet bars, a
// coverage row or the Cases page's linked wallet at the fold) cannot be
// sampled; the graph draws its labels over SVG shapes.

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

const H1 = (name) => ['heading', { level: 1, name }]

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
  { name: 'New trace', path: '/trace/new', as: 'investigator', ready: H1('New trace') },
  // A searched hash on a site that cannot trace from one says so.
  { name: 'New trace, hash with payments off', path: `/trace/new?pay=0x${'c'.repeat(64)}`, as: 'investigator', stub: { url: '**/trace/intake', body: { payments: false } }, ready: H1('New trace') },
  // The table on a desktop, a card per case on a phone; a pressed filter, and
  // the Linked complaints card both linked and empty.
  { name: 'Cases', path: '/cases', as: 'investigator', stub: CASES_STUB(LINKED), ready: ['link', { name: CASES.cases[0].address }], unmeasured: { phone: 1 } },
  { name: 'Cases, one filter pressed', path: '/cases', as: 'investigator', stub: CASES_STUB({ ...LINKED, cluster_count: 0, clusters: [] }), click: ['button', { name: /^No exchange/ }], ready: ['button', { name: /^No exchange/, pressed: true }] },
  { name: 'Bulk intake', path: '/batch', as: 'investigator', ready: H1('Bulk intake') },
  { name: 'Watchlist', path: '/watchlist', as: 'investigator', ready: H1('Watchlist') },
  { name: 'Requests', path: '/requests', as: 'investigator', ready: H1('Requests') },
  // A recorded trace: the case view, read from the recording, no chain consulted.
  { name: 'recorded case 11', path: '/demo/11', as: 'investigator', ready: ['heading', { level: 2 }], unmeasured: { desktop: 19, phone: 28 } },
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
