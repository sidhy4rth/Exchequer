import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import FlowView from './FlowView'
import Watchlist from './Watchlist'

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
})
