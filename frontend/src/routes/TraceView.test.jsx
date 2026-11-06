import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TraceView from './TraceView'
import recordings from '../../../backend/data/recorded_demos.json'
import { stubFetch } from '../test/setup'

// Demo 11: Tron USDT, frozen by Tether, Binance-Hot 7 at score 0.80 (high),
// with one amount-split pattern. Traced from the address alone.
const demo = recordings.find((r) => r.demo === 11)

async function openDemo11(overrides = {}) {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  stubFetch({ '/demos/recorded/11': { body: { ...demo.result, case_id: null, created_at: demo.recorded_at, recorded_demo: 11, ...overrides } } })
  render(
    <MemoryRouter initialEntries={['/demo/11']}>
      <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
    </MemoryRouter>,
  )
  await screen.findByText(/Verified example 11/)
}

describe('how sure the case is (R10)', () => {
  it('leads with the band, and says it is not a probability', async () => {
    await openDemo11()
    expect(demo.result.confidence).toBeCloseTo(0.8)
    const big = document.querySelector('.sure .big')
    expect(big).toHaveTextContent('High')
    expect(big.textContent).not.toMatch(/\d/)
    expect(screen.getByText('a rule of three inputs, not a probability')).toBeInTheDocument()
  })

  it('keeps the exact score in the working, beside the band rule', async () => {
    await openDemo11()
    const working = document.querySelector('.score-working')
    expect(working).toHaveTextContent('Score 0.80')
    expect(working).toHaveTextContent('read the band, not the decimal')
  })

  it('folds patterns into hints with their measured hit rates', async () => {
    await openDemo11()
    expect(screen.getByText('Hints · 1')).toBeInTheDocument()
    expect(screen.queryByText(/^Patterns ·/)).not.toBeInTheDocument()
    expect(screen.getByText(/6 of 32 documented fraud wallets and 5 of 47 ordinary ones/)).toBeInTheDocument()
    expect(screen.queryByText(/strength/)).not.toBeInTheDocument()
    expect(document.querySelector('details.card.sec:not([open]) .hint-rate')).not.toBeNull()
  })

  it('marks an address-only trace as exploratory', async () => {
    await openDemo11()
    expect(screen.getByText(/Exploratory · traced from the address/)).toBeInTheDocument()
  })
})

describe('a payment case read by someone other than the officer who traced it', () => {
  it('says the NCRP number is on file without showing it, and survives a withheld payer', async () => {
    await openDemo11({
      intake: { mode: 'payment', ncrp_ack: null, payments: [{ tx_hash: '0x' + 'c'.repeat(64), from: null, amount: 12 }] },
      reported_amount: 12,
      redacted: ['intake.ncrp_ack', 'intake.payments[].from'],
    })
    expect(screen.getByText(/NCRP on file \(visible to the officer who traced it\)/)).toBeInTheDocument()
  })
})

describe('three tracing rules side by side (R4)', () => {
  async function openWith(methods) {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    stubFetch({ '/demos/recorded/11': { body: { ...demo.result, tracing_methods: methods, case_id: null, created_at: demo.recorded_at, recorded_demo: 11 } } })
    render(
      <MemoryRouter initialEntries={['/demo/11']}>
        <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
      </MemoryRouter>,
    )
    await screen.findByText(/Verified example 11/)
  }

  it('shows the range and the figure a letter states', async () => {
    await openWith({ figures: { fifo: 40, prorata: 20, libr: 0 }, range: { low: 0, high: 40 }, conservative: 0, conservative_method: 'libr' })
    const line = document.querySelector('.method-range')
    expect(line).toHaveTextContent('By tracing rule')
    expect(line).toHaveTextContent('FIFO 40')
    expect(line).toHaveTextContent('LIBR 0')
    expect(line).toHaveTextContent('a letter states the smallest')
  })

  it('says so when the rules agree', async () => {
    await openWith({ figures: { fifo: 5, prorata: 5, libr: 5 }, range: { low: 5, high: 5 }, conservative: 5, conservative_method: 'fifo' })
    expect(document.querySelector('.method-range')).toHaveTextContent('All 3 tracing rules agree')
  })

  it('shows nothing when the trace ran pro-rata alone', async () => {
    await openWith(null)
    expect(document.querySelector('.method-range')).toBeNull()
  })
})

