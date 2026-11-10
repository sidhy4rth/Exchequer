import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Home from './Home'
import { stubFetch } from '../test/setup'
import { CONSOLE_FIELD, OFFICER_SIGN_IN } from '../../e2e/canary.lines.js'
import canarySource from '../../e2e/canary.spec.js?raw'
import recorded from '../../../backend/data/recorded_demos.json'

// The console's home page: one field to start from, the recorded cases to
// try, this browser's recent cases, the exchange wallets on file and the
// watchlist. Every figure on it is one the backend gave.

const health = {
  status: 'ok',
  default_chain: 'ethereum',
  chains: {
    ethereum: { key: 'ethereum', name: 'Ethereum', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }, { symbol: 'USDT' }],
      exchange_labels: 25038, exchange_wallets: 975, deposit_addresses: 24063,
      risk_labels: { sanctioned: 127, mixer: 0, frozen: 2828, stolen: 11 } },
    tron: { key: 'tron', name: 'Tron', ready: true, address_family: 'tron', assets: [{ symbol: 'TRX' }, { symbol: 'USDT' }],
      exchange_labels: 68, exchange_wallets: 67, deposit_addresses: 1,
      risk_labels: { sanctioned: 915, mixer: 0, frozen: 6759, stolen: 0 } },
  },
}
// GET /demos/recorded, from the recordings the backend serves.
const RECORDED = { demos: recorded.map((r) => ({ demo: r.demo, recorded_at: r.recorded_at, address: r.result.address, exchange: r.result.exchange,
  attribution_inferred: Boolean(r.result.attribution_inferred), confidence: r.result.confidence })) }
const NO_CASES = { count: 0, cases: [] }
const WALLET = '0x' + 'ab'.repeat(20)
const TRON_WALLET = 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts'

function Landed() {
  const { pathname, search, state } = useLocation()
  return <p data-testid="landed" data-started={String(state?.startedHere === true)}>{pathname + search}</p>
}

function renderHome({ chains = health, cases = NO_CASES, watches = { count: 0, watches: [] }, demos = RECORDED, extra = {} } = {}) {
  const fetch = stubFetch({
    '/chains': { body: chains }, '/cases': { body: cases }, '/exchanges': { body: {} }, '/risk-labels': { body: {} },
    '/demos/recorded': { body: demos }, '/watches': { body: watches }, ...extra,
  })
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/trace/:address" element={<Landed />} />
        <Route path="/demo/:n" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
  return fetch
}
const loaded = () => screen.findByRole('list', { name: 'Exchange wallets per chain' })
const region = (name) => within(screen.getByRole('region', { name }))

