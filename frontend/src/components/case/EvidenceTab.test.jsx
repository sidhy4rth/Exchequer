import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import TraceView from '../../routes/TraceView'
import { chainRows } from './EvidenceTab'
import recordings from '../../../../backend/data/recorded_demos.json'

// The Evidence tab (pack 2-glass-07): the route's transfers by full hash,
// a second provider's word on each, the freeze records, what the trace read
// and the signed report. Demo 11: Tron USDT, traced from the address, 2 hops
// to Binance-Hot 7; its last hop keeps 20 of 27 hashes in trace_path.
const demo = recordings.find((r) => r.demo === 11)
const PATH = demo.result.trace_path.map((s) => s.address)
const ON_PATH = demo.result.transfers.filter((t) => PATH.some((a, i) => a === t.from && PATH[i + 1] === t.to))
const LISTED = new Set(demo.result.trace_path.flatMap((s) => s.tx_hashes ?? []))
// The route's first four transfers in time: hop 1, hop 2, hop 1, hop 2.
const [HOP1, HOP2, HOP1B, HOP2B] = [...ON_PATH].sort((a, b) => a.timestamp - b.timestamp).map((t) => t.hash)

/** fetch answering "METHOD /path"; anything else is the 404 a server without it gives. */
function serve(routes) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const path = String(url).replace(/^\/api/, '').split('?')[0]
    calls.push({ method, path, url: String(url) })
    const hit = routes[`${method} ${path}`]
    if (!hit) return new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 })
    const { status = 200, body } = hit
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status })
  }))
  return calls
}

