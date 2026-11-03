import { render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it } from 'vitest'
import FlowView from './FlowView'

// jsdom has no ResizeObserver; the hop map only uses it to track its width.
beforeAll(() => {
  globalThis.ResizeObserver ??= class { observe() {} disconnect() {} unobserve() {} }
})

const SEED = '0x' + 'a'.repeat(40)
const DEPOSIT = '0x' + 'b'.repeat(40)

const data = {
  nodes: [
    { id: SEED, address: SEED, is_seed: true, depth: 0 },
    { id: DEPOSIT, address: DEPOSIT, depth: 1, risk_category: 'gambling', risk_entity: 'Stake.com', total_in_native: 120 },
  ],
  edges: [{ source: SEED, target: DEPOSIT, value_native: 120, timestamp: 1700000000 }],
}

describe('gambling platform wallets on the hop map', () => {
  it('names the platform and gives gambling its own legend entry, not the sanctions one', () => {
    const { container } = render(<FlowView data={data} tracePath={[SEED, DEPOSIT]} unit="USDT" />)
    expect(screen.getByText('Gambling platform wallet')).toBeInTheDocument()
    expect(screen.getByText('Stake.com')).toBeInTheDocument()
    const node = container.querySelector('.flow-node.role-gambling')
    expect(node).not.toBeNull()
    // The dot is the circle with vector-effect (the other two are the halo and a transparent hit area).
    expect(node.querySelector('circle[vector-effect]:not(.halo)').getAttribute('fill')).toBe('var(--purple)')
    expect(node.querySelector('circle.halo').style.stroke).toBe('var(--purple)')
  })
})
