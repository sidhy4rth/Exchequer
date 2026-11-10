import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { applyTheme } from '../theme'
import GraphView, { EASE_POP, PALETTES, keptByFlags } from './GraphView'
import { DASH, FADED } from './RoleSwatch'

// The canvas is react-force-graph's; stubbed, it hands back the callbacks
// GraphView paints with, so they can be called here, and the methods GraphView
// calls on the mounted canvas, so those can be counted. Each mount (a theme
// flip remounts it) is a new canvas, as in the browser.
const graph = vi.hoisted(() => ({ props: null, api: null, mounts: 0 }))
vi.mock('react-force-graph-2d', async () => {
  const React = await import('react')
  const { vi: spy } = await import('vitest')
  const chain = () => {
    const force = {}
    force.strength = spy.fn(() => force)
    force.distance = spy.fn(() => force)
    return force
  }
  const canvas = () => {
    const forces = { charge: chain(), link: chain() }
    const api = {
      forces,
      d3Force: spy.fn((name, force) => {
        if (force === undefined) return forces[name]
        forces[name] = force
        return api
      }),
      d3ReheatSimulation: spy.fn(),
      zoomToFit: spy.fn(),
      getGraphBbox: spy.fn(() => ({ x: [-50, 50], y: [-40, 40] })),
      zoom: spy.fn(() => 1),
      centerAt: spy.fn(),
      pauseAnimation: spy.fn(),
      resumeAnimation: spy.fn(),
    }
    return api
  }
  const ForceGraph = React.forwardRef((props, ref) => {
    graph.props = props
    const api = React.useMemo(() => { graph.mounts += 1; return canvas() }, [])
    graph.api = api
    React.useImperativeHandle(ref, () => api, [api])
    return null
  })
  return { default: ForceGraph }
})

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
    setLineDash(d) { dash = d }, translate() {}, scale() {},
    fill() { fills.push({ colour: ctx.fillStyle, alpha: ctx.globalAlpha }) },
    stroke() { strokes.push({ colour: ctx.strokeStyle, dash }) },
  }
  return { ctx, fills, strokes }
}

