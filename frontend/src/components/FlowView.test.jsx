import { readFileSync } from 'node:fs'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import FlowView, { COLUMN_STEP_MS } from './FlowView'

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

// ---- Motion, selection and "Show only flags" ------------------------------

const PLAIN = '0x' + 'f'.repeat(40)
const MIXER = '0x' + 'e'.repeat(40)
const short4 = (a) => `${a.slice(0, 4)}…${a.slice(-4)}`
// Three columns: the route seed -> MID (a possible flag) -> Binance; a side
// transfer MID -> SIDE that fired amount_split; a plain branch to a mixer.
const mixed = {
  nodes: [
    { id: SEED, address: SEED, is_seed: true, depth: 0 },
    { id: MID, address: MID, depth: 1, flags: ['peel_chain'], total_in_native: 100 },
    { id: PLAIN, address: PLAIN, depth: 1, total_in_native: 20 },
    { id: DEPOSIT, address: DEPOSIT, depth: 2, exchange: 'Binance', label: 'Binance 14', total_in_native: 90 },
    { id: SIDE, address: SIDE, depth: 2, flags: ['amount_split'], total_in_native: 10 },
    { id: MIXER, address: MIXER, depth: 2, risk_category: 'mixer', risk_entity: 'Tornado Cash', total_in_native: 20 },
  ],
  edges: [
    { source: SEED, target: MID, value_native: 100 },
    { source: SEED, target: PLAIN, value_native: 20 },
    { source: MID, target: DEPOSIT, value_native: 90 },
    { source: MID, target: SIDE, value_native: 10, flags: ['amount_split'] },
    { source: PLAIN, target: MIXER, value_native: 20 },
  ],
}

const nodeOf = (container, id) => container.querySelector(`.flow-node[data-address="${id}"]`)
const linkOf = (container, from, to) => container.querySelector(`.flow-lg[data-edge="${from}>${to}"]`)
const reduceMotion = () => vi.stubGlobal('matchMedia', (query) => ({
  matches: query.includes('reduce'), media: query, addEventListener() {}, removeEventListener() {},
}))
const settle = () => act(() => { vi.advanceTimersByTime(5000) })
const comets = (container) => [...container.querySelectorAll('.flow-comet')]
const cometLit = (container) => comets(container).some((el) => el.style.opacity === '1')

