import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import FlowView from './FlowView'
import Watchlist from './Watchlist'
import VictimFlow from './case/VictimFlow'

// A name from outside this codebase is shown as the plain text it reads as:
// a zero-width space or a bidi override in a tag must not make "Binance"
// look like something the server classified differently, nor flip the text
// around it (r2-g2-frontend-intake-rendering-3-3).

beforeAll(() => {
  globalThis.ResizeObserver ??= class { observe() {} disconnect() {} unobserve() {} }
})
afterEach(() => vi.unstubAllGlobals())

const SEED = '0x' + 'a'.repeat(40)
const HOT = '0x' + 'b'.repeat(40)
const RISKY = '0x' + 'c'.repeat(40)

describe('names that hide characters', () => {
  it('captions the hop map with the plain name', () => {
    const data = {
      nodes: [
        { id: SEED, address: SEED, is_seed: true, depth: 0 },
        { id: HOT, address: HOT, depth: 1, exchange: 'Binance', label: 'Bin\u200Bance\u00AD 14' },
        { id: RISKY, address: RISKY, depth: 1, risk_category: 'scam', risk_entity: '\u202Etekcor\u202C scam' },
      ],
      edges: [
        { source: SEED, target: HOT, value_native: 5, timestamp: 1700000000 },
        { source: SEED, target: RISKY, value_native: 1, timestamp: 1700000001 },
      ],
    }
    const { container } = render(<FlowView data={data} tracePath={[SEED, HOT]} unit="ETH" />)
    expect(screen.getByText('Binance 14')).toBeInTheDocument()
    expect(screen.getByText('tekcor scam')).toBeInTheDocument()
    expect(container.textContent).not.toMatch(/[\u200B\u00AD\u202A-\u202E\u2066-\u2069]/)
  })

  it('names an alert counterparty without its hidden characters', async () => {
    const alerts = [{ alert_id: 'a1', kind: 'exchange', value: 1, asset: 'ETH', counterparty: HOT,
      counterparty_label: 'Bin\u2060ance\u2066 Hot\u2069', tx_time: 1700000000, tx_url: '', tx_hash: '0x1', read: false }]
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      const path = String(url).replace(/^\/api/, '').split('?')[0]
      const body = path === '/watches'
        ? { count: 1, running: true, watches: [{ watch_id: 'w1', address: SEED, chain: 'ethereum', asset: 'ETH', note: '', last_checked_at: null, unread_alerts: 1 }] }
        : { count: alerts.length, alerts }
      return new Response(JSON.stringify(body), { status: 200 })
    }))
    render(<MemoryRouter><Watchlist /></MemoryRouter>)
    expect(await screen.findByText('Binance Hot')).toBeInTheDocument()
  })

  it('captions the victim-flow Sankey and its cards with the plain names', () => {
    const victim_flow = {
      status: 'estimated',
      nodes: [
        { address: SEED, role: 'seed', victim_in: 6, left: 0, basis: 'seed_outflow' },
        { address: RISKY, role: 'wallet', victim_in: 1, left: 1, basis: 'traced_only' },
        { address: HOT, role: 'exchange', victim_in: 5, left: 0, basis: null },
      ],
      links: [{ source: SEED, target: HOT, victim: 5, gross: 5, style: 'solid' }, { source: SEED, target: RISKY, victim: 1, gross: 1, style: 'solid' }],
      buckets: [{ kind: 'exchange', amount: 5, share: 5 / 6, addresses: [HOT] }, { kind: 'held', amount: 1, share: 1 / 6, addresses: [RISKY] }],
      totals: { denominator: 6 }, lead: { path: [SEED, HOT], reached: 5 },
      passed_through: [{ address: RISKY, category: 'frozen', victim_in: 1 }],
      notes: ['A display\u200B only.'], stops: [{ kind: 'fanout_limit', amount: 5, note: 'Only the 10 largest destinations were followed at 0xcccc\u202E…cccc.', addresses: [HOT] }],
    }
    const result = {
      address: SEED, max_depth: 2, victim_flow, exchange: 'Bin\u200Bance', exchange_label: 'Bin\u200Bance\u00AD 14', exchange_address: HOT,
      confidence_detail: { band: 'high' },
      graph: { nodes: [{ address: SEED }, { address: HOT, exchange: 'Binance', label: 'Bin\u200Bance\u00AD 14' }, { address: RISKY, risk_category: 'frozen' }], edges: [] },
      risk_matches: [{ address: RISKY, category: 'frozen', issuer: 'Te\u200Dther' }],
    }
    const { container } = render(<VictimFlow result={result} unit="ETH" onLetters={() => {}} onWatch={() => {}} onDeeper={() => {}} />)
    expect(screen.getByText('Binance 14 · 5')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Draft letter to Binance' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Held at a wallet Tether froze' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Ask Tether' })).toHaveLength(1)
    // The flow's own sentences keep their punctuation, and lose what hides in an address they quote.
    expect(screen.getByText('Only the 10 largest destinations were followed at 0xcccc…cccc.')).toBeInTheDocument()
    expect(screen.getByText('A display only.')).toBeInTheDocument()
    expect(container.textContent).not.toMatch(/[\u200B-\u200D\u00AD\u202A-\u202E\u2066-\u2069]/)
  })
})
