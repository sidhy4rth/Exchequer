// What the accessibility check (a11y.spec.js) opens: every page, and each
// state of one that a person reaches with a click. `as` is the view the tab
// has chosen at the front door (session.js); `click` and `ready` are
// page.getByRole() arguments: what to press, and what shows once the page
// has rendered. src/a11yCheck.test.js fails when App.jsx routes to a page
// that is neither here nor in NOT_CHECKED.
//
// `unmeasured` pins, per size, how much text axe still cannot measure for
// contrast with the canvases and gradients hidden (a11y.spec.js lists it).
// TODO(Glass): bring these down, never up. The door's card sits under its
// tiles; on a phone the Coverage tables, the verified-example rows and a
// batch's empty cell run under their neighbours; the graph draws its labels
// over SVG shapes.

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

const HOME_TABS = ['Stored cases', 'Watchlist', 'Open requests', 'Bulk intake', 'Coverage']

export const PAGES = [
  { name: 'investigator sign-in', path: '/signin/investigator', ready: DOOR },
  { name: 'investigator sign-in, door open', path: '/signin/investigator', click: DOOR, ready: ['dialog', { name: /enter as investigator/i }], unmeasured: { desktop: 3, phone: 4 } },
  { name: 'citizen sign-in', path: '/signin/citizen', ready: DOOR },
  { name: 'citizen sign-in, door open', path: '/signin/citizen', click: DOOR, ready: ['dialog', { name: /enter as citizen/i }], unmeasured: { desktop: 4, phone: 4 } },
  ...HOME_TABS.map((tab) => ({
    name: `Home · ${tab}`, path: '/', as: 'investigator',
    click: ['tab', { name: new RegExp(`^${tab}`) }], ready: ['tab', { name: new RegExp(`^${tab}`), selected: true }],
    ...(tab === 'Coverage' && { unmeasured: { desktop: 1, phone: 16 } }),
  })),
  // What a public site shows until the demo code is given (render.yaml sets
  // one): the verified examples, and no way to start a trace.
  { name: 'Home, locked (demo code)', path: '/', as: 'investigator', stub: { url: '**/access', body: { demo_code_required: true } }, ready: ['heading', { name: 'Verified examples' }], unmeasured: { phone: 2 } },
  // A recorded trace: the case view, read from the recording, no chain consulted.
  { name: 'recorded case 11', path: '/demo/11', as: 'investigator', ready: ['heading', { level: 2 }], unmeasured: { desktop: 19, phone: 28 } },
  // Opened from a link, a trace asks before it runs.
  { name: 'trace link', path: '/trace/0x7c3e9bab6715e4040f013e865b193b0209642e36?chain=ethereum&asset=ETH&depth=3&direction=outgoing', as: 'investigator', ready: ['button', { name: 'Run this trace' }] },
  { name: 'batch', path: '/batch/a11y-example', as: 'investigator', stub: { url: '**/batches/a11y-example', body: BATCH }, ready: ['heading', { level: 1, name: BATCH.name }], unmeasured: { phone: 1 } },
  { name: 'verify a report', path: '/verify', ready: ['heading', { level: 1 }] },
  { name: 'citizen page', path: '/citizen', as: 'citizen', ready: ['heading', { level: 1 }] },
]

export const NOT_CHECKED = {
  '/signin': 'sends the browser on to /signin/investigator',
  '/case/:caseId': 'needs a stored case; /demo/11 opens the same case view from a recording',
  '*': 'any other path shows Home',
}