describe('the hop map entrance', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('brings the columns in one at a time, the lines drawing on as their far end arrives, then the light', () => {
    const { container } = render(<FlowView data={mixed} tracePath={route} unit="ETH" />)
    const pop = (id) => nodeOf(container, id).querySelector('.flow-pop')
    const heads = () => [...container.querySelectorAll('.flow-col')]

    expect(pop(SEED)).toHaveClass('in')
    expect(pop(MID)).toHaveClass('pre')
    expect(pop(DEPOSIT)).toHaveClass('pre')
    expect(heads()[0]).toHaveClass('in')
    expect(heads()[1]).toHaveClass('pre')
    expect(linkOf(container, SEED, MID)).toHaveClass('pre')
    act(() => { vi.advanceTimersByTime(100) })
    expect(cometLit(container)).toBe(false) // no light while the columns arrive

    act(() => { vi.advanceTimersByTime(COLUMN_STEP_MS - 100) })
    expect(pop(MID)).toHaveClass('in')
    expect(pop(PLAIN)).toHaveClass('in')
    expect(pop(DEPOSIT)).toHaveClass('pre')
    // Top to bottom, 40 ms apart.
    expect([pop(MID).style.animationDelay, pop(PLAIN).style.animationDelay].sort()).toEqual(['0ms', '40ms'])
    const drawn = linkOf(container, SEED, MID).querySelector('.flow-link')
    expect(linkOf(container, SEED, MID)).not.toHaveClass('pre')
    expect(drawn).toHaveClass('drawing')
    expect(drawn.getAttribute('pathLength')).toBe('1')

    act(() => { vi.advanceTimersByTime(COLUMN_STEP_MS) })
    expect(pop(DEPOSIT)).toHaveClass('in')
    // The dashed possible-flag line draws on through a mask, keeping its dashes.
    const side = linkOf(container, MID, SIDE)
    expect(side.getAttribute('mask')).toMatch(/^url\(#/)
    expect(container.querySelector(`mask${side.getAttribute('mask').slice(4, -1)}`)).not.toBeNull()
    expect(side.querySelector('.flow-link')).not.toHaveClass('drawing')

    settle()
    expect(container.querySelector('.pre, .in, .drawing, mask')).toBeNull()
    expect(linkOf(container, MID, SIDE).getAttribute('mask')).toBeNull()
    act(() => { vi.advanceTimersByTime(100) })
    expect(cometLit(container)).toBe(true)
  })

  it('is not played again when the map is hidden and shown; Replay plays it again', () => {
    const view = (active) => <FlowView data={mixed} tracePath={route} unit="ETH" active={active} />
    const { container, rerender } = render(view(true))
    settle()
    rerender(view(false))
    act(() => { vi.advanceTimersByTime(100) })
    expect(cometLit(container)).toBe(false) // hidden: the light stops
    rerender(view(true))
    expect(container.querySelector('.pre, .in')).toBeNull()
    act(() => { vi.advanceTimersByTime(100) })
    expect(cometLit(container)).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Replay the entrance' }))
    expect(container.querySelector('.pre')).not.toBeNull()
    expect(nodeOf(container, SEED).querySelector('.flow-pop')).toHaveClass('in')
    settle()
    expect(container.querySelector('.pre, .in')).toBeNull()
  })

  it('waits for a map mounted hidden to be shown', () => {
    const view = (active) => <FlowView data={mixed} tracePath={route} unit="ETH" active={active} />
    const { container, rerender } = render(view(false))
    settle()
    expect(nodeOf(container, SEED).querySelector('.flow-pop')).toHaveClass('pre')
    rerender(view(true))
    expect(nodeOf(container, SEED).querySelector('.flow-pop')).toHaveClass('in')
    expect(nodeOf(container, MID).querySelector('.flow-pop')).toHaveClass('pre')
  })

  it('draws the final picture at once, with nothing moving, under reduced motion', () => {
    reduceMotion()
    const { container } = render(<FlowView data={mixed} tracePath={route} unit="ETH" />)
    expect(container.querySelector('.pre, .in, .drawing, mask')).toBeNull()
    act(() => { vi.advanceTimersByTime(1000) })
    expect(cometLit(container)).toBe(false)
    fireEvent.click(nodeOf(container, MID))
    expect(nodeOf(container, MID).querySelector('.sel-ring')).not.toBeNull()
    expect(container.querySelector('.flow-sweep')).toBeNull()
    expect(screen.getByRole('button', { name: 'Pause motion' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Replay the entrance' })).toBeDisabled()
  })

  it('Pause motion stops the light and the sweeps, and says so', () => {
    const { container } = render(<FlowView data={mixed} tracePath={route} unit="ETH" />)
    settle()
    fireEvent.click(nodeOf(container, MID))
    expect(container.querySelectorAll('.flow-sweep').length).toBeGreaterThan(0)
    const pause = screen.getByRole('button', { name: 'Pause motion' })
    expect(pause).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(pause)
    expect(pause).toHaveAttribute('aria-pressed', 'true')
    expect(container.querySelector('.flow-sweep')).toBeNull()
    act(() => { vi.advanceTimersByTime(500) })
    expect(cometLit(container)).toBe(false)
    fireEvent.click(pause)
    expect(pause).toHaveAttribute('aria-pressed', 'false')
    expect(container.querySelectorAll('.flow-sweep').length).toBeGreaterThan(0)
  })
})

describe('selecting an address on the hop map', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true })
  })
  afterEach(() => {
    vi.useRealTimers()
    delete navigator.clipboard
  })

  it("is the caller's when it passes onSelect: a click copies and asks, the ring follows `selected`", () => {
    const onSelect = vi.fn()
    const view = (selected) => <FlowView data={mixed} tracePath={route} unit="ETH" selected={selected} onSelect={onSelect} />
    const { container, rerender } = render(view(null))
    settle()
    fireEvent.click(nodeOf(container, MID))
    expect(onSelect).toHaveBeenLastCalledWith(MID)
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(MID)
    expect(nodeOf(container, MID).querySelector('.sel-ring')).toBeNull() // not until the caller says so

    rerender(view(MID))
    const ring = nodeOf(container, MID).querySelector('.sel-ring')
    expect(ring).not.toBeNull()
    // MID is on the route: its dot (5) wears the green path ring, so the ring sits outside it.
    expect(Number(ring.getAttribute('r'))).toBe(14)
    expect(nodeOf(container, MID)).toHaveClass('selected')
    // Lit like a lasting hover: its transfers sweep, the rest recede.
    expect(linkOf(container, MID, SIDE).querySelector('.flow-sweep')).not.toBeNull()
    expect(nodeOf(container, PLAIN).style.opacity).toBe('0.18')
    expect(nodeOf(container, DEPOSIT).style.opacity).toBe('1')
    expect(screen.getByText(`Selected ${MID.slice(0, 6)}…${MID.slice(-4)}`)).toBeInTheDocument()

    fireEvent.click(nodeOf(container, MID))
    expect(onSelect).toHaveBeenLastCalledWith(null)
    onSelect.mockClear()
    fireEvent.keyDown(container.querySelector('.flow-stage'), { key: 'Escape' })
    expect(onSelect).toHaveBeenLastCalledWith(null)

    // A hovered address wins while the pointer is on it.
    fireEvent.mouseEnter(nodeOf(container, PLAIN))
    expect(nodeOf(container, PLAIN).style.opacity).toBe('1')
    expect(nodeOf(container, SIDE).style.opacity).toBe('0.18')
    fireEvent.mouseLeave(nodeOf(container, PLAIN))
    expect(nodeOf(container, SIDE).style.opacity).toBe('1')
  })

  it('keeps its own selection without onSelect: click to select, again or on the empty stage to clear', () => {
    const { container } = render(<FlowView data={mixed} tracePath={route} unit="ETH" />)
    settle()
    fireEvent.click(nodeOf(container, PLAIN))
    expect(Number(nodeOf(container, PLAIN).querySelector('.sel-ring').getAttribute('r'))).toBe(3.5 + 5)
    fireEvent.click(nodeOf(container, PLAIN))
    expect(container.querySelector('.sel-ring')).toBeNull()
    fireEvent.click(nodeOf(container, MIXER))
    expect(nodeOf(container, MIXER).querySelector('.sel-ring')).not.toBeNull()
    fireEvent.click(container.querySelector('.flow svg'))
    expect(container.querySelector('.sel-ring')).toBeNull()
  })
})

