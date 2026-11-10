import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Present from './Present'
import recordings from '../../../backend/data/recorded_demos.json'
import { stubFetch } from '../test/setup'

const demo = recordings.find((r) => r.demo === 11)

function open(over) {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  return render(<Present result={{ ...demo.result, ...over }} unit="USDT" onClose={() => {}} />)
}

describe('Present mode, screen 1', () => {
  // Audit r2-g2-documented-claims-vs-code-7-2.
  it('does not say the funds reached the exchange as a measured amount when pro-rata was not estimated', () => {
    const { container } = open({ prorata: { status: 'unknown', reason: 'a wallet received too many transfers to read in full' } })
    const lede = container.querySelector('.pr-lede')
    expect(lede).not.toHaveTextContent('Funds from the reported wallet reached')
    expect(lede).toHaveTextContent('Funds moved from the reported wallet to')
    expect(lede).toHaveTextContent('amount not estimated')
  })

  it('states a capped figure as the victim\'s, never the wallet\'s whole outflow', () => {
    const { container } = open({ prorata: { ...demo.result.prorata, estimated: 100, seed_cap: { amount: 100, basis: 'reported_amount', applied: true } } })
    expect(container.querySelector('.pr-lede')).toHaveTextContent('About 100 of 100 USDT the victim reported paying likely reached')
    expect(container.querySelector('.pr-lede')).not.toHaveTextContent("other people's money")
  })

  // Audit r1-attribution-integrity-7: an address-only figure is everything the
  // reported wallet sent along the route, not the complainant's loss.
  it("says an address-only figure may include other people's money", () => {
    const { container } = open({})
    const lede = container.querySelector('.pr-lede')
    expect(lede).toHaveTextContent('About 635 of 635 USDT from the reported wallet likely reached')
    expect(lede).toHaveTextContent("may include other people's money, not only the complainant's")
  })

  it("words a payment trace's figure for the victim's payment, without that caveat", () => {
    const { container } = open({ intake: { mode: 'payment', payments: [] } })
    const lede = container.querySelector('.pr-lede')
    expect(lede).toHaveTextContent("About 635 of 635 USDT sent on after the victim's payment likely reached")
    expect(lede).not.toHaveTextContent("other people's money")
  })
})

describe('Present mode, the handoff screen', () => {
  // The letters left the Export menu for the case's Letters tab; the screen
  // that says to send the request must still offer them.
  it('offers the draft letter beside a labelled Export', async () => {
    stubFetch({ '/trace/c1/letters': { body: { letters: [{ to: 'exchange', title: 'Request to Binance' }] } } })
    open({ case_id: 'c1' })
    await userEvent.setup().keyboard('{ArrowRight}{ArrowRight}{ArrowRight}')
    expect(screen.getByText('Send the request to Binance.')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /Request to Binance/ })).toBeInTheDocument()
    const exportMenu = screen.getByRole('button', { name: 'Export' })
    expect(exportMenu).not.toHaveClass('icon-btn')
    expect(exportMenu.querySelector('.visually-hidden')).toBeNull()
  })
})

describe('Present mode, after a swap and on the route screen', () => {
  it('states the followed trace\'s confidence as the band word, with no decimal', () => {
    const { container } = open({
      exchange: null, exchange_address: null, exchange_label: null,
      followed_attribution: { exchange: 'Binance', exchange_label: 'Binance-Hot 7', exchange_address: 'T'.padEnd(34, '9'), asset: 'TRX', hop_count: 2, confidence: 0.49, attribution_inferred: false },
    })
    const lede = container.querySelector('.pr-lede')
    expect(lede).toHaveTextContent('2 hops after the swap, low confidence within that trace.')
    expect(lede.textContent).not.toMatch(/\d\.\d/)
  })

  it('says which view of the route is showing, to a screen reader too', async () => {
    const user = userEvent.setup()
    open()
    await user.keyboard('{ArrowRight}')
    const hop = screen.getByRole('button', { name: 'By hop' })
    const bubbles = screen.getByRole('button', { name: 'Bubbles' })
    expect(hop).toHaveAttribute('aria-pressed', 'true')
    expect(bubbles).toHaveAttribute('aria-pressed', 'false')
    await user.click(bubbles)
    expect(bubbles).toHaveAttribute('aria-pressed', 'true')
  })
})