async function openEvidence({ routes = {}, caseId = null, ...overrides } = {}) {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  const result = { ...demo.result, case_id: caseId, created_at: demo.recorded_at, recorded_demo: caseId ? undefined : 11, ...overrides }
  const calls = serve({ 'GET /demos/recorded/11': { body: result }, [`GET /trace/${caseId}`]: { body: result }, ...routes })
  render(
    <MemoryRouter initialEntries={[`${caseId ? `/case/${caseId}` : '/demo/11'}?tab=evidence`]}>
      <Routes>
        <Route path="/demo/:demoNo" element={<TraceView />} />
        <Route path="/case/:caseId" element={<TraceView />} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByRole('heading', { name: 'The chain, transfer by transfer' })
  return calls
}

const table = () => screen.getByRole('table', { name: 'The chain, transfer by transfer' })
const bodyRows = () => within(table()).getAllByRole('row').slice(1)
const rowWith = (hash) => bodyRows().find((r) => r.textContent.includes(hash))
const NONE_YET = { case_id: null, checked_at: null, transfers: [] }
/** Wait until the tab has asked for the recheck and had time to act on the answer. */
async function recheckAnswered(calls, id = 'demo-11') {
  await waitFor(() => expect(calls.some((c) => c.method === 'GET' && c.path === `/trace/${id}/recheck`)).toBe(true))
  await act(() => new Promise((resolve) => { setTimeout(resolve, 50) }))
}

afterEach(() => {
  delete URL.createObjectURL
  delete URL.revokeObjectURL
})

describe('the chain, transfer by transfer', () => {
  it("lists the route's transfers from the case's transfers, not the 20 hashes a hop keeps", async () => {
    const user = userEvent.setup()
    await openEvidence()
    expect(ON_PATH).toHaveLength(29)
    expect(bodyRows()).toHaveLength(12)
    await user.click(screen.getByRole('button', { name: 'Show all 29 transfers' }))
    expect(bodyRows()).toHaveLength(29)
    const unlisted = ON_PATH.find((t) => !LISTED.has(t.hash))
    expect(unlisted).toBeDefined()
    expect(rowWith(unlisted.hash)).toBeDefined()
  })

  it('gives each row its step, IST time, from and to, amount, full hash and explorer link', async () => {
    await openEvidence()
    const heads = within(table()).getAllByRole('columnheader').map((h) => h.textContent)
    expect(heads).toEqual(['Step', 'IST', 'From → to', 'Amount', 'Transaction', 'Explorer'])
    const [first, second] = bodyRows()
    expect(first).toHaveTextContent('Hop 1')
    expect(first).toHaveTextContent('19 Dec 2024 14:36')
    expect(first).toHaveTextContent(/TUVN…i3ts\s*→\s*to\s*TXgo…BBVU/)
    expect(first).toHaveTextContent('340 USDT')
    expect(within(first).getByRole('button', { name: new RegExp(HOP1) })).toBeInTheDocument()
    expect(within(first).getByRole('link')).toHaveAttribute('href', `https://tronscan.org/#/transaction/${HOP1}`)
    expect(second).toHaveTextContent('Hop 2')
    expect(second).toHaveTextContent('Binance-Hot 7')
    expect(second).toHaveTextContent(HOP2)
  })

  it('scrolls sideways in a region of its own, which a keyboard can reach, rather than being cut off', async () => {
    await openEvidence()
    const region = screen.getByRole('region', { name: 'Route transfers' })
    expect(region).toHaveAttribute('tabindex', '0')
    expect(region).toContainElement(table())
  })

  it('copies a full hash when pressed', async () => {
    const user = userEvent.setup()
    await openEvidence()
    await user.click(within(rowWith(HOP1)).getByRole('button', { name: new RegExp(HOP1) }))
    expect(await navigator.clipboard.readText()).toBe(HOP1)
  })

  it('drops the "copied" mark\'s timer when the tab goes away, so it never fires on a closed page', async () => {
    const user = userEvent.setup()
    await openEvidence()
    const set = vi.spyOn(globalThis, 'setTimeout')
    const clear = vi.spyOn(globalThis, 'clearTimeout')
    try {
      await user.click(within(rowWith(HOP1)).getByRole('button', { name: new RegExp(HOP1) }))
      await within(rowWith(HOP1)).findByText('copied')
      const marks = set.mock.calls.flatMap(([, ms], i) => (ms === 1100 ? [set.mock.results[i].value] : []))
      expect(marks).toHaveLength(1)
      cleanup()
      expect(clear).toHaveBeenCalledWith(marks[0])
    } finally {
      set.mockRestore()
      clear.mockRestore()
    }
  })

  it("starts from the victim's payments, and keeps back a hash the reader may not see", () => {
    const victim = 'T' + '5'.repeat(33)
    const rows = chainRows({
      ...demo.result,
      intake: { mode: 'payment', payments: [
        { tx_hash: 'a1'.repeat(32), from: victim, to: demo.result.address, amount: 9890, timestamp: 1_734_351_180 },
        { tx_hash: null, from: null, to: demo.result.address, amount: 5, timestamp: null },
      ] },
    })
    expect(rows.slice(0, 2).map((r) => [r.hop, r.hash, r.amount])).toEqual([[0, 'a1'.repeat(32), 9890], [0, null, 5]])
    expect(rows.slice(2).map((r) => r.hop)).toEqual([1, 2, 1, 2, ...Array(25).fill(2)])
  })

  it('reads a reverse trace along its path, which runs the way the money moved', () => {
    // Demo 5: traced back from the reported address to Binance 17; trace_path
    // runs from the exchange down to the reported address, as the money did.
    const five = recordings.find((r) => r.demo === 5).result
    expect(five.direction).toBe('incoming')
    expect(chainRows(five).map((r) => [r.hop, r.hash])).toEqual([
      [1, '0x3713027e9f2768b616f4b327b88ffe5214ae866ab292823979446797535131a9'],
      [1, '0x9058d284940734f8096ff7651556c9a55f469bc7e35ab523da6b1453d259d19c'],
    ])
  })

  it('follows a swap to the exchange its follow-on reached, in each leg\'s own asset', () => {
    const [seed, sender, router, mid, binance] = ['TS', 'TW', 'TR', 'TM', 'TB']
    const rows = chainRows({
      address: seed, asset: 'USDT', exchange: null, trace_path: [],
      transfers: [
        { hash: 'r1', from: seed, to: sender, value_native: 100, timestamp: 1 },
        { hash: 'sw', from: sender, to: router, value_native: 100, timestamp: 2 },
        { hash: 'no', from: seed, to: 'TX', value_native: 7, timestamp: 1 },
      ],
      follow_ons: [
        { asset: 'TRX', result: { exchange: null } },
        { asset: 'TRX', swap: { tx: 'sw', sender }, route: [{ address: seed }, { address: sender }], result: {
          exchange: 'Binance', trace_path: [{ address: sender }, { address: mid }, { address: binance }],
          transfers: [
            { hash: 'f2', from: mid, to: binance, value_native: 390, timestamp: 4 },
            { hash: 'f1', from: sender, to: mid, value_native: 400, timestamp: 3 },
          ],
        } },
      ],
    })
    expect(rows.map((r) => [r.step, r.hash, r.asset ?? null])).toEqual([
      ['Hop 1', 'r1', null], ['Swap', 'sw', null], ['Hop 2', 'f1', 'TRX'], ['Hop 3', 'f2', 'TRX'],
    ])
  })

  it("shows a follow-on's transfers in its asset, and never says the trace reached no exchange", async () => {
    const [a, b] = ['T' + '6'.repeat(33), 'T' + '7'.repeat(33)]
    await openEvidence({ exchange: null, trace_path: [], follow_ons: [{ asset: 'TRX', route: [], result: {
      exchange: 'Binance', graph: { nodes: [], edges: [] }, trace_path: [{ address: a }, { address: b }], transfers: [{ hash: 'f'.repeat(64), from: a, to: b, value_native: 400, timestamp: 1_734_351_180 }],
    } }] })
    expect(rowWith('f'.repeat(32))).toHaveTextContent('400 TRX')
    expect(screen.getByRole('tabpanel')).not.toHaveTextContent('reached no exchange')
  })

  it('shows a withheld payment as withheld, with no explorer link', async () => {
    await openEvidence({ intake: { mode: 'payment', payments: [{ tx_hash: null, from: null, amount: 5, timestamp: null }] }, reported_amount: 5 })
    const [first] = bodyRows()
    expect(first).toHaveTextContent('Payment')
    expect(first).toHaveTextContent('hash withheld')
    expect(within(first).queryByRole('link')).toBeNull()
  })
})

describe('the second provider', () => {
  it('hides its column and button where the server has no recheck (404), and says nothing', async () => {
    await recheckAnswered(await openEvidence())
    expect(within(table()).queryByRole('columnheader', { name: 'Second provider' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Re-read from a second provider/ })).toBeNull()
    expect(within(screen.getByRole('tabpanel')).queryByRole('alert')).toBeNull()
    expect(screen.getByRole('tabpanel')).not.toHaveTextContent(/not found|could not/i)
  })

  it('hides them on a 405 as well', async () => {
    await recheckAnswered(await openEvidence({ routes: { 'GET /trace/demo-11/recheck': { status: 405, body: { detail: 'Method Not Allowed' } } } }))
    expect(within(table()).queryByRole('columnheader', { name: 'Second provider' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Re-read from a second provider/ })).toBeNull()
    expect(screen.getByRole('tabpanel')).not.toHaveTextContent(/Method Not Allowed/)
  })

  it('says each row is not checked yet, then rereads on request', async () => {
    const user = userEvent.setup()
    const reread = {
      case_id: null, recorded_demo: 11, chain: 'tron', asset: 'USDT', provider: 'TronScan', checked_at: '2026-11-10T05:00:00+00:00',
      cited: 22, checked: 3, skipped: 0, counts: { matches: 1, differs: 1, not_found: 1, error: 0 }, saved: false,
      transfers: [
        { hash: HOP1, status: 'matches', differences: [], detail: null },
        { hash: HOP2, status: 'differs', differences: [{ field: 'amount', case: '1148.688', provider: '1148.7' }], detail: 'amount is 1148.7, the report says 1148.688' },
        { hash: HOP1B, status: 'not_found', differences: [], detail: 'the second provider does not have this transaction' },
      ],
    }
    const calls = await openEvidence({ routes: { 'GET /trace/demo-11/recheck': { body: NONE_YET }, 'POST /trace/demo-11/recheck': { body: reread } } })
    expect(await within(table()).findByRole('columnheader', { name: 'Second provider' })).toBeInTheDocument()
    expect(bodyRows().every((r) => r.textContent.includes('not checked yet'))).toBe(true)
    // Mounted empty before the reread, so a screen reader hears it fill.
    const status = within(table().closest('section')).getByRole('status')
    expect(status).toBeEmptyDOMElement()
    await user.click(screen.getByRole('button', { name: 'Re-read from a second provider' }))
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual(['/trace/demo-11/recheck'])
    await waitFor(() => expect(status).toHaveTextContent(/Re-read from TronScan/))
    expect(rowWith(HOP1)).toHaveTextContent('matches')
    expect(rowWith(HOP2)).toHaveTextContent('differs')
    expect(rowWith(HOP2)).toHaveTextContent('amount is 1148.7, the report says 1148.688')
    expect(rowWith(HOP1B)).toHaveTextContent('not found')
    expect(rowWith(HOP2B)).toHaveTextContent('not checked')
    expect(rowWith(HOP2B)).not.toHaveTextContent('not checked yet')
  })

  it("shows a stored case's last recheck as it opens", async () => {
    const kept = { case_id: 'case-1', provider: 'TronScan', checked_at: '2026-11-10T05:00:00+00:00', cited: 1, checked: 1, skipped: 0,
      counts: { matches: 1, differs: 0, not_found: 0, error: 0 }, transfers: [{ hash: HOP1, status: 'matches', differences: [], detail: null }] }
    const calls = await openEvidence({ caseId: 'case-1', routes: { 'GET /trace/case-1/recheck': { body: kept } } })
    await within(table()).findByRole('columnheader', { name: 'Second provider' })
    expect(rowWith(HOP1)).toHaveTextContent('matches')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('says why a recheck was refused, and keeps the column', async () => {
    const user = userEvent.setup()
    const refused = 'This connection has run 5 rechecks in the last hour. Try again in 12 min.'
    await openEvidence({ routes: {
      'GET /trace/demo-11/recheck': { body: NONE_YET },
      'POST /trace/demo-11/recheck': { status: 429, body: { detail: refused } },
    } })
    await user.click(await screen.findByRole('button', { name: 'Re-read from a second provider' }))
    expect(await within(screen.getByRole('tabpanel')).findByRole('alert')).toHaveTextContent(refused)
    expect(within(table()).getByRole('columnheader', { name: 'Second provider' })).toBeInTheDocument()
  })
})

describe('the freeze records', () => {
  const card = () => screen.getByRole('heading', { name: 'Freeze records · Tether' }).closest('article')

  it("lists each frozen wallet with the freeze's day and event transaction", async () => {
    await openEvidence()
    expect(card()).toHaveTextContent('Reported wallet TUVN…i3ts')
    expect(card()).toHaveTextContent('Hop 1 wallet TZ7L…9cNz')
    expect(card()).toHaveTextContent(/11 Sept? 2026/)
    expect(card()).toHaveTextContent('a7a163d21039fe8c378aaad209423a0825a4c66c65486f0d7a57609dd3237f2c')
    expect(card()).toHaveTextContent('98463d6ac7907828e56d49ece8ea4f34a362b8eeaa9fccaacd39f4c21a49354f')
  })

  it('prefers the day and event the case records', async () => {
    const [seed, hop] = demo.result.risk_matches
    await openEvidence({ risk_matches: [{ ...seed, frozen_on: '2026-09-10', event_tx: 'f'.repeat(64) }, { ...hop, frozen_on: null, event_tx: null }] })
    expect(card()).toHaveTextContent(/10 Sept? 2026/)
    expect(card()).toHaveTextContent('f'.repeat(64))
    expect(card()).toHaveTextContent('no event transaction on file')
  })

  it('is not shown when nothing was frozen', async () => {
    await openEvidence({ risk_matches: [] })
    expect(screen.queryByRole('heading', { name: /Freeze records/ })).toBeNull()
  })
})

describe('what the trace read', () => {
  it('counts the responses, providers and requests, with the read window and the manifest', async () => {
    await openEvidence()
    const card = screen.getByRole('heading', { name: 'What the trace read' }).closest('article')
    expect(card).toHaveTextContent('24 responses hashed')
    expect(card).toHaveTextContent('2 providers')
    expect(card).toHaveTextContent('1 request')
    expect(card).toHaveTextContent('TronGrid, TronScan · read 9 Nov 2026 21:07 to 21:07 IST')
    expect(card).toHaveTextContent(demo.result.evidence.manifest_sha256)
  })
})

describe('the signed report', () => {
  const card = () => screen.getByRole('heading', { name: 'Signed report' }).closest('article')

  it('states the limits the report states', async () => {
    const user = userEvent.setup()
    await openEvidence()
    const caveats = demo.result.confidence_detail.caveats
    await user.click(within(card()).getByText(`Limits stated in the report · ${caveats.length}`))
    for (const c of caveats) expect(within(card()).getByText(c)).toBeVisible()
  })

  it('has no files for a recorded example, and says how to get them', async () => {
    await openEvidence()
    expect(within(card()).queryByRole('button', { name: /PDF/ })).toBeNull()
    expect(card()).toHaveTextContent(/Trace live/)
  })

  it('downloads the PDF, the text and the graph file of a stored case', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:case')
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const user = userEvent.setup()
    const calls = await openEvidence({ caseId: 'case-1', routes: {
      'GET /trace/case-1/report': { body: 'signed report' },
      'GET /trace/case-1/graph': { body: '<graphml/>' },
    } })
    for (const name of ['PDF', 'Text', 'Graph file']) await user.click(within(card()).getByRole('button', { name: new RegExp(`^${name}`) }))
    const asked = calls.filter((c) => /\/(report|graph)$/.test(c.path)).map((c) => c.url.replace(/^\/api/, ''))
    expect(asked).toEqual(['/trace/case-1/report?format=pdf', '/trace/case-1/report?format=text', '/trace/case-1/graph?format=graphml'])
    expect(URL.createObjectURL).toHaveBeenCalledTimes(3)
  })
})

describe('scope and evidence', () => {
  it('stays in the tab, with the listed-of-total line', async () => {
    await openEvidence({ transfers_total: 5000, transfers_omitted: 5000 - demo.result.transfers.length })
    expect(within(screen.getByRole('tabpanel')).getByText('Scope and evidence')).toBeVisible()
    expect(screen.getByText(new RegExp(`5000 individual transactions \\(${demo.result.transfers.length} listed\\)`))).toBeInTheDocument()
  })
})