describe('"Show only flags" on the hop map', () => {
  it('keeps exactly the possible flags, the confirmed risk and the reported address, and captions them', () => {
    const { container } = render(<FlowView data={mixed} tracePath={route} unit="ETH" flagsOnly />)
    const alphaOf = (id) => nodeOf(container, id).style.opacity
    for (const id of [SEED, MID, SIDE, MIXER]) expect(alphaOf(id)).toBe('1')
    for (const id of [PLAIN, DEPOSIT]) expect(alphaOf(id)).toBe('0.12')
    expect(linkOf(container, SEED, MID).style.opacity).toBe('')
    expect(linkOf(container, MID, SIDE).style.opacity).toBe('')
    for (const [a, b] of [[SEED, PLAIN], [MID, DEPOSIT], [PLAIN, MIXER]]) expect(linkOf(container, a, b).style.opacity).toBe('0.08')
    // Every kept flag says what it is, whatever the row spacing.
    expect(screen.getByText(`possible flag · ${short4(MID)}`)).toBeInTheDocument()
    expect(screen.getByText(`possible flag · ${short4(SIDE)}`)).toBeInTheDocument()
    expect(screen.getByText('Tornado Cash')).toBeInTheDocument()
    expect(screen.getByText('Showing 2 possible flags · 1 confirmed')).toBeInTheDocument()
  })

  it('shows everything, uncaptioned flags and no chip, when off', () => {
    const { container } = render(<FlowView data={mixed} tracePath={route} unit="ETH" />)
    expect(container.querySelector('.flow-node[style*="0.12"]')).toBeNull()
    expect(screen.queryByText(/possible flag ·/)).toBeNull()
    expect(screen.queryByText(/^Showing/)).toBeNull()
  })
})

