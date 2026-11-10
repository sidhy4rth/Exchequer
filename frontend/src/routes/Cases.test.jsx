import { readFileSync } from 'node:fs'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Cases from './Cases'
import { stubFetch } from '../test/setup'

// The Cases page (/cases): every stored case this browser may see, its own
// and the recorded demos, filtered by what it reached or its chain and
// searched by wallet, exchange or case; then the complaints that meet at one
// wallet (GET /cases/correlate). R10 holds: a case shows its band, never the
// decimal. An exchange's name is outside text and is shown as plain() reads it.

const TRON = 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts'
const ETH = `0x${'ab'.repeat(20)}`
const ETH2 = `0x${'cd'.repeat(20)}`
const SHARED = `0x${'ef'.repeat(20)}`
const ZWSP = '​'

const STORED = {
  count: 3,
  cases: [
    // 20:00 UTC is 01:30 the next morning in India.
    { case_id: 'c-tron', address: TRON, chain: 'tron', asset: 'USDT', direction: 'outgoing', exchange: `Bin${ZWSP}ance`, confidence: 0.875,
      flags: [], hop_count: 2, node_count: 30, created_at: '2026-11-04T20:00:00+00:00', demo: true },
    { case_id: 'c-eth', address: ETH, chain: 'ethereum', asset: 'ETH', direction: 'outgoing', exchange: 'Bybit', confidence: 0.49,
      flags: [], hop_count: 1, node_count: 9, created_at: '2026-11-04T10:00:00+00:00', demo: false },
    { case_id: 'c-none', address: ETH2, chain: 'ethereum', asset: 'ETH', direction: 'incoming', exchange: null, confidence: null,
      flags: [], hop_count: 2, node_count: 11, created_at: '2026-10-14T16:52:10+00:00', demo: false },
  ],
}
const NONE_LINKED = { cases_examined: 3, cluster_count: 0, clusters: [] }

function Landed() {
  return <p data-testid="landed">{useLocation().pathname}</p>
}

function open({ cases = STORED, linked = NONE_LINKED } = {}) {
  const fetch = stubFetch({ '/cases': cases.status ? cases : { body: cases }, '/cases/correlate': linked.status ? linked : { body: linked } })
  render(
    <MemoryRouter initialEntries={['/cases']}>
      <Routes>
        <Route path="/case/:id" element={<Landed />} />
        <Route path="/cases" element={<Cases />} />
      </Routes>
    </MemoryRouter>,
  )
  return fetch
}

const table = () => screen.findByRole('table', { name: 'Stored cases' })
const rowOf = (address) => screen.getByRole('link', { name: address }).closest('tr')
const shown = () => within(screen.getByRole('table', { name: 'Stored cases' })).queryAllByRole('link').map((a) => a.textContent)
/** A screen `width` px wide: each (max-width) query the page asks matches as a browser would. */
const screenOf = (width) => vi.stubGlobal('matchMedia', (query) => ({
  matches: Number(/max-width:\s*(\d+)px/.exec(query)?.[1] ?? -1) >= width, addEventListener: () => {}, removeEventListener: () => {},
}))

