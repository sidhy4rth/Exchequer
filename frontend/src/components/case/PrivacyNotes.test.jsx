import { render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it } from 'vitest'
import PrivacyNotes from './PrivacyNotes'
import FlowView from '../FlowView'
import { flagCounts, isConfirmedRisk, roleOf } from '../mapRoles'

// jsdom has no ResizeObserver; the hop map only uses it to track its width.
beforeAll(() => {
  globalThis.ResizeObserver ??= class { observe() {} disconnect() {} unobserve() {} }
})

// A privacy protocol's contract (flag EXCHEQUER_PRIVACY_CATEGORY, #189): a
// note on the trace, never a risk hit. Shapes as backend/app/pipeline.py
// writes them; the address is Railgun's Ethereum Relay Adapt from
// backend/data/privacy_protocols.json.
const SEED = '0x' + 'a'.repeat(40)
const RAILGUN = '0x22af4edbea3de885dda8f0a0653e6209e44e5b84'
const NOTE = `Privacy protocol: ${RAILGUN} is Railgun: Relay Adapt contract (Initial deployment) (Railgun), per Railgun shared-models. It received 9.0000 ETH within this trace, 2 hops from the reported address. A privacy protocol: funds passing through lose their visible link, so what leaves it is not shown on chain to be the same money. The trace did not stop here. This is not an accusation: no sanctions list or enforcement action names this protocol, and using it is not a finding against anyone.`
const result = {
  risk_matches: [],
  privacy_matches: [{ address: RAILGUN, category: 'privacy', entity: 'Railgun', label: 'Railgun: Relay Adapt contract',
    source: 'Railgun shared-models', depth: 2, value_received_native: 9, is_terminal: false, origin: 'privacy_protocols.json' }],
  privacy_notes: [NOTE],
}
const node = { id: RAILGUN, address: RAILGUN, depth: 2, privacy_entity: 'Railgun', risk_category: null, flags: [], total_in_native: 9 }

describe('the privacy note on the case', () => {
  it('says what a privacy protocol means and that it is not an accusation', () => {
    const { container } = render(<PrivacyNotes result={result} unit="ETH" />)
    expect(screen.getByText(/A privacy protocol on the route · a note, not an accusation/)).toBeInTheDocument()
    expect(screen.getByText(/lose their visible link/, { selector: '.lede' })).toBeInTheDocument()
    // Drawn for every stored case, so it claims nothing a note stored before #279 may not say.
    const lede = container.querySelector('.lede').textContent
    expect(lede).toContain('may not go past a contract that pays out to, or is paid by, many addresses')
    expect(lede).not.toContain('each note says')
    expect(screen.getByText(NOTE)).toBeInTheDocument()
    expect(container.querySelector('.privacy-notes').textContent).toContain('2 hops away, 9 ETH reached it')
    // Not the red risk alert: no role="alert".
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })

  it('renders nothing on a case without one, as every case is with the flag off', () => {
    const { container } = render(<PrivacyNotes result={{ risk_matches: [] }} unit="ETH" />)
    expect(container.innerHTML).toBe('')
  })
})

describe('a privacy contract on the maps', () => {
  it('has its own role, never a confirmed risk or a flag', () => {
    expect(roleOf(node)).toBe('privacy')
    expect(isConfirmedRisk(node)).toBe(false)
    expect(flagCounts({ nodes: [node] })).toEqual({ possible: 0, confirmed: 0 })
    // A risk label on the same address still wins (the backend never sets both).
    expect(roleOf({ ...node, risk_category: 'sanctioned' })).toBe('risk')
  })

  it('is grey with a dotted halo on the hop map, with a key entry only when one is on the map', () => {
    const data = { nodes: [{ id: SEED, address: SEED, is_seed: true, depth: 0 }, node],
      edges: [{ source: SEED, target: RAILGUN, value_native: 9 }] }
    const { container } = render(<FlowView data={data} tracePath={[]} unit="ETH" />)
    const dot = container.querySelector('.flow-node.role-privacy circle[vector-effect]:not(.halo)')
    expect(dot.getAttribute('fill')).toBe('var(--text-2)')
    expect(screen.getByText('Privacy protocol (not an accusation)')).toBeInTheDocument()
    expect(container.querySelector('.flow-legend .role-privacy .halo').getAttribute('stroke-dasharray')).toBeTruthy()

    const { container: without } = render(<FlowView data={{ nodes: [data.nodes[0]], edges: [] }} tracePath={[]} unit="ETH" />)
    expect(without.querySelector('.flow-legend .role-privacy')).toBeNull()
  })
})