describe.each(['dark', 'light'])('the bubble graph, %s', (theme) => {
  // The skin flips while the graph is on screen, as from the top bar.
  const show = () => {
    vi.useFakeTimers()
    const view = render(<GraphView data={data} tracePath={route} />)
    act(() => applyTheme(theme))
    // Past the hop-by-hop reveal: every address on the canvas.
    act(() => vi.runAllTimers())
    return view
  }
  afterEach(() => vi.useRealTimers())

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

  it('paints a possible flag in the risk red, faded, with a dashed ring; a confirmed hit stays solid', () => {
    show()
    const p = PALETTES[theme]
    expect(p.flagged).toBe(p.risk)
    // The transfer a pattern fired on is tinted with the same red.
    const [r, g, b] = p.risk.match(/[0-9a-f]{2}/gi).map((h) => parseInt(h, 16))
    expect(p.linkFlagged).toMatch(new RegExp(`^rgba\\(${r},${g},${b},0\\.\\d+\\)$`))

    const paint = (node) => {
      const drawn = recorder()
      graph.props.nodeCanvasObject({ ...node, x: 0, y: 0 }, drawn.ctx, 1)
      return drawn
    }
    const flag = paint(data.nodes.find((n) => n.id === SIDE))
    expect(flag.fills.find((f) => f.colour === p.risk).alpha).toBe(FADED)
    expect(flag.strokes.find((s) => s.colour === p.risk).dash).toEqual(DASH)

    const listed = paint({ id: 'x', address: addr('9'), depth: 2, risk_category: 'sanctioned', total_in_native: 10 })
    expect(listed.fills.find((f) => f.colour === p.risk).alpha).toBe(1)
    expect(listed.strokes.filter((s) => s.colour === p.risk).every((s) => s.dash.length === 0)).toBe(true)
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

describe('the bubble graph in motion', () => {
  afterEach(() => vi.useRealTimers())
  const ids = () => graph.props.graphData.nodes.map((n) => n.id).sort()
  const reduceMotion = () => vi.stubGlobal('matchMedia', (query) => ({
    matches: query.includes('reduce'), addEventListener() {}, removeEventListener() {},
  }))

  it('configures the packed-bubble physics on the canvas once it has mounted', () => {
    render(<GraphView data={data} tracePath={route} />)
    const { api } = graph
    expect(api.d3Force).toHaveBeenCalledWith('collide', expect.any(Function))
    expect(api.forces.charge.strength).toHaveBeenCalled()
    expect(api.forces.link.distance).toHaveBeenCalled()
    expect(api.d3ReheatSimulation).toHaveBeenCalled()
    // Collision clears each bubble's own radius.
    const collide = api.d3Force.mock.calls.find(([name]) => name === 'collide')[1]
    expect(collide.radius()({ ...data.nodes[0] })).toBeGreaterThan(8)
  })

  it('configures the physics again on the new canvas a theme flip mounts', () => {
    render(<GraphView data={data} tracePath={route} />)
    const before = graph.mounts
    act(() => applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'))
    expect(graph.mounts).toBe(before + 1)
    expect(graph.api.d3Force).toHaveBeenCalledWith('collide', expect.any(Function))
  })

  it('reveals the trace hop by hop: the reported address, then each hop', () => {
    vi.useFakeTimers()
    render(<GraphView data={data} tracePath={route} />)
    expect(ids()).toEqual([SEED])
    expect(graph.props.graphData.links).toHaveLength(0)
    // No money moves until the whole route is on screen.
    expect(graph.props.linkDirectionalParticles).toBe(0)
    act(() => vi.advanceTimersByTime(600))
    expect(ids()).toEqual([SEED, MID].sort())
    // A hop is born beside the address that paid it.
    expect(graph.props.graphData.links.map((l) => [l.source, l.target])).toEqual([[SEED, MID]])
    act(() => vi.advanceTimersByTime(600))
    expect(ids()).toEqual(data.nodes.map((n) => n.id).sort())
    expect(graph.props.graphData.links).toHaveLength(data.edges.length)
    expect(typeof graph.props.linkDirectionalParticles).toBe('function')
    // Framed only once the layout has settled, never while the last hop is
    // still packed inside its parents.
    act(() => vi.advanceTimersByTime(3000))
    expect(graph.api.zoomToFit).not.toHaveBeenCalled()
    act(() => graph.props.onEngineStop())
    expect(graph.api.zoomToFit).toHaveBeenCalledTimes(1)
    act(() => graph.props.onEngineStop())
    act(() => vi.runAllTimers())
    expect(graph.api.zoomToFit).toHaveBeenCalledTimes(1)
  })

  it('frames a revealed trace anyway when the simulation never reports a stop', () => {
    vi.useFakeTimers()
    render(<GraphView data={data} tracePath={route} />)
    act(() => vi.advanceTimersByTime(1200))
    act(() => vi.advanceTimersByTime(5900))
    expect(graph.api.zoomToFit).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(200))
    expect(graph.api.zoomToFit).toHaveBeenCalledTimes(1)
  })

  it('holds the camera still through the reveal: set once per run, not at every hop', () => {
    vi.useFakeTimers()
    render(<GraphView data={data} tracePath={route} />)
    const held = () => graph.api.zoom.mock.calls.filter((call) => call.length === 2)
    act(() => graph.props.onEngineTick())
    expect(held()).toEqual([[4 / Math.cbrt(data.nodes.length), 0]])
    act(() => vi.advanceTimersByTime(600))
    act(() => graph.props.onEngineTick())
    act(() => vi.advanceTimersByTime(600))
    act(() => graph.props.onEngineTick())
    expect(held()).toHaveLength(1)
    // A replay is a new run: the camera eases back to the same framing once.
    fireEvent.click(screen.getByRole('button', { name: 'Replay' }))
    act(() => graph.props.onEngineTick())
    act(() => graph.props.onEngineTick())
    expect(held()).toHaveLength(2)
    expect(held()[1]).toEqual([4 / Math.cbrt(data.nodes.length), 400])
  })

  it('grows a newly revealed bubble from nothing with the pop easing', () => {
    expect(EASE_POP(0)).toBe(0)
    expect(EASE_POP(1)).toBe(1)
    expect(Math.max(...[0.4, 0.5, 0.6, 0.7].map(EASE_POP))).toBeGreaterThan(1)
    vi.useFakeTimers()
    render(<GraphView data={data} tracePath={route} />)
    act(() => vi.advanceTimersByTime(600))
    const born = graph.props.graphData.nodes.find((n) => n.id === MID)
    expect(born.__bornAt).toBeTypeOf('number')
    const scales = []
    const ctx = { save() {}, restore() {}, beginPath() {}, arc() {}, fill() {}, stroke() {}, setLineDash() {},
      translate() {}, scale(x) { scales.push(x) }, fillRect() {}, fillText() {}, measureText: () => ({ width: 1 }) }
    vi.spyOn(performance, 'now').mockReturnValue(born.__bornAt + 45)
    graph.props.nodeCanvasObject({ ...born, x: 0, y: 0 }, ctx, 1)
    expect(scales[0]).toBeGreaterThan(0)
    expect(scales[0]).toBeLessThan(0.5)
  })

  it('replays the reveal from the reported address', () => {
    vi.useFakeTimers()
    render(<GraphView data={data} tracePath={route} />)
    act(() => vi.runAllTimers())
    expect(ids()).toHaveLength(data.nodes.length)
    fireEvent.click(screen.getByRole('button', { name: 'Replay' }))
    expect(ids()).toEqual([SEED])
    act(() => vi.runAllTimers())
    expect(ids()).toHaveLength(data.nodes.length)
  })

  it('shows everything at once, with the route still, under reduced motion', () => {
    reduceMotion()
    render(<GraphView data={data} tracePath={route} />)
    expect(ids()).toHaveLength(data.nodes.length)
    expect(graph.props.linkDirectionalParticles).toBe(0)
    expect(screen.getByRole('button', { name: 'Pause motion' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Replay' })).toBeDisabled()
    // Drawn at full size, never mid-growth.
    const scales = []
    const ctx = { save() {}, restore() {}, beginPath() {}, arc() {}, fill() {}, stroke() {}, setLineDash() {},
      translate() {}, scale(x) { scales.push(x) }, fillRect() {}, fillText() {}, measureText: () => ({ width: 1 }) }
    graph.props.nodeCanvasObject({ ...data.nodes[1], __bornAt: performance.now(), x: 0, y: 0 }, ctx, 1)
    expect(scales).toEqual([])
  })

  it('Pause motion stops the moving money and finishes the reveal at once', () => {
    vi.useFakeTimers()
    render(<GraphView data={data} tracePath={route} />)
    const pause = screen.getByRole('button', { name: 'Pause motion' })
    expect(pause).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(pause)
    expect(pause).toHaveAttribute('aria-pressed', 'true')
    expect(ids()).toHaveLength(data.nodes.length)
    expect(graph.props.linkDirectionalParticles).toBe(0)
    fireEvent.click(pause)
    expect(pause).toHaveAttribute('aria-pressed', 'false')
    // The reveal is not replayed by un-pausing; the route moves again.
    expect(ids()).toHaveLength(data.nodes.length)
    expect(typeof graph.props.linkDirectionalParticles).toBe('function')
  })

  describe('show only flags', () => {
    const draw = (node) => {
      const fills = []
      const texts = []
      const ctx = { globalAlpha: 1, fillStyle: '', save() {}, restore() {}, beginPath() {}, arc() {}, stroke() {}, setLineDash() {},
        translate() {}, scale() {}, fillRect() {}, measureText: () => ({ width: 1 }),
        fill() { fills.push(ctx.globalAlpha) }, fillText(t) { texts.push(t) } }
      graph.props.nodeCanvasObject({ ...node, x: 0, y: 0 }, ctx, 1)
      return { alpha: Math.max(...fills), labelled: texts.length > 0 }
    }
    const listed = { id: addr('9'), address: addr('9'), depth: 2, risk_category: 'frozen', risk_entity: 'Tether (USDT freeze)', total_in_native: 5 }
    const withRisk = { nodes: [...data.nodes, listed], edges: [...data.edges, { source: MID, target: listed.id, value_native: 5 }] }

    it('keeps exactly the possible flags, the confirmed hits and the reported address', () => {
      reduceMotion()
      render(<GraphView data={withRisk} tracePath={route} flagsOnly />)
      const bright = withRisk.nodes.filter((n) => draw(n).alpha > 0.2).map((n) => n.id).sort()
      // The gambling platform is an attribution, not a confirmed hit: it fades, as on the hop map.
      expect(bright).toEqual([SEED, MID, SIDE, listed.id].sort())
      expect(withRisk.nodes.filter(keptByFlags).map((n) => n.id).sort()).toEqual(bright)
      // Every kept flag and hit is named, even an ordinary pattern hit.
      expect(draw(withRisk.nodes.find((n) => n.id === SIDE)).labelled).toBe(true)
      expect(draw(withRisk.nodes.find((n) => n.id === CEX)).labelled).toBe(false)
      // A transfer stays bright only when both of its ends are kept.
      const link = (s, t) => graph.props.graphData.links.find((l) => l.source === s && l.target === t)
      const faded = PALETTES[document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'].linkFaded
      expect(graph.props.linkColor(link(MID, SIDE))).not.toBe(faded)
      expect(graph.props.linkColor(link(MID, CEX))).toBe(faded)
    })

    it('counts the flags from the trace in its chip', () => {
      reduceMotion()
      const { rerender } = render(<GraphView data={withRisk} tracePath={route} />)
      expect(screen.queryByRole('status')).toBeNull()
      expect(draw(data.nodes.find((n) => n.id === CEX)).alpha).toBe(1)
      rerender(<GraphView data={withRisk} tracePath={route} flagsOnly />)
      // MID and SIDE fired a pattern; only the frozen wallet is a confirmed hit
      // (the gambling platform is an attribution), the same count as the hop map.
      expect(screen.getByRole('status')).toHaveTextContent('Showing 2 possible flags · 1 confirmed')
    })
  })

  it('on a phone: no tooltips or hint, a finger-sized hit area, the key left to the page; a tap still selects', () => {
    reduceMotion()
    const onSelect = vi.fn()
    const { container } = render(<GraphView data={data} tracePath={route} compact onSelect={onSelect} selected={null} />)
    expect(graph.props.nodeLabel).toBeNull()
    expect(graph.props.linkLabel).toBeNull()
    expect(container.querySelector('.graph-hint')).toBeNull()
    expect(container.querySelector('.legend')).toBeNull()
    expect(container.querySelector('.graph-view.compact')).not.toBeNull()
    const arcs = []
    const ctx = { beginPath() {}, fill() {}, arc(x, y, r) { arcs.push(r) } }
    const node = graph.props.graphData.nodes.find((n) => n.id === MID)
    graph.props.nodePointerAreaPaint({ ...node, x: 0, y: 0 }, '#000', ctx)
    const drawn = []
    graph.props.nodeCanvasObject({ ...node, x: 0, y: 0 }, { save() {}, restore() {}, beginPath() {}, arc(x, y, r) { drawn.push(r) },
      fill() {}, stroke() {}, setLineDash() {}, fillRect() {}, fillText() {}, measureText: () => ({ width: 1 }) }, 1)
    expect(arcs[0] - drawn[0]).toBeGreaterThanOrEqual(22)
    act(() => graph.props.onNodeClick(node))
    expect(onSelect).toHaveBeenCalledWith(node)
  })

  it('on a phone keeps the Jump-to list behind a finger-sized toggle, and a jump selects', () => {
    reduceMotion()
    const onSelect = vi.fn()
    render(<GraphView data={data} tracePath={route} compact onSelect={onSelect} selected={null} />)
    const toggle = screen.getByRole('button', { name: /^Jump to/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const list = screen.getByRole('group', { name: 'Jump to a wallet' })
    // One button per exchange, inferred deposit and gambling platform.
    expect(list.querySelectorAll('button')).toHaveLength(3)
    fireEvent.click(screen.getByRole('button', { name: /Binance 14/ }))
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: CEX }))
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('shows only fired patterns as possible-flag tags, never a confirmed category', () => {
    reduceMotion()
    render(<GraphView data={data} tracePath={route} />)
    const tags = (html) => [...new DOMParser().parseFromString(html, 'text/html').querySelectorAll('.tags span')].map((t) => t.textContent)
    const sanctioned = { id: 'x', address: addr('9'), depth: 2, flags: ['sanctioned'], risk_category: 'sanctioned' }
    expect(tags(graph.props.nodeLabel(sanctioned))).toEqual([])
    expect(graph.props.nodeLabel(sanctioned)).toContain('Sanctioned entity')
    const split = { id: 'y', address: addr('8'), depth: 2, flags: ['amount_split', 'frozen'], risk_category: 'frozen' }
    expect(tags(graph.props.nodeLabel(split))).toEqual(['Amount split'])
  })

  it('names quiet addresses in the dim ink, which holds its contrast in both themes', () => {
    reduceMotion()
    render(<GraphView data={data} tracePath={route} onSelect={() => {}} selected={SEED} />)
    const theme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
    const texts = []
    const ctx = { globalAlpha: 1, fillStyle: '', save() {}, restore() {}, beginPath() {}, arc() {}, fill() {}, stroke() {}, setLineDash() {},
      translate() {}, scale() {}, fillRect() {}, measureText: () => ({ width: 1 }), fillText(t) { texts.push(ctx.fillStyle) } }
    // An ordinary address beside the selected one is named, in the dim ink.
    const plainNode = { id: MID, address: MID, depth: 1, total_in_native: 100 }
    graph.props.nodeCanvasObject({ ...plainNode, x: 0, y: 0 }, ctx, 1)
    expect(texts).toEqual([PALETTES[theme].dim])
    expect(graph.props.nodeLabel(plainNode)).toContain(`color:${PALETTES[theme].dim}`)
  })

  it('re-frames on f only while focus is inside the map', () => {
    reduceMotion()
    vi.useFakeTimers()
    render(<GraphView data={data} tracePath={route} />)
    act(() => vi.runAllTimers())
    const before = graph.api.zoomToFit.mock.calls.length
    fireEvent.keyDown(window, { key: 'f' })
    expect(graph.api.zoomToFit).toHaveBeenCalledTimes(before)
    screen.getByRole('button', { name: 'Fit' }).focus()
    fireEvent.keyDown(window, { key: 'f' })
    expect(graph.api.zoomToFit).toHaveBeenCalledTimes(before + 1)
  })

  it('a parent that owns the selection is asked to clear it when the selected bubble is clicked again', () => {
    reduceMotion()
    const onSelect = vi.fn()
    const node = () => graph.props.graphData.nodes.find((n) => n.id === MID)
    const { rerender } = render(<GraphView data={data} tracePath={route} onSelect={onSelect} selected={null} />)
    act(() => graph.props.onNodeClick(node()))
    expect(onSelect).toHaveBeenLastCalledWith(node())
    rerender(<GraphView data={data} tracePath={route} onSelect={onSelect} selected={MID} />)
    act(() => graph.props.onNodeClick(node()))
    expect(onSelect).toHaveBeenLastCalledWith(null)
    act(() => graph.props.onBackgroundClick())
    expect(onSelect).toHaveBeenLastCalledWith(null)
  })

  it('keeps the hover tooltip and the key on a desk', () => {
    reduceMotion()
    const { container } = render(<GraphView data={data} tracePath={route} />)
    expect(graph.props.nodeLabel).toBeTypeOf('function')
    expect(graph.props.nodeLabel(data.nodes[5])).toContain('Possible flag')
    expect(container.querySelector('.graph-hint')).not.toBeNull()
    expect(container.querySelector('.legend')).toHaveTextContent('Possible flag · pattern (not confirmed)')
    expect(container.querySelector('.legend')).toHaveTextContent('Sanctioned / mixer / frozen (confirmed)')
  })

  it('stops drawing while hidden, and frames the map when it is first shown', () => {
    reduceMotion()
    vi.useFakeTimers()
    const { rerender } = render(<GraphView data={data} tracePath={route} active={false} />)
    act(() => vi.runAllTimers())
    expect(graph.api.pauseAnimation).toHaveBeenCalled()
    expect(graph.api.zoomToFit).not.toHaveBeenCalled()
    rerender(<GraphView data={data} tracePath={route} active />)
    expect(graph.api.resumeAnimation).toHaveBeenCalled()
    act(() => vi.runAllTimers())
    expect(graph.api.zoomToFit).toHaveBeenCalledTimes(1)
    // Hidden and shown again, an already framed map keeps the camera where the officer left it.
    rerender(<GraphView data={data} tracePath={route} active={false} />)
    rerender(<GraphView data={data} tracePath={route} active />)
    act(() => vi.runAllTimers())
    expect(graph.api.zoomToFit).toHaveBeenCalledTimes(1)
  })

  it('holds the reveal until a hidden map is shown', () => {
    vi.useFakeTimers()
    const { rerender } = render(<GraphView data={data} tracePath={route} active={false} />)
    act(() => vi.advanceTimersByTime(5000))
    expect(ids()).toEqual([SEED])
    rerender(<GraphView data={data} tracePath={route} active />)
    act(() => vi.advanceTimersByTime(1200))
    expect(ids()).toHaveLength(data.nodes.length)
  })
})