describe('the hop map colour rule', () => {
  // A literal path here would be rewritten by Vite into an asset URL.
  const sheet = '../styles.css'
  const css = readFileSync(new URL(sheet, import.meta.url), 'utf8')
  const rule = (selector) => new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')} \\{([^}]*)\\}`).exec(css)?.[1]

  it('draws a possible flag red but unconfirmed: faded, with a dashed ring; a confirmed hit solid with a halo', () => {
    const { container } = render(<FlowView data={mixed} tracePath={route} unit="ETH" />)
    const flagged = nodeOf(container, SIDE)
    expect(flagged).toHaveClass('role-flagged')
    expect(flagged.querySelector('circle.dot').getAttribute('fill')).toBe('var(--risk)')
    expect(flagged.querySelector('.halo')).toBeNull()
    expect(rule('.flow .flow-node.role-flagged circle.dot')).toMatch(/fill-opacity: 0\.45/)
    expect(rule('.flow .flow-node.role-flagged circle.dot')).toMatch(/stroke: var\(--risk\); stroke-dasharray/)
    const risk = nodeOf(container, MIXER)
    expect(risk.querySelector('circle.dot').getAttribute('fill')).toBe('var(--risk)')
    expect(risk.querySelector('.halo')).not.toBeNull()
    // A flagged transfer off the route: dashed and red-tinted, not grey.
    expect(rule('.flow .flow-link.flagged')).toMatch(/stroke: var\(--risk\)/)
    expect(rule('.flow .flow-link.flagged')).toMatch(/stroke-dasharray/)
  })

  it('names them apart in the key', () => {
    render(<FlowView data={mixed} tracePath={route} unit="ETH" />)
    expect(screen.getByText('Possible flag · pattern (not confirmed)')).toBeInTheDocument()
    expect(screen.getByText('Sanctioned / mixer / frozen (confirmed)')).toBeInTheDocument()
  })
})

describe('the hop map on a phone (compact)', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  // A tall second column, so the map is scaled to fit and the rows sit close.
  const tall = {
    nodes: [
      { id: SEED, address: SEED, is_seed: true, depth: 0 },
      ...Array.from({ length: 40 }, (_, i) => {
        const id = '0x' + String(i).padStart(2, '0').repeat(20)
        return { id, address: id, depth: 1, total_in_native: 40 - i }
      }),
    ],
    edges: Array.from({ length: 40 }, (_, i) => ({ source: SEED, target: '0x' + String(i).padStart(2, '0').repeat(20), value_native: 40 - i })),
  }

  it('selects the nearest address to a tap, within reach, and shows no hover tooltip', () => {
    const onSelect = vi.fn()
    const { container } = render(<FlowView data={mixed} tracePath={route} unit="ETH" compact onSelect={onSelect} selected={null} />)
    settle()
    expect(container.querySelector('.flow')).toHaveClass('compact')
    const svg = container.querySelector('.flow svg')
    const transform = /translate\(([-\d.]+) ([-\d.]+)\) scale\(([-\d.]+)\)/.exec(svg.querySelector('g[transform]').getAttribute('transform'))
    const [tx, ty, k] = transform.slice(1).map(Number)
    const at = (id) => {
      const dot = nodeOf(container, id).querySelector('circle.dot')
      return { x: Number(dot.getAttribute('cx')) * k + tx, y: Number(dot.getAttribute('cy')) * k + ty }
    }
    const mid = at(MID); const plain = at(PLAIN)
    // Between the two rows, a little nearer PLAIN.
    fireEvent.click(svg, { clientX: mid.x + 4, clientY: mid.y + (plain.y - mid.y) * 0.6 })
    expect(onSelect).toHaveBeenLastCalledWith(PLAIN)
    fireEvent.click(svg, { clientX: mid.x + 6, clientY: mid.y + 3 })
    expect(onSelect).toHaveBeenLastCalledWith(MID)
    onSelect.mockClear()
    // Far from every dot: nothing to pick, and nothing was selected.
    fireEvent.click(svg, { clientX: mid.x + 120, clientY: mid.y + 200 })
    expect(onSelect).not.toHaveBeenCalled()

    fireEvent.mouseEnter(nodeOf(container, MID), { clientX: mid.x, clientY: mid.y })
    expect(container.querySelector('.flow-tip')).toBeNull()
  })

  it('hides the scroll hint, which speaks of a mouse', () => {
    const { container, unmount } = render(<FlowView data={tall} tracePath={[]} unit="ETH" />)
    expect(container.querySelector('.flow-hint')).not.toBeNull()
    unmount()
    const phone = render(<FlowView data={tall} tracePath={[]} unit="ETH" compact />)
    expect(phone.container.querySelector('.flow-hint')).toBeNull()
    // The controls keep their names for a screen reader, without the words on screen.
    expect(screen.getByRole('button', { name: 'Pause motion' })).toHaveTextContent('')
    expect(screen.getByRole('button', { name: 'Replay the entrance' })).toBeInTheDocument()
  })
})