describe('the console hero', () => {
  it('says what the console is for, with no globe behind it and the line about people kept', async () => {
    renderHome()
    await loaded()
    expect(screen.getByRole('heading', { level: 1, name: 'Follow a payment to the exchange that can freeze it' })).toBeInTheDocument()
    expect(screen.getByText('Names an exchange, never a person.')).toBeInTheDocument()
    expect(screen.queryByTestId('globe-bg')).not.toBeInTheDocument()
  })

  it('says every chain is ready only when /chains says so', async () => {
    renderHome()
    expect(await screen.findByText('All 2 chains ready to trace')).toBeInTheDocument()
  })

  it('says nothing about the chains when one of them is not ready', async () => {
    renderHome({ chains: { ...health, chains: { ...health.chains, tron: { ...health.chains.tron, ready: false } } } })
    await loaded()
    expect(screen.queryByText(/chains ready to trace/)).not.toBeInTheDocument()
  })

  it('opens a pasted wallet at its trace link, on the chain and asset chosen, without starting it', async () => {
    const user = userEvent.setup()
    renderHome()
    await loaded()
    await user.selectOptions(screen.getByLabelText('Chain and asset'), 'Ethereum · USDT')
    await user.type(screen.getByLabelText(CONSOLE_FIELD), `  ${WALLET} {Enter}`)
    const landed = screen.getByTestId('landed')
    expect(landed).toHaveTextContent(`/trace/${WALLET}?chain=ethereum&asset=USDT`)
    // The trace page shows what it would run and waits for a click.
    expect(landed).toHaveAttribute('data-started', 'false')
  })

  it('fills the new trace form with a pasted payment hash', async () => {
    const user = userEvent.setup()
    renderHome()
    await loaded()
    const hash = '0x' + 'cd'.repeat(32)
    await user.type(screen.getByLabelText(CONSOLE_FIELD), hash)
    await user.click(screen.getByRole('button', { name: 'Trace' }))
    expect(screen.getByTestId('landed')).toHaveTextContent(`/trace/new?pay=${hash}&chain=ethereum&asset=ETH`)
  })

  it('moves to a chain that reads what was pasted: a Tron wallet, a hash without 0x', async () => {
    const user = userEvent.setup()
    renderHome()
    await loaded()
    const pick = screen.getByLabelText('Chain and asset')
    expect(pick).toHaveValue('ethereum:ETH')
    await user.type(screen.getByLabelText(CONSOLE_FIELD), TRON_WALLET)
    // Tron's complaints are almost always USDT.
    expect(pick).toHaveValue('tron:USDT')
    await user.keyboard('{Enter}')
    expect(screen.getByTestId('landed')).toHaveTextContent(`/trace/${TRON_WALLET}?chain=tron&asset=USDT`)
  })

  it('reads a hash without 0x as Tron', async () => {
    const user = userEvent.setup()
    renderHome()
    await loaded()
    const hash = 'e'.repeat(64)
    await user.type(screen.getByLabelText(CONSOLE_FIELD), `${hash}{Enter}`)
    expect(screen.getByTestId('landed')).toHaveTextContent(`/trace/new?pay=${hash}&chain=tron&asset=USDT`)
  })

  it('says in place what it did not recognise, and goes nowhere', async () => {
    const user = userEvent.setup()
    renderHome()
    await loaded()
    const field = screen.getByLabelText(CONSOLE_FIELD)
    await user.type(field, '0x1234{Enter}')
    expect(screen.getByRole('alert')).toHaveTextContent(/Not recognised/)
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(field).toHaveAccessibleDescription(/Not recognised/)
    expect(screen.queryByTestId('landed')).not.toBeInTheDocument()
    await user.type(field, '5')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('offers three recorded cases, named from their recordings, each opening as recorded', async () => {
    const user = userEvent.setup()
    renderHome()
    const tries = within(await screen.findByRole('list', { name: 'Try a recorded case' }))
    const links = tries.getAllByRole('link')
    expect(links.map((a) => [a.textContent, a.getAttribute('href')])).toEqual([
      ['Tron USDT to Binance', '/demo/11'],
      ['Tron USDT to Flipster', '/demo/12'],
      // Demo 7's recording infers its Bybit deposit address: the chip says so.
      ['Ethereum ETH to a probable Bybit deposit', '/demo/7'],
    ])
    await user.click(links[1])
    expect(screen.getByTestId('landed')).toHaveTextContent('/demo/12')
  })

  it('names an exchange the recording inferred as a probable deposit', async () => {
    const as = (inferred) => ({ demos: [{ ...RECORDED.demos.find((d) => d.demo === 11), attribution_inferred: inferred }] })
    renderHome({ demos: as(true) })
    expect(await screen.findByRole('link', { name: 'Tron USDT to a probable Binance deposit' })).toBeInTheDocument()
  })

  it('fits its hint inside the field on a phone', async () => {
    const narrow = (query) => ({ matches: query === '(max-width: 720px)', addEventListener: () => {}, removeEventListener: () => {} })
    renderHome()
    await loaded()
    expect(screen.getByLabelText(CONSOLE_FIELD)).toHaveAttribute('placeholder', "Victim's payment hash, or the wallet they paid")
    vi.stubGlobal('matchMedia', narrow)
    cleanup()
    renderHome()
    await loaded()
    // The phone's field holds about 38 characters before its hint is cut.
    expect(screen.getByLabelText(CONSOLE_FIELD)).toHaveAttribute('placeholder', CONSOLE_FIELD)
  })

  it('draws its own chevron inside the chain choice, clear of the round edge', async () => {
    renderHome()
    await loaded()
    const pick = screen.getByLabelText('Chain and asset')
    expect(pick.parentElement).toHaveClass('hero-chain')
    expect(pick.parentElement.querySelector(':scope > svg[aria-hidden="true"]')).not.toBeNull()
    // A literal path here would be rewritten by Vite into an asset URL.
    const sheet = '../styles.css'
    const css = readFileSync(new URL(sheet, import.meta.url), 'utf8')
    const rule = /\.hero-chain select \{([^}]*)\}/.exec(css)?.[1] ?? ''
    expect(rule).toMatch(/appearance: none/)
    expect(rule).toMatch(/padding: 0 40px 0 18px/)
  })

  it('offers no recorded case the site has no recording of', async () => {
    renderHome({ demos: { demos: RECORDED.demos.filter((d) => d.demo === 12) } })
    const tries = within(await screen.findByRole('list', { name: 'Try a recorded case' }))
    expect(tries.getAllByRole('link')).toHaveLength(1)
  })

  it('is the field the site canary looks for', async () => {
    renderHome()
    expect(await screen.findByLabelText(CONSOLE_FIELD)).toBeInTheDocument()
    expect(canarySource).toContain('getByLabel(CONSOLE_FIELD)')
  })
})

describe('recent cases', () => {
  const CASES = {
    count: 3,
    cases: [
      { case_id: 'c-1', address: TRON_WALLET, chain: 'tron', asset: 'USDT', direction: 'outgoing', exchange: 'Bin​ance', confidence: 0.49, hop_count: 2, created_at: '2026-11-09T10:00:00+00:00' },
      { case_id: 'c-2', address: WALLET, chain: 'ethereum', asset: 'ETH', direction: 'outgoing', exchange: 'Bybit', confidence: 0.7728, hop_count: 1, created_at: '2026-11-09T09:00:00+00:00' },
      { case_id: 'c-3', address: '0x' + '12'.repeat(20), chain: 'ethereum', asset: 'ETH', direction: 'incoming', exchange: null, confidence: null, hop_count: 1, created_at: '2026-11-09T08:00:00+00:00' },
    ],
  }

  it('lists each case with the exchange it reached and the band word, never the score', async () => {
    const fetch = renderHome({ cases: CASES })
    const card = within(await screen.findByRole('region', { name: 'Recent cases' }))
    const first = await card.findByRole('link', { name: new RegExp(`^${TRON_WALLET}`) })
    expect(first).toHaveAttribute('href', '/case/c-1')
    expect(first).toHaveTextContent('Tron USDT · 2 hops')
    expect(first).toHaveTextContent(/Binance\s*Confidence Low$/)
    expect(card.getByRole('link', { name: new RegExp(`^${WALLET}`) })).toHaveTextContent(/Bybit\s*Confidence High$/)
    const reverse = card.getByRole('link', { name: /^0x1212/ })
    expect(reverse).toHaveTextContent('Ethereum ETH · 1 hop · reverse')
    expect(reverse).toHaveTextContent(/No exchange$/)
    expect(screen.getByRole('region', { name: 'Recent cases' }).textContent).not.toMatch(/0\.\d|​/)
    expect(card.getByRole('link', { name: 'All cases' })).toHaveAttribute('href', '/cases')
    expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/cases?limit=5'))).toBe(true)
  })

  it('marks the recorded demos the site keeps, as the Cases page does, so none reads as this browser\'s own', async () => {
    const own = CASES.cases[1]
    renderHome({ cases: { count: 2, cases: [{ ...CASES.cases[0], demo: true }, { ...own, demo: false }] } })
    const card = within(await screen.findByRole('region', { name: 'Recent cases' }))
    expect(await card.findByRole('link', { name: new RegExp(`^${TRON_WALLET}.*demo`) })).toHaveAttribute('href', '/case/c-1')
    expect(card.getByRole('link', { name: new RegExp(`^${WALLET}`) })).not.toHaveTextContent('demo')
  })

  it('says when there are none yet', async () => {
    renderHome()
    expect(await screen.findByText(/No cases yet/)).toBeInTheDocument()
  })

  it('says the cases are loading until /cases answers', async () => {
    renderHome()
    const card = within(screen.getByRole('region', { name: 'Recent cases' }))
    expect(card.getByRole('status')).toHaveTextContent('Loading cases…')
    expect(await card.findByText(/No cases yet/)).toBeInTheDocument()
    expect(card.queryByText('Loading cases…')).not.toBeInTheDocument()
  })

  it('says the cases cannot be reached, never that there are none, when /cases fails', async () => {
    renderHome({ extra: { '/cases': { status: 500, body: { detail: 'down' } } } })
    const card = within(await screen.findByRole('region', { name: 'Recent cases' }))
    expect(await card.findByText('Recent cases cannot be reached right now.')).toBeInTheDocument()
    expect(card.queryByText(/No cases yet/)).not.toBeInTheDocument()
  })
})

describe('exchange wallets on file', () => {
  it('counts exchange wallets per chain from /chains, largest first, with deposit addresses apart', async () => {
    renderHome()
    const bars = await loaded()
    expect(within(bars).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Ethereum975', 'Tron67'])
    const card = region('Exchange wallets on file')
    expect(card.getByText('1,042')).toBeInTheDocument()
    expect(card.getByText('plus 24,063 Ethereum and 1 Tron deposit addresses')).toBeInTheDocument()
  })

  it('shows only numbers that /chains gives, and never one total as exchange wallets', async () => {
    renderHome()
    await loaded()
    const chains = Object.values(health.chains)
    const sum = (f) => chains.reduce((s, c) => s + f(c), 0)
    const allowed = new Set([
      sum((c) => c.exchange_wallets), sum((c) => c.deposit_addresses),
      ...chains.flatMap((c) => [c.exchange_wallets, c.deposit_addresses, ...Object.values(c.risk_labels)]),
    ])
    // Text node by text node: textContent would run neighbouring cells together.
    const shown = []
    for (const root of [screen.getByRole('region', { name: 'Exchange wallets on file' }), screen.getByRole('group', { name: 'Coverage' })]) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
      while (walker.nextNode()) {
        for (const m of walker.currentNode.nodeValue.match(/\d[\d,]*(?:\.\d+)?/g) ?? []) shown.push(Number(m.replace(/,/g, '')))
      }
    }
    expect(shown.length).toBeGreaterThan(10)
    for (const n of shown) expect(allowed, `${n} is not from /chains`).toContain(n)
    expect(document.body.textContent).not.toMatch(/25,?038|25,?106/)
  })
})

describe('the coverage tables', () => {
  it('wait behind a disclosure, so the console opens on the field and the cards', async () => {
    const user = userEvent.setup()
    renderHome()
    await loaded()
    const table = screen.getByRole('table', { name: 'Exchange labels per chain', hidden: true })
    expect(table).not.toBeVisible()
    const open = screen.getByText('Exchange labels and risk screening per chain')
    expect(open.closest('summary')).not.toBeNull()
    await user.click(open)
    expect(table).toBeVisible()
    expect(screen.getByRole('table', { name: 'Risk screening per chain' })).toBeVisible()
  })
})

describe('the mixers note under the coverage tables', () => {
  const card = () => within(screen.getByRole('group', { name: 'Coverage' }))
  it('never says the count is zero beside a count that is not', async () => {
    const tagged = { ...health, chains: { ...health.chains, ethereum: { ...health.chains.ethereum, risk_labels: { ...health.chains.ethereum.risk_labels, mixer: 40 } } } }
    renderHome({ chains: tagged })
    await loaded()
    expect(card().getByRole('table', { name: 'Risk screening per chain', hidden: true })).toHaveTextContent('40')
    expect(card().queryByText(/count is zero|have none/)).not.toBeInTheDocument()
    expect(card().getByText(/Mixers here are explorer-tagged/)).toBeInTheDocument()
  })

  it('never claims every counted mixer stops a trace (only a pinned pool or entry point does)', async () => {
    const tagged = { ...health, chains: { ...health.chains, ethereum: { ...health.chains.ethereum, risk_labels: { ...health.chains.ethereum.risk_labels, mixer: 40 } } } }
    renderHome({ chains: tagged })
    await loaded()
    expect(card().queryByText(/A trace stops at a mixer\./)).not.toBeInTheDocument()
    expect(card().getByText(/A trace stops at a mixer's pool or entry point\./)).toBeInTheDocument()
  })

  it('says why there are none only when every chain has none', async () => {
    renderHome()
    await loaded()
    expect(card().getByText(/these chains have none/)).toBeInTheDocument()
    expect(card().queryByText(/explorer-tagged; /)).not.toBeInTheDocument()
  })
})

describe('the watchlist card', () => {
  it('says how many wallets this browser watches, and opens the watchlist', async () => {
    const watched = (n) => ({ watch_id: `w${n}`, address: WALLET, chain: 'ethereum', asset: 'ETH', note: '' })
    renderHome({ watches: { count: 2, watches: [watched(1), watched(2)] } })
    const card = within(await screen.findByRole('region', { name: 'Watchlist' }))
    expect(await card.findByText('2 wallets watched.')).toBeInTheDocument()
    expect(card.getByRole('link', { name: 'Open the watchlist' })).toHaveAttribute('href', '/watchlist')
  })

  it('says nothing is watched yet', async () => {
    renderHome()
    const card = within(await screen.findByRole('region', { name: 'Watchlist' }))
    expect(await card.findByText(/Nothing watched yet\. Watch a wallet from any case/)).toBeInTheDocument()
  })
})

describe('a public site that asks for a demo code', () => {
  const recordings = { demos: [{ demo: 6, recorded_at: '2026-10-14T16:44:03+00:00', address: '0x00000000072d54638c2c2a3da3f715360269eea1', exchange: 'Binance', confidence: 0.875 }] }

  async function renderPublicHome(check = { status: 403, body: { detail: 'That access code is not right.' } }) {
    const fetch = stubFetch({
      '/chains': { body: health }, '/cases': { body: NO_CASES }, '/demos/recorded': { body: recordings },
      '/access': { body: { demo_code_required: true } }, '/access/check': check,
    })
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/demo/:n" element={<Landed />} />
        </Routes>
      </MemoryRouter>,
    )
    await screen.findByLabelText('Access code')
    return fetch
  }

  it('shows the recorded demos and no way to start a trace, batch or watch', async () => {
    const user = userEvent.setup()
    await renderPublicHome()
    expect(screen.queryByLabelText(CONSOLE_FIELD)).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Bulk intake' })).not.toBeInTheDocument()
    expect(screen.queryByText('Bulk intake')).not.toBeInTheDocument()
    expect(screen.queryByText(/^Watchlist/)).not.toBeInTheDocument()
    await user.click(await screen.findByRole('link', { name: /reached Binance/ }))
    expect(screen.getByTestId('landed')).toHaveTextContent('/demo/6')
  })

  it('keeps the site locked and remembers nothing when the code is wrong', async () => {
    const user = userEvent.setup()
    await renderPublicHome()
    await user.type(screen.getByLabelText('Access code'), 'guess{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('not right')
    expect(screen.queryByLabelText(CONSOLE_FIELD)).not.toBeInTheDocument()
    expect(sessionStorage.getItem('exchequer-demo-code')).toBeNull()
  })

  it('unlocks live tracing with the right code and sends it from then on', async () => {
    const user = userEvent.setup()
    const fetch = await renderPublicHome({ body: { ok: true } })
    await user.type(screen.getByLabelText('Access code'), 'river-otter-42{Enter}')
    expect(await screen.findByLabelText(CONSOLE_FIELD)).toBeInTheDocument()
    expect(sessionStorage.getItem('exchequer-demo-code')).toBe('river-otter-42')
    // Requests after the check itself, which carries the typed code by design.
    const checked = fetch.mock.calls.findIndex(([url]) => String(url).includes('/access/check'))
    const after = fetch.mock.calls.slice(checked + 1)
    expect(after.length).toBeGreaterThan(0)
    for (const [, init] of after) expect(new Headers(init.headers).get('X-Exchequer-Demo-Code')).toBe('river-otter-42')
  })

  it('keeps the pass the right code returns, never the code itself', async () => {
    const user = userEvent.setup()
    const fetch = await renderPublicHome({ body: { ok: true, pass: 'v1.1999999999.nonce.mac', expires_in: 43200 } })
    await user.type(screen.getByLabelText('Access code'), 'river-otter-42{Enter}')
    expect(await screen.findByLabelText(CONSOLE_FIELD)).toBeInTheDocument()
    expect(sessionStorage.getItem('exchequer-demo-pass')).toBe('v1.1999999999.nonce.mac')
    expect(sessionStorage.getItem('exchequer-demo-code')).toBeNull()
    const checked = fetch.mock.calls.findIndex(([url]) => String(url).includes('/access/check'))
    const after = fetch.mock.calls.slice(checked + 1)
    expect(after.length).toBeGreaterThan(0)
    for (const [, init] of after) {
      const headers = new Headers(init.headers)
      expect(headers.get('X-Exchequer-Demo-Pass')).toBe('v1.1999999999.nonce.mac')
      expect(headers.has('X-Exchequer-Demo-Code')).toBe(false)
    }
  })
})

describe('a site the owner has closed to officers', () => {
  const recordings = { demos: [{ demo: 6, recorded_at: '2026-10-14T16:44:03+00:00', address: '0x00000000072d54638c2c2a3da3f715360269eea1', exchange: 'Binance', confidence: 0.875 }] }

  function renderClosedHome(access) {
    stubFetch({
      '/chains': { body: health }, '/cases': { body: NO_CASES }, '/demos/recorded': { body: recordings },
      '/watches': { body: { count: 0, watches: [] } }, '/access': { body: access },
    })
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/demo/:n" element={<Landed />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('sends a visitor to the officer sign-in instead of asking for the demo code, and the demos still open', async () => {
    const user = userEvent.setup()
    renderClosedHome({ demo_code_required: true, console: 'officers', officer: false })
    const link = await screen.findByRole('link', { name: 'Sign in as an officer to trace live' })
    expect(link).toHaveAttribute('href', '/signin/investigator')
    expect(screen.queryByLabelText('Access code')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(CONSOLE_FIELD)).not.toBeInTheDocument()
    await user.click(await screen.findByRole('link', { name: /reached Binance/ }))
    expect(screen.getByTestId('landed')).toHaveTextContent('/demo/6')
  })

  it('gives a signed-in officer the trace field, with no code asked', async () => {
    renderClosedHome({ demo_code_required: true, console: 'officers', officer: true })
    expect(await screen.findByLabelText(CONSOLE_FIELD)).toBeInTheDocument()
    expect(screen.queryByLabelText('Access code')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Sign in as an officer to trace live' })).not.toBeInTheDocument()
  })

  it('is the link the site canary accepts in place of the field, so closing the site keeps the canary green', async () => {
    renderClosedHome({ demo_code_required: false, console: 'officers', officer: false })
    expect(await screen.findByRole('link', { name: OFFICER_SIGN_IN })).toBeInTheDocument()
    // The canary waits for the console through one helper that accepts the
    // link, in both tests that open it (the front door; nothing from elsewhere).
    const helper = /const consoleReady = [^]*?\n\n/.exec(canarySource)?.[0] ?? ''
    expect(helper).toContain('getByLabel(CONSOLE_FIELD)')
    expect(helper).toContain("getByRole('link', { name: OFFICER_SIGN_IN })")
    expect(canarySource.match(/expect\(consoleReady\(page\)\)\.toBeVisible\(\)/g)).toHaveLength(2)
    expect(canarySource.split('getByLabel(CONSOLE_FIELD)')).toHaveLength(2)
    // /health keeps "access": "open" when no code is set; closed to officers is closed too.
    expect(canarySource).toMatch(/EXPECT_DEMO_CODE && health.console !== 'officers'/)
  })
})

describe('motion', () => {
  // Read from disk: vitest hands a stylesheet imported with ?raw back empty.
  const sheet = './Home.css'
  const motionCss = readFileSync(new URL(sheet, import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
  const reduceMotion = (query) => ({ matches: query === '(prefers-reduced-motion: reduce)', addEventListener: () => {}, removeEventListener: () => {} })
  const root = () => document.querySelector('.home.console')
  /** The rules outside @keyframes and outside the reduced-motion block, as [selector, body]. */
  function rules() {
    const flat = motionCss.replace(/@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*[^}]*\}/g, '')
      .replace(/@media \(prefers-reduced-motion: reduce\) \{[\s\S]*?\}\s*\}/, '')
      .replace(/@media [^{]*\{([\s\S]*?\})\s*\}/g, '$1')
    return [...flat.matchAll(/([^{}]+)\{([^}]*)\}/g)].map(([, sel, body]) => [sel.trim(), body])
  }
  const animated = () => rules().filter(([sel, body]) => /animation(-name)?:/.test(body) && !/animation: none/.test(body))
    .flatMap(([sel]) => sel.split(',').map((s) => s.trim()))
    .filter((s) => s.startsWith('.console-home ') && !s.startsWith('.console-home.'))
  afterEach(() => { try { localStorage.clear() } catch { /* none */ } })

  it('keeps every word on the page: the hint typed in is a hidden copy of the field\'s own placeholder', async () => {
    const user = userEvent.setup()
    renderHome()
    await loaded()
    const field = screen.getByLabelText(CONSOLE_FIELD)
    expect(field).toHaveAttribute('placeholder', "Victim's payment hash, or the wallet they paid")
    const typed = field.parentElement.querySelector('.hero-typed')
    expect(typed).toHaveAttribute('aria-hidden', 'true')
    expect(typed.textContent).toBe(field.getAttribute('placeholder'))
    // One letter per step, each in its turn.
    const letters = [...typed.children]
    expect(letters).toHaveLength(field.getAttribute('placeholder').length)
    expect(letters.map((l) => l.style.getPropertyValue('--i'))).toEqual(letters.map((_, i) => String(i)))
    // It never takes the click or the key: the field still types.
    expect(motionCss).toMatch(/\.hero-typed \{[^}]*pointer-events: none/)
    expect(motionCss).toMatch(/input:not\(:placeholder-shown\) \+ \.hero-typed \{[^}]*visibility: hidden/)
    await user.type(field, WALLET)
    expect(field).toHaveValue(WALLET)
  })

  it('brings the sections in one after another, 60 ms apart and never more than 8 steps', async () => {
    renderHome()
    await loaded()
    const steps = [...document.querySelectorAll('.console-rise')].map((el) => Number(el.style.getPropertyValue('--rise')))
    expect(steps).toEqual([0, 1, 2, 3, 4, 5, 6, 7])
    expect(screen.getByRole('region', { name: 'Start a trace' })).toHaveClass('console-rise')
    expect(screen.getByRole('region', { name: 'Recent cases' })).toHaveClass('console-rise')
    expect(motionCss).toMatch(/animation-delay: calc\(var\(--rise, 0\) \* 60ms\)/)
    expect(motionCss).toMatch(/var\(--ease-enter, cubic-bezier\(0\.22, 1, 0\.36, 1\)\)/)
  })

  it('grows each exchange bar from its start, at the width /chains gives', async () => {
    renderHome()
    const bars = [...(await loaded()).querySelectorAll('.bar i')]
    expect(bars.map((b) => b.style.width)).toEqual(['100%', `${(67 / 975) * 100}%`])
    expect(bars.map((b) => b.style.getPropertyValue('--i'))).toEqual(['0', '1'])
    expect(motionCss).toMatch(/@keyframes console-grow \{ from \{ transform: scaleX\(0\); \} \}/)
  })

  it('shows the radar only on an empty watchlist, hidden from screen readers', async () => {
    renderHome()
    const card = within(await screen.findByRole('region', { name: 'Watchlist' }))
    await card.findByText(/Nothing watched yet/)
    expect(document.querySelector('.watch-radar')).toHaveAttribute('aria-hidden', 'true')
    cleanup()
    const watched = { watch_id: 'w1', address: WALLET, chain: 'ethereum', asset: 'ETH', note: '' }
    renderHome({ watches: { count: 1, watches: [watched] } })
    expect(await screen.findByText('1 wallet watched.')).toBeInTheDocument()
    expect(document.querySelector('.watch-radar')).toBeNull()
  })

  it('draws everything at its final state when reduced motion is asked for, with no switch to show', async () => {
    vi.stubGlobal('matchMedia', reduceMotion)
    renderHome()
    await loaded()
    expect(root()).toHaveClass('still')
    expect(screen.queryByRole('button', { name: 'Pause motion' })).not.toBeInTheDocument()
    // Every word is still there.
    expect(screen.getByRole('heading', { level: 1, name: 'Follow a payment to the exchange that can freeze it' })).toBeInTheDocument()
    expect(screen.getByLabelText(CONSOLE_FIELD)).toBeInTheDocument()
    expect(await screen.findByText(/Nothing watched yet/)).toBeInTheDocument()
  })

  it('turns every animation it starts off under reduced motion, in CSS and under .still', () => {
    const list = animated()
    expect(list.length).toBeGreaterThan(8)
    const reduced = /@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\}\s*\}/.exec(motionCss)?.[1] ?? ''
    expect(reduced).toMatch(/animation: none !important/)
    const still = rules().find(([sel]) => sel.startsWith('.console-home.still'))
    expect(still?.[1]).toMatch(/animation: none !important/)
    for (const sel of list) {
      expect(reduced.split('{')[0].split(',').map((s) => s.trim())).toContain(sel)
      expect(still[0].split(',').map((s) => s.trim())).toContain(sel.replace('.console-home ', '.console-home.still '))
    }
  })

  it('styles every entrance at its end, so taking the animation away leaves the page whole', () => {
    // Only a @keyframes "from" hides or shrinks anything that enters.
    const entrances = rules().filter(([sel]) => /console-rise|showroom|hero-typed|wallet-bars|recent-cases/.test(sel))
    for (const [, body] of entrances) {
      expect(body).not.toMatch(/opacity: 0\b/)
      expect(body).not.toMatch(/scaleX\(0\)/)
      expect(body).not.toMatch(/animation[^;]*\b(forwards|both)\b/)
    }
  })

  it('keeps every loop slow (3 s or more), and stops each one with Pause motion', async () => {
    const user = userEvent.setup()
    const loops = rules().filter(([, body]) => /infinite/.test(body))
    expect(loops.length).toBeGreaterThanOrEqual(5)
    for (const [sel, body] of loops) {
      const seconds = Number(/(\d+(?:\.\d+)?)(m?s) [^;]*infinite/.exec(body)?.[1]) / (/\d(ms) [^;]*infinite/.test(body) ? 1000 : 1)
      expect(seconds, sel).toBeGreaterThanOrEqual(3)
      const paused = rules().find(([s]) => s.startsWith('.console-home.paused'))
      expect(paused[0].split(',').map((s) => s.trim())).toContain(sel.replace('.console-home ', '.console-home.paused '))
    }
    renderHome()
    await loaded()
    const pause = screen.getByRole('button', { name: 'Pause motion' })
    expect(pause).toHaveAttribute('aria-pressed', 'false')
    expect(root()).not.toHaveClass('paused')
    await user.click(pause)
    expect(pause).toHaveAttribute('aria-pressed', 'true')
    expect(root()).toHaveClass('paused')
    // Remembered in this browser, so the next visit opens still.
    cleanup()
    renderHome()
    await loaded()
    expect(screen.getByRole('button', { name: 'Pause motion' })).toHaveAttribute('aria-pressed', 'true')
    expect(root()).toHaveClass('paused')
    await user.click(screen.getByRole('button', { name: 'Pause motion' }))
    expect(root()).not.toHaveClass('paused')
  })

  it('moves in neutral grey only: no new green, and the ready dot is not green', () => {
    expect(motionCss).not.toMatch(/--go\b|--green|--exchange/)
    expect(motionCss).toMatch(/\.console-home \.hero-status i \{[^}]*background: var\(--text-2\)/)
    // The glow sits behind everything and takes no click.
    expect(motionCss).toMatch(/\.console-ambient \{[^}]*z-index: -1[^}]*pointer-events: none/)
  })
})
