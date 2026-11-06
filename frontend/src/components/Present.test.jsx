import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import Present from './Present'
import recordings from '../../../backend/data/recorded_demos.json'

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
  })
})
