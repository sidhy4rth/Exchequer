import { act, render } from '@testing-library/react'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { applyTheme } from '../theme'
import GraphView, { PALETTES } from './GraphView'

// The canvas is react-force-graph's; stubbed, it hands back the callbacks
// GraphView paints with, so they can be called here.
const graph = vi.hoisted(() => ({ props: null }))
vi.mock('react-force-graph-2d', () => ({ default: (props) => { graph.props = props; return null } }))

// jsdom lays nothing out: give the container a size so the canvas mounts.
beforeAll(() => {
  globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback }
    observe() { this.callback([{ contentRect: { width: 800, height: 600 } }]) }
    disconnect() {}
    unobserve() {}
  }
})
afterAll(() => act(() => applyTheme('dark')))

const addr = (c) => '0x' + c.repeat(40)
const [SEED, MID, CEX, DEP, BET, SIDE] = ['a', 'b', 'c', 'd', 'e', 'f'].map(addr)
const data = {
  nodes: [
    { id: SEED, address: SEED, is_seed: true, depth: 0 },
    { id: MID, address: MID, depth: 1, flags: ['peel_chain'], total_in_native: 100 },
    { id: CEX, address: CEX, depth: 2, exchange: 'Binance', label: 'Binance 14', total_in_native: 60 },
    { id: DEP, address: DEP, depth: 2, exchange: 'OKX', inferred_exchange: 'OKX', total_in_native: 20 },
    { id: BET, address: BET, depth: 2, risk_category: 'gambling', risk_entity: 'Stake.com', total_in_native: 10 },
    { id: SIDE, address: SIDE, depth: 2, flags: ['amount_split'], total_in_native: 10 },
  ],
  edges: [
    { source: SEED, target: MID, value_native: 100, flags: ['peel_chain'] },
    { source: MID, target: CEX, value_native: 60, flags: ['peel_chain'] },
    { source: MID, target: DEP, value_native: 20 },
    { source: MID, target: BET, value_native: 10 },
    { source: MID, target: SIDE, value_native: 10, flags: ['amount_split'] },
  ],
}
const route = [{ address: SEED }, { address: MID }, { address: CEX }]

/** A canvas context that records every fill (colour, alpha) and stroke (colour, dash). */
function recorder() {
  const fills = []
  const strokes = []
  let dash = []
  const ctx = {
    globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: '', textBaseline: '',
    save() {}, restore() {}, beginPath() {}, arc() {}, fillRect() {}, fillText() {},
    measureText: () => ({ width: 10 }),
    setLineDash(d) { dash = d },
    fill() { fills.push({ colour: ctx.fillStyle, alpha: ctx.globalAlpha }) },
    stroke() { strokes.push({ colour: ctx.strokeStyle, dash }) },
  }
  return { ctx, fills, strokes }
}

describe.each(['dark', 'light'])('the bubble graph, %s', (theme) => {
  // The skin flips while the graph is on screen, as from the top bar.
  const show = () => {
    const view = render(<GraphView data={data} tracePath={route} />)
    act(() => applyTheme(theme))
    return view
  }

  it('has a key whose entries all look different', () => {
    const { container } = show()
    const swatches = [...container.querySelectorAll('.legend .item')].map((item) => item.querySelector('svg, span'))
    expect(swatches).toHaveLength(8)
    const looks = swatches.map((s) => s.outerHTML.replace(/ class="[^"]*"/g, ''))
    expect(new Set(looks).size).toBe(looks.length)
  })

  it('paints each role the way its key shows it', () => {
    show()
    const paint = (id) => {
      const drawn = recorder()
      graph.props.nodeCanvasObject({ ...data.nodes.find((n) => n.id === id), x: 0, y: 0 }, drawn.ctx, 1)
      return drawn
    }
    const dot = (id, role) => paint(id).fills.find((f) => f.colour === PALETTES[theme][role])
    // An inferred deposit and a pattern hit are faded under a confirmed exchange.
    expect(dot(CEX, 'exchange').alpha).toBe(1)
    expect(dot(DEP, 'inferred').alpha).toBeLessThan(1)
    expect(dot(SIDE, 'flagged').alpha).toBeLessThan(1)
    // A gambling platform's wallet has a dashed ring.
    expect(paint(BET).strokes.find((s) => s.colour === PALETTES[theme].gambling).dash.length).toBeGreaterThan(0)
  })

  it('keeps the traced funds solid where a pattern fired on them; a flagged transfer off the route is dashed', () => {
    show()
    const link = (s, t) => graph.props.graphData.links.find((l) => l.source === s && l.target === t)
    expect(graph.props.linkLineDash(link(SEED, MID))).toBeNull()
    expect(graph.props.linkLineDash(link(MID, CEX))).toBeNull()
    expect(graph.props.linkLineDash(link(MID, SIDE))).toBeTruthy()
    expect(graph.props.linkLineDash(link(MID, DEP))).toBeNull()
  })
})