describe('what the walk did not follow (R5)', () => {
  it('states the untraced value under scope and evidence', async () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    const untraced = [{ address: demo.result.address, counterparties: 2, value_native: 6, share_of_outflow: 0.13, rule: 'top_n' }]
    stubFetch({ '/demos/recorded/11': { body: { ...demo.result, untraced, case_id: null, created_at: demo.recorded_at, recorded_demo: 11 } } })
    render(
      <MemoryRouter initialEntries={['/demo/11']}>
        <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
      </MemoryRouter>,
    )
    await screen.findByText(/Verified example 11/)
    const row = document.querySelector('.exclusion.untraced')
    expect(row).toHaveTextContent('sent on but not followed')
    expect(row).toHaveTextContent('2 smaller destinations of 1 address')
    expect(row).toHaveTextContent('the ten largest')
  })
})

describe('what the amount is, and when it was not measured', () => {
  async function openWithResult(over) {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    stubFetch({ '/demos/recorded/11': { body: { ...demo.result, ...over, case_id: null, created_at: demo.recorded_at, recorded_demo: 11 } } })
    render(
      <MemoryRouter initialEntries={['/demo/11']}>
        <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
      </MemoryRouter>,
    )
    await screen.findByText(/Verified example 11/)
  }

  // Audit r2-g2-documented-claims-vs-code-7-2.
  it('shows "not estimated" with the reason', async () => {
    await openWithResult({ prorata: { status: 'unknown', reason: 'TXgo received too many transfers in the window to read in full' } })
    const chip = document.querySelector('.prorata-unknown')
    expect(chip).toHaveTextContent('Pro-rata: not estimated')
    expect(chip).toHaveTextContent('too many transfers')
  })

  it('renders the confidence caveats', async () => {
    await openWithResult({})
    const limits = [...document.querySelectorAll('.limitation')].map((p) => p.textContent)
    expect(limits).toEqual(demo.result.confidence_detail.caveats)
  })

  // Audit r1-attribution-integrity-7.
  it('says an address-only figure can include other people\'s money', async () => {
    await openWithResult({})
    const basis = document.querySelector('.finding-bar .basis')
    expect(basis).toHaveTextContent('this wallet sent on this route likely arrived')
    expect(basis).toHaveTextContent("may include other people's money")
  })

  it('a payment trace never shows more than the victim reported', async () => {
    await openWithResult({
      intake: { mode: 'payment', payments: [{ tx_hash: '0xaa', amount: 100 }], ncrp_ack: null },
      reported_amount: 100,
      prorata: { ...demo.result.prorata, estimated: 100, seed_cap: { amount: 100, basis: 'reported_amount', applied: true } },
    })
    const basis = document.querySelector('.finding-bar .basis')
    expect(basis).toHaveTextContent('≈ 100 of 100 USDT the victim reported paying likely arrived')
    expect(basis).not.toHaveTextContent('of 635')
  })
})