describe('the cases page', () => {
  it('is headed Cases, with the line the pack puts over it', async () => {
    open()
    expect(screen.getByRole('heading', { level: 1, name: 'Cases' })).toBeInTheDocument()
    expect(screen.getByText('Stored cases · yours and the recorded demos')).toBeInTheDocument()
    await table()
  })

  it('lists each case: the wallet, chain and asset, what it reached, how sure as a word, hops, wallets and the day in India', async () => {
    open()
    const list = await table()
    expect(within(list).getAllByRole('columnheader').map((h) => h.textContent))
      .toEqual(['Reported wallet', 'Chain', 'Reached', 'How sure', 'Hops', 'Wallets', 'Traced (IST)'])
    const tron = within(rowOf(TRON))
    expect(tron.getByRole('link', { name: TRON })).toHaveAttribute('href', '/case/c-tron')
    expect(tron.getByRole('link', { name: TRON })).toHaveClass('mono')
    expect(tron.getAllByRole('cell').map((c) => c.textContent))
      .toEqual([`${TRON}demo`, 'Tron USDT', 'Binance', 'High', '2', '30', '5 Nov 2026'])
    const none = within(rowOf(ETH2))
    expect(none.getAllByRole('cell').map((c) => c.textContent))
      .toEqual([`${ETH2}reverse`, 'Ethereum ETH', 'no exchange reached', 'n/a', '—', '11', '14 Oct 2026'])
    expect(within(rowOf(ETH)).getByText('Low')).toBeInTheDocument()
    // The band, never the score; a name with a hidden character reads as it looks.
    expect(list.textContent).not.toMatch(/0\.\d/)
    expect(list.textContent).not.toContain(ZWSP)
  })

  it('marks the recorded demos, so none reads as this browser\'s own', async () => {
    open()
    await table()
    expect(within(rowOf(TRON)).getByText('demo')).toBeInTheDocument()
    expect(within(rowOf(ETH)).queryByText('demo')).not.toBeInTheDocument()
  })

  it('opens a case from its row, by keyboard', async () => {
    const user = userEvent.setup()
    open()
    await table()
    screen.getByRole('link', { name: ETH }).focus()
    await user.keyboard('{Enter}')
    expect(screen.getByTestId('landed')).toHaveTextContent('/case/c-eth')
  })

  it('counts each filter, and a pressed one keeps only its cases', async () => {
    const user = userEvent.setup()
    open()
    await table()
    const filters = within(screen.getByRole('group', { name: 'Filter cases' }))
    expect(filters.getAllByRole('button').map((b) => b.textContent))
      .toEqual(['All · 3', 'Reached an exchange · 2', 'No exchange · 1', 'Ethereum · 2', 'Tron · 1'])
    expect(filters.getByRole('button', { name: 'All · 3' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(filters.getByRole('button', { name: 'No exchange · 1' }))
    expect(filters.getByRole('button', { name: 'No exchange · 1' })).toHaveAttribute('aria-pressed', 'true')
    expect(filters.getByRole('button', { name: 'All · 3' })).toHaveAttribute('aria-pressed', 'false')
    expect(shown()).toEqual([ETH2])
    expect(screen.getByRole('status')).toHaveTextContent('1 of 3 cases shown')

    filters.getByRole('button', { name: 'Tron · 1' }).focus()
    await user.keyboard('{Enter}')
    expect(shown()).toEqual([TRON])
    await user.click(filters.getByRole('button', { name: 'Reached an exchange · 2' }))
    expect(shown()).toEqual([TRON, ETH])
    await user.click(filters.getByRole('button', { name: 'All · 3' }))
    expect(shown()).toEqual([TRON, ETH, ETH2])
    expect(screen.getByRole('status')).toHaveTextContent('')
  })

  it('searches by wallet, exchange or case, on the page', async () => {
    const user = userEvent.setup()
    const fetch = open()
    await table()
    const box = within(screen.getByRole('search', { name: 'Search cases' })).getByRole('searchbox', { name: 'Search cases' })
    expect(box).toHaveAttribute('placeholder', 'Wallet, exchange or case')
    const asked = fetch.mock.calls.length
    await user.type(box, 'tuvngw2z')
    expect(shown()).toEqual([TRON])
    await user.clear(box)
    await user.type(box, 'BYBIT')
    expect(shown()).toEqual([ETH])
    await user.clear(box)
    await user.type(box, 'binance')
    expect(shown()).toEqual([TRON])
    await user.clear(box)
    await user.type(box, 'c-none')
    expect(shown()).toEqual([ETH2])
    expect(screen.getByRole('status')).toHaveTextContent('1 of 3 cases shown')
    await user.clear(box)
    await user.type(box, 'nothing like it')
    expect(screen.queryByRole('table', { name: 'Stored cases' })).not.toBeInTheDocument()
    expect(screen.getByText('No case matches.')).toBeInTheDocument()
    // A search reads the cases already loaded; it never asks the server.
    expect(fetch.mock.calls.length).toBe(asked)
  })

  it('asks for every case a browser may keep, so an older one can still be found', async () => {
    const user = userEvent.setup()
    const many = Array.from({ length: 60 }, (_, i) => ({ ...STORED.cases[1], case_id: `c-${i}`, address: `0x${String(i).padStart(40, '0')}` }))
    const fetch = open({ cases: { count: 60, cases: many } })
    await table()
    const asked = new URL(fetch.mock.calls.find(([url]) => String(url).includes('/cases?'))[0], 'http://x')
    // The backend's own most: up to 200 cases per browser, plus the demos.
    expect(Number(asked.searchParams.get('limit'))).toBe(500)
    await user.type(screen.getByRole('searchbox', { name: 'Search cases' }), many[59].address)
    expect(shown()).toEqual([many[59].address])
  })

  it('says a search covers only the newest cases when the list is cut short', async () => {
    const user = userEvent.setup()
    const full = Array.from({ length: 500 }, (_, i) => ({ ...STORED.cases[1], case_id: `c-${i}`, address: `0x${String(i).padStart(40, '0')}` }))
    open({ cases: { count: 500, cases: full } })
    await table()
    expect(screen.getByText(/The newest 500 are listed/)).toBeInTheDocument()
    await user.type(screen.getByRole('searchbox', { name: 'Search cases' }), 'nothing like it')
    expect(screen.getByText('No case among the newest 500 matches.')).toBeInTheDocument()
  })

  it('shows each case as a card on a phone', async () => {
    screenOf(390)
    open()
    const list = within(await screen.findByRole('list', { name: 'Stored cases' }))
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    const tron = list.getByRole('link', { name: new RegExp(`^${TRON}`) })
    expect(tron).toHaveAttribute('href', '/case/c-tron')
    expect(tron).toHaveTextContent('Tron USDT · 2 hops · 30 wallets · 5 Nov 2026')
    expect(tron).toHaveTextContent('demo')
    expect(tron).toHaveTextContent(/Binance\s*Confidence High$/)
    expect(list.getByRole('link', { name: new RegExp(`^${ETH2}`) })).toHaveTextContent(/Ethereum ETH · 11 wallets · 14 Oct 2026.*reverse.*No exchange$/)
  })

  // Above 720 px the sidebar keeps 248 px, so on a tablet (an iPad is 744 to
  // 834 px wide) the seven columns would not fit beside it: the table would
  // scroll sideways, cut "Traced (IST)" off and wrap each wallet every few
  // characters. Until the column is wide enough, the cases stay cards.
  it.each([744, 768, 820, 834, 900])('keeps the cases as cards beside the sidebar at %s px', async (width) => {
    screenOf(width)
    open()
    expect(await screen.findByRole('list', { name: 'Stored cases' })).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it.each([960, 1024, 1280, 1440])('shows the table once it fits beside the sidebar, at %s px', async (width) => {
    screenOf(width)
    open()
    expect(await table()).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Stored cases' })).not.toBeInTheDocument()
  })

  // The pack's band-first reading: only High is drawn strong; Moderate, Low
  // and Very low share one faint pill in the softer grey; n/a has none.
  it('draws only a High band strong, the lower bands faint and n/a bare', async () => {
    open({ cases: { count: 4, cases: [...STORED.cases, { ...STORED.cases[1], case_id: 'c-mid', address: SHARED, confidence: 0.6 }] } })
    await table()
    const pill = (address) => within(rowOf(address)).getAllByRole('cell')[3].firstChild
    expect(pill(TRON)).toHaveClass('case-band', 'high')
    expect(pill(SHARED)).toHaveClass('case-band', 'moderate')
    expect(pill(ETH)).toHaveClass('case-band', 'low')
    expect(pill(ETH2)).toHaveClass('case-band', 'none')

    // A literal path here would be rewritten by Vite into an asset URL.
    const sheet = '../styles.css'
    const css = readFileSync(new URL(sheet, import.meta.url), 'utf8')
    /** The declarations of the one-line rule whose selector list includes `selector`. */
    const rule = (selector) => {
      const found = css.split('\n').map((line) => /^([^{/@][^{]*)\{([^}]*)\}/.exec(line))
        .find((m) => m?.[1].split(/,(?![^(]*\))/).map((x) => x.trim()).includes(selector))
      return Object.fromEntries((found?.[2] ?? '').split(';').map((d) => d.split(/:(.*)/s).map((x) => x?.trim())).filter(([k]) => k))
    }
    const high = rule('.case-band.high')
    const faint = rule('.case-band:is(.moderate, .low, .very-low)')
    const none = rule('.case-band.none')
    expect(high).toMatchObject({ background: 'var(--panel-2)', color: 'var(--text)' })
    expect(faint.color).toBe('var(--text-2)')
    expect(faint.background).toMatch(/^color-mix\(in srgb, var\(--line\) \d+%, transparent\)$/)
    expect(none).toMatchObject({ background: 'none', color: 'var(--text-3)' })
    // The base pill draws no fill of its own, so no band falls back to High's.
    expect(rule('.case-band').background).toBeUndefined()
  })

  it('says when there are no cases yet', async () => {
    open({ cases: { count: 0, cases: [] } })
    expect(await screen.findByText(/No cases yet/)).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Filter cases' })).not.toBeInTheDocument()
  })

  it('says the cases cannot be reached, never that there are none, when /cases fails', async () => {
    open({ cases: { status: 500, body: { detail: 'down' } } })
    expect(await screen.findByText('Stored cases cannot be reached right now.')).toBeInTheDocument()
    expect(screen.queryByText(/No cases yet/)).not.toBeInTheDocument()
  })
})

describe('linked complaints', () => {
  const region = () => within(screen.getByRole('region', { name: 'Linked complaints' }))

  it('says none of the cases shares a wallet yet, asking about every case the browser may see', async () => {
    const fetch = open()
    expect(await region().findByText(/^None of your cases shares a wallet with another yet\./)).toBeInTheDocument()
    expect(fetch.mock.calls.map(([url]) => String(url)).filter((u) => u.includes('/cases/correlate'))).toEqual(['/api/cases/correlate'])
  })

  it('names each wallet two complaints meet at, and links the cases that reach it', async () => {
    const member = (case_id, reported_address) => ({ case_id, reported_address, direction: 'outgoing', asset: 'ETH', traced_at: '2026-11-04T10:00:00+00:00',
      depth: 2, value_in_native: 1.5, exchange: null, after_swap_to: null })
    const linked = {
      cases_examined: 4,
      cluster_count: 1,
      clusters: [{
        chain: 'ethereum', address: SHARED, inferred_exchange: `Bin${ZWSP}ance`, risk_category: 'frozen', reported_addresses: [ETH, ETH2],
        case_count: 4, max_value_in_native: 1.5, other_complaints: 1,
        // Newest first: an older trace of the same wallet is the same complaint.
        cases: [member('c-eth', ETH), member('c-eth-old', ETH), member('c-none', ETH2),
          { ...member(null, null), traced_at: null, value_in_native: null, hidden: true }],
      }],
    }
    open({ linked })
    const card = region()
    expect(await card.findByText(SHARED)).toBeInTheDocument()
    expect(card.getByText(/Ethereum · probable Binance deposit · frozen by issuer/)).toBeInTheDocument()
    expect(card.getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual(['/case/c-eth', '/case/c-none'])
    expect(card.getByText(/and 1 other complaint$/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Linked complaints' }).textContent).not.toContain(ZWSP)
    expect(card.queryByText(/None of your cases/)).not.toBeInTheDocument()
  })

  it('says the links cannot be checked, never that there are none, when /cases/correlate fails', async () => {
    open({ linked: { status: 429, body: { detail: 'too often' } } })
    expect(await region().findByText('Linked complaints cannot be checked right now.')).toBeInTheDocument()
    expect(region().queryByText(/None of your cases/)).not.toBeInTheDocument()
  })
})
