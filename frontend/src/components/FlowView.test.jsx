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
    expect(node.querySelector('circle[vector-effect]:not(.halo)').getAttribute('fill')).toBe('var(--text-2)')
    expect(node.querySelector('circle.halo').style.stroke).toBe('var(--text-2)')
  })
})

const MID = '0x' + 'c'.repeat(40)
const SIDE = '0x' + 'd'.repeat(40)
// The route runs through a peel chain (pattern_detection adds PEEL_CHAIN to
// consecutive path edges), and one transfer off the route fired a pattern too.
const peel = {
  nodes: [
    { id: SEED, address: SEED, is_seed: true, depth: 0 },
    { id: MID, address: MID, depth: 1, flags: ['peel_chain'], total_in_native: 100 },
    { id: DEPOSIT, address: DEPOSIT, depth: 2, exchange: 'Binance', label: 'Binance 14', total_in_native: 90 },
    { id: SIDE, address: SIDE, depth: 2, total_in_native: 10 },
  ],
  edges: [
    { source: SEED, target: MID, value_native: 100, flags: ['peel_chain'] },
    { source: MID, target: DEPOSIT, value_native: 90, flags: ['peel_chain'] },
    { source: MID, target: SIDE, value_native: 10, flags: ['amount_split'] },
  ],
}
const route = [{ address: SEED }, { address: MID }, { address: DEPOSIT }]

describe('the traced funds on the hop map', () => {
  it('stay one solid line where a pattern fired on them: dashed means an inference', () => {
    const { container } = render(<FlowView data={peel} tracePath={route} unit="ETH" />)
    expect(container.querySelectorAll('.flow-link.on-path')).toHaveLength(2)
    expect(container.querySelectorAll('.flow-link.on-path.flagged')).toHaveLength(0)
    expect(container.querySelectorAll('.flow-link.flagged')).toHaveLength(1)
  })

  it('are green, the colour of money reaching an exchange; red is for risk', () => {
    const { container } = render(<FlowView data={peel} tracePath={route} unit="ETH" />)
    expect(container.querySelector('#arrow-path path').style.fill).toBe('var(--go)')
  })
})

describe('the hop map key', () => {
  it('draws each role the way the map does, so no two entries look alike', () => {
    const { container } = render(<FlowView data={peel} tracePath={route} unit="ETH" />)
    const entries = [...container.querySelectorAll('.flow-legend > span')]
    expect(entries.length).toBeGreaterThanOrEqual(8)
    // What an officer sees: the swatch's drawing, without its class names.
    const looks = entries.map((e) => e.querySelector('svg, i').outerHTML.replace(/ class="[^"]*"/g, ''))
    expect(new Set(looks).size).toBe(looks.length)
    for (const role of ['inferred', 'flagged']) {
      const dot = container.querySelector(`.flow-legend .role-${role} .dot`)
      expect(Number(dot.getAttribute('fill-opacity'))).toBeLessThan(1)
      expect(dot.getAttribute('stroke-dasharray')).toBeTruthy()
    }
    expect(container.querySelector('.flow-legend .role-gambling .halo').getAttribute('stroke-dasharray')).toBeTruthy()
  })
})