describe('a government seizure order (audit r1-labels-data-12)', () => {
  const seized = {
    address: 'TAR2KrCfTST5BQXs7D7N4HYHx6FBt4bzLh', category: 'seized', entity: 'NBCTF order FO 05/24',
    label: 'NBCTF order FO 05/24', source: 'Israel NBCTF seizure or forfeiture order FO 05/24 (via OpenSanctions)',
    depth: 1, value_received_native: 10, is_terminal: false,
  }

  async function openWithSeized() {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    stubFetch({ '/demos/recorded/11': { body: { ...demo.result, risk_matches: [seized], case_id: null, created_at: demo.recorded_at, recorded_demo: 11 } } })
    render(
      <MemoryRouter initialEntries={['/demo/11']}>
        <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
      </MemoryRouter>,
    )
    await screen.findByText(/Verified example 11/)
  }

  it('is labelled a seizure order, never a sanctioned entity', async () => {
    await openWithSeized()
    const alert = document.querySelector('.alert')
    expect(alert).toHaveTextContent('Seizure order:')
    expect(alert).not.toHaveTextContent('Sanctioned')
  })

  it('is a seizure order in present mode too, not the "Sanctioned" fallback', async () => {
    await openWithSeized()
    screen.getByRole('button', { name: /Present/ }).click()
    const alert = await screen.findByText(/Seizure order · NBCTF order FO 05\/24/)
    expect(alert.closest('.pr-alert')).not.toHaveTextContent('Sanctioned')
  })
})

describe("the victim's payments on the case page (5-3, 5-2, 5-5, 5-1)", () => {
  const H1 = '0x' + 'a1'.repeat(32)
  const H2 = '0x' + 'b2'.repeat(32)
  const SENDER = '0x' + '5'.repeat(40)
  const pay = (over) => ({ chain: 'ethereum', asset: 'ETH', to: demo.result.address, block: 1, found_by: 'victim', from: SENDER, ...over })

  async function openPaymentCase(extra = {}) {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    const intake = {
      mode: 'payment', ncrp_ack: '31911250012345',
      payments: [
        pay({ tx_hash: H1, amount: 3999, timestamp: 1_700_000_000, leg: 0, payer_label: 'Binance 14', payer_is_victim: false }),
        pay({ tx_hash: H1, amount: 1, timestamp: 1_700_000_000, leg: 1, payer_is_victim: false }),
        pay({ tx_hash: H2, amount: 5, timestamp: 1_700_086_400, payer_is_victim: true }),
      ],
    }
    stubFetch({ '/demos/recorded/11': { body: { ...demo.result, intake, reported_amount: 4005, explorer_url: 'https://etherscan.io', chain: 'ethereum', case_id: null, created_at: demo.recorded_at, recorded_demo: 11, ...extra } } })
    render(
      <MemoryRouter initialEntries={['/demo/11']}>
        <Routes><Route path="/demo/:demoNo" element={<TraceView />} /></Routes>
      </MemoryRouter>,
    )
    await screen.findByText(/Verified example 11/)
  }

  it('counts payments by hash, not by transfer, and marks the NCRP number as entered', async () => {
    await openPaymentCase()
    const line = document.querySelector('.finding-bar .intake')
    expect(line).toHaveTextContent('in 2 payments (3 transfers)')
    expect(line).toHaveTextContent('NCRP 31911250012345 as entered')
  })

  it('lists every payment with its sender, label, victim check and explorer link', async () => {
    await openPaymentCase()
    const card = document.querySelector('.payments-card')
    expect(card).toHaveTextContent("Victim's payments · 2")
    expect(card).toHaveTextContent('confirm each against the complaint')
    const rows = card.querySelectorAll('.row')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('Binance 14')
    expect(rows[0]).toHaveTextContent("not the victim's wallet")
    expect(rows[0]).toHaveTextContent('transfer 1 of this hash')
    expect(rows[2]).toHaveTextContent("the victim's wallet")
    expect(rows[2].querySelector('a')).toHaveAttribute('href', `https://etherscan.io/tx/${H2}`)
  })

  it("greys statement rows from before the victim's first payment", async () => {
    const row = (over) => ({ tx: over.tx, counterparty: SENDER, amount: 1, time: 1_600_000_000, ...over })
    await openPaymentCase({ statement: { credits: [row({ tx: 'a', before_window: true })], debits: [row({ tx: 'b', before_window: false })], rows_per_side: 20, lookalikes: 0 } })
    const marked = document.querySelectorAll('.row.before-window')
    expect(marked).toHaveLength(1)
    expect(marked[0]).toHaveTextContent('before the payment')
  })
})
