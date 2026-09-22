import { currentTheme } from '../theme'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { forceCollide } from 'd3-force-3d'

// Kept in sync with the custom properties in styles.css. The canvas paints in
// JS and cannot read CSS variables, so these values are duplicated here on
// purpose — change one, change both.
//
// Three things carry colour: a sanctions or mixer hit (red), a confirmed
// exchange (accent green) and a fired pattern (amber). The reported address is
// bright neutral rather than coloured, and ordinary traced addresses are dim,
// so the eye lands on the answer instead of on decoration.
//
// Red is reserved for the risk lists and outranks the rest. A published
// government designation is a fact from outside this tool, and it should not
// have to compete for attention with the tool's own inferences.
const PALETTES = {
  light: {
    seed: '#16191d', risk: '#b3261e', exchange: '#1d7a4c', inferred: '#9a5b00',
    service: '#b9b5ac', flagged: '#c98a1e', node: '#8a9098',
    link: 'rgba(22,25,29,0.16)', linkPath: '#1d7a4c', linkFlagged: '#c98a1e',
    text: '#16191d', dim: '#5b6169', background: '#ffffff',
    haloExchange: 'rgba(29,122,76,0.16)', haloRisk: 'rgba(179,38,30,0.16)',
    ring: 'rgba(255,255,255,0.8)', ringInk: 'rgba(22,25,29,0.6)', ringSelected: 'rgba(22,25,29,0.85)',
    labelBox: 'rgba(255,255,255,0.88)',
  },
  dark: {
    seed: '#ececea', risk: '#ff5c5c', exchange: '#2fd3a2', inferred: '#e0a44a',
    service: '#4a5057', flagged: '#e0a44a', node: '#5b6167',
    link: 'rgba(236,236,234,0.13)', linkPath: '#2fd3a2', linkFlagged: '#e0a44a',
    text: '#ececea', dim: '#9a9fa6', background: '#111316',
    haloExchange: 'rgba(47,211,162,0.18)', haloRisk: 'rgba(255,92,92,0.2)',
    ring: 'rgba(17,19,22,0.9)', ringInk: 'rgba(236,236,234,0.6)', ringSelected: 'rgba(236,236,234,0.9)',
    labelBox: 'rgba(17,19,22,0.85)',
  },
}
let COLORS = PALETTES[currentTheme()]

// Bubble sizing. Area is proportional to value, not radius -- a wallet that
// moved 100x more than another should look 100x bigger by area, which is what
// the eye actually compares. Radius therefore scales with the square root.
const MIN_RADIUS = 3.2
const MAX_RADIUS = 22
// Addresses the user came to find never shrink below this however little value
// passed through them. This covers the risk hits too, not just the seed and the
// exchanges: a sanctioned wallet that moved dust is still the most important
// bubble on the canvas, and sizing it by value alone buries it.
const FLOOR_RADIUS = 8
const ANSWER_ROLES = new Set(['seed', 'exchange', 'inferred', 'risk'])

// How far a non-highlighted element fades when something is highlighted.
const DIMMED_ALPHA = 0.12

// Padding around a bubble's clickable area, in SCREEN pixels.
//
// This matters more than it looks. The padding used to be a flat value added
// to the radius, which is in *graph* units -- so it shrank along with
// everything else as the camera pulled back. A 125-node trace frames at
// roughly 0.3x, which left an ordinary 3.2-radius bubble with about two pixels
// of hittable area, while the seed and the exchanges kept FLOOR_RADIUS and
// stayed easy to hit. The graph read as though only some bubbles were
// interactive. Dividing by the live zoom holds the padding constant on screen
// at every framing, so every bubble is reachable however far out you are.
const HIT_PAD = 9
// Same reasoning for edges, kept smaller so a link never steals the pointer
// from a bubble sitting on top of it.
const LINK_HIT_PAD = 4

const PATTERN_NAME = { peel_chain: 'Peel chain', amount_split: 'Amount split' }
const RISK_NAME = { sanctioned: 'Sanctioned entity', mixer: 'Mixer', stolen: 'Stolen funds' }
const ROLE_NAME = {
  seed: 'Reported address',
  risk: 'Sanctioned / mixer / stolen funds',
  exchange: 'Labelled exchange wallet',
  inferred: 'Probable deposit address (inferred)',
  service: 'Service contract or router, not expanded',
  flagged: 'Flagged by a pattern',
  node: 'Traced address',
}

function roleOf(node) {
  if (node.is_seed) return 'seed'
  if (node.risk_category) return 'risk'
  if (node.exchange && !node.inferred_exchange) return 'exchange'
  if (node.inferred_exchange) return 'inferred'
  if (node.is_router || node.is_service_contract) return 'service'
  if (node.flags?.length) return 'flagged'
  return 'node'
}

/** Value that passed through an address, in the chain's native unit. */
function flowOf(node) {
  return Math.max(node.total_in_native || 0, node.total_out_native || 0)
}

const short = (a) => `${a.slice(0, 6)}…${a.slice(-4)}`
const idOf = (end) => (typeof end === 'object' ? end.id : end)

const num = (value) =>
  value >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : Number((value || 0).toFixed(6)).toString()

const when = (seconds) =>
  seconds ? new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ') : ''

// Tooltip content is injected as HTML by react-force-graph, and some of these
// values (labels, entity names) originate outside this codebase, so escape.
const esc = (value) =>
  String(value ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

const rows = (pairs) =>
  pairs
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `<div class="r"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span></div>`)
    .join('')

/** Everything known about an address, without having to click it. */
function nodeTooltip(node, unit) {
  const role = roleOf(node)
  const suffix = unit ? ` ${unit}` : ''
  const body = rows([
    ['Exchange', node.inferred_exchange ? `${node.inferred_exchange} (inferred)` : node.exchange],
    ['Wallet', node.label && node.label !== node.exchange ? node.label : null],
    ['Router', node.router],
    ['Not expanded', node.is_service_contract ? 'contract paying out to many addresses' : null],
    ['Excluded by time rule', node.excluded_by_time ? `${node.excluded_by_time} earlier transfers` : null],
    ['Listed as', node.risk_entity],
    ['Category', node.risk_category ? RISK_NAME[node.risk_category] ?? node.risk_category : null],
    ['Depth', `${node.depth} hop${node.depth === 1 ? '' : 's'} from seed`],
    ['Received', `${num(node.total_in_native)}${suffix}`],
    ['Sent', `${num(node.total_out_native)}${suffix}`],
    ['Transfers', node.activity_count],
  ])
  const flags = node.flags?.length
    ? `<div class="tags">${node.flags
        .map((f) => `<span>${esc(PATTERN_NAME[f] ?? f)}</span>`)
        .join('')}</div>`
    : ''
  return `<div class="gt">
    <div class="gt-head" style="color:${COLORS[role]}">${esc(ROLE_NAME[role])}</div>
    <div class="gt-addr">${esc(node.address)}</div>
    ${body}${flags}
    <div class="gt-foot">Click to keep this highlighted</div>
  </div>`
}

/** What actually moved along an edge. */
function linkTooltip(link, unit) {
  const suffix = unit ? ` ${unit}` : ''
  const body = rows([
    ['Value', `${num(link.value_native)}${suffix}`],
    ['Transfers', link.tx_count],
    ['First', when(link.first_seen)],
    ['Last', when(link.last_seen)],
  ])
  const flags = link.flags?.length
    ? `<div class="tags">${link.flags
        .map((f) => `<span>${esc(PATTERN_NAME[f] ?? f)}</span>`)
        .join('')}</div>`
    : ''
  return `<div class="gt">
    <div class="gt-head" style="color:${COLORS.text}">Transfer</div>
    <div class="gt-addr">${esc(short(idOf(link.source)))} → ${esc(short(idOf(link.target)))}</div>
    ${body}${flags}
  </div>`
}

export default function GraphView({ data, tracePath, onSelect, selected, unit = '' }) {
  const containerRef = useRef(null)
  const graphRef = useRef(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  // The canvas painter reads COLORS on every frame; swap the palette and
  // force a repaint when the skin flips.
  const [theme, setTheme] = useState(currentTheme())
  useEffect(() => {
    const onChange = (e) => { COLORS = PALETTES[e.detail] ?? PALETTES.dark; setTheme(e.detail) }
    window.addEventListener('themechange', onChange)
    return () => window.removeEventListener('themechange', onChange)
  }, [])
  // Highlight state lives in refs, not React state, and the canvas callbacks
  // read it at draw time. react-force-graph holds on to the callback closures
  // it was given, so a value captured from render scope goes stale and the
  // canvas keeps drawing the highlight that was current when it bound them --
  // which is to say, none. A ref is read live on every frame, so it cannot go
  // stale. The canvas already repaints continuously, so no re-render is needed
  // to show a change.
  const hoverRef = useRef(null)
  const hoverLinkRef = useRef(null)
  const selectedRef = useRef(null)
  const focusRef = useRef({ id: null, set: null })
  const neighboursRef = useRef(new Map())
  // The live camera scale, for anything that has to be sized in screen pixels
  // rather than graph units. Read on every pointer-area repaint, so it is a ref
  // for the same staleness reason as the highlight state above.
  const zoomRef = useRef(1)
  // Bumped whenever a node is pinned or released, purely so the control bar
  // re-renders with a current count. The pin itself lives on the node object,
  // because that is what the physics simulation reads.
  const [pinTick, setPinTick] = useState(0)

  // Selection works whether or not a parent asks to own it. Left uncontrolled,
  // a click still pins the highlight -- which is the whole point of clicking,
  // and used to do nothing at all on the trace screen because no handler was
  // passed down.
  const [ownSelected, setOwnSelected] = useState(null)
  const controlled = selected !== undefined
  const activeSelected = controlled ? selected : ownSelected

  const labelBoxes = useRef([])

  // Size the canvas to its container.
  useEffect(() => {
    const element = containerRef.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize({ width, height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // Addresses on the seed -> exchange path, so those links can be emphasised.
  const pathEdges = useMemo(() => {
    const set = new Set()
    for (let i = 0; i < (tracePath?.length ?? 0) - 1; i += 1) {
      set.add(`${tracePath[i].address}>${tracePath[i + 1].address}`)
    }
    return set
  }, [tracePath])

  // react-force-graph mutates the objects it is given (it writes x/y onto
  // them), so hand it fresh copies whenever the data changes.
  const graphData = useMemo(() => {
    if (!data) return { nodes: [], links: [] }
    return {
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.edges.map((e) => ({ ...e, source: e.source, target: e.target })),
    }
  }, [data])

  // Who is connected to whom, in both directions. Used to highlight an
  // address's immediate counterparties when it is hovered or selected --
  // on a 100+ node graph that is the difference between a hairball and a
  // readable answer to "who did this wallet actually pay?".
  const neighbours = useMemo(() => {
    const map = new Map()
    const link = (a, b) => {
      if (!map.has(a)) map.set(a, new Set())
      map.get(a).add(b)
    }
    for (const edge of graphData.links) {
      const s = idOf(edge.source)
      const t = idOf(edge.target)
      link(s, t)
      link(t, s)
    }
    return map
  }, [graphData])

  const maxFlow = useMemo(
    () => Math.max(...graphData.nodes.map(flowOf), 0.000001),
    [graphData],
  )

  const radiusOf = useCallback(
    (node) => {
      const scaled =
        MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(flowOf(node) / maxFlow)
      if (ANSWER_ROLES.has(roleOf(node))) return Math.max(scaled, FLOOR_RADIUS)
      return scaled
    },
    [maxFlow],
  )

  // Physics. Collision is what produces the packed-bubble look: without it,
  // large bubbles sit on top of each other and the sizing is unreadable.
  useEffect(() => {
    const fg = graphRef.current
    if (!fg || graphData.nodes.length === 0) return
    fg.d3Force('collide', forceCollide((node) => radiusOf(node) + 2.5).iterations(2))
    // Repulsion scales with bubble size so a big bubble clears room for itself
    // instead of swallowing its neighbours.
    fg.d3Force('charge')?.strength((node) => -18 - 3.2 * radiusOf(node))
    fg.d3Force('link')?.distance((link) => 24 + radiusOf(link.source) + radiusOf(link.target))
    fg.d3ReheatSimulation()
  }, [graphData, radiusOf])

  // Frame the whole graph once its layout has settled.
  //
  // This is fussier than it looks. Fitting on a fixed timer framed a graph
  // that collision was still expanding and cropped the outer bubbles; fitting
  // only on engine-stop missed graphs whose simulation settled before the
  // nodes had usable coordinates, leaving the camera pointed at nothing and
  // the canvas apparently empty. So: attempt a fit, verify it had a real
  // bounding box to work with, and keep retrying briefly until it does.
  // Whichever trigger succeeds first wins, and the ref makes it once-per-trace
  // regardless of which callback closure react-force-graph is holding.
  const needsFit = useRef(false)

  const fitToView = useCallback(() => {
    const fg = graphRef.current
    if (!fg) return false
    // A degenerate box means the nodes have no positions yet -- fitting to it
    // would zoom the camera somewhere the graph is not.
    const bbox = fg.getGraphBbox?.()
    if (bbox) {
      const width = bbox.x[1] - bbox.x[0]
      const height = bbox.y[1] - bbox.y[0]
      if (!Number.isFinite(width) || !Number.isFinite(height) || (width === 0 && height === 0)) {
        return false
      }
    }
    fg.zoomToFit(500, 70)
    return true
  }, [])

  useEffect(() => {
    if (graphData.nodes.length === 0) return undefined
    needsFit.current = true
    const timers = [300, 700, 1200, 2000, 3000].map((delay) =>
      setTimeout(() => {
        if (needsFit.current && fitToView()) needsFit.current = false
      }, delay),
    )
    return () => timers.forEach(clearTimeout)
  }, [graphData, fitToView])

  const handleEngineStop = useCallback(() => {
    if (needsFit.current && fitToView()) needsFit.current = false
  }, [fitToView])

  const maxValue = useMemo(
    () => Math.max(...graphData.links.map((l) => l.value_native || 0), 0.000001),
    [graphData],
  )

  useEffect(() => { neighboursRef.current = neighbours }, [neighbours])

  // What is currently emphasised: the address itself plus everything it traded
  // with. Hover is transient and wins while it lasts; a click persists so the
  // user can study a neighbourhood without holding the mouse still.
  const applyFocus = useCallback((id) => {
    if (!id) {
      focusRef.current = { id: null, set: null }
      return
    }
    const set = new Set([id])
    for (const n of neighboursRef.current.get(id) ?? []) set.add(n)
    focusRef.current = { id, set }
  }, [])

  // Hovering an edge lights up just its two ends, which is the question an
  // edge actually asks: who paid whom. No single node owns the focus here, so
  // neither end gets the active ring.
  const resolveFocus = useCallback(() => {
    const node = hoverRef.current
    if (node) {
      applyFocus(node)
      return
    }
    const link = hoverLinkRef.current
    if (link) {
      focusRef.current = {
        id: null,
        set: new Set([idOf(link.source), idOf(link.target)]),
      }
      return
    }
    applyFocus(selectedRef.current)
  }, [applyFocus])

  // A selection made elsewhere (or cleared on a new trace) has to reach the
  // renderer too.
  useEffect(() => {
    selectedRef.current = activeSelected ?? null
    resolveFocus()
  }, [activeSelected, resolveFocus])

  const handleHover = useCallback(
    (node) => {
      hoverRef.current = node?.id ?? null
      // Cursor feedback is mutated directly rather than held in state: this
      // fires on every pointer move across the canvas, and a re-render per
      // move would cost far more than it is worth.
      if (containerRef.current) {
        containerRef.current.style.cursor = node ? 'pointer' : 'default'
      }
      resolveFocus()
    },
    [resolveFocus],
  )

  const handleLinkHover = useCallback(
    (link) => {
      hoverLinkRef.current = link ?? null
      resolveFocus()
    },
    [resolveFocus],
  )

  const isFaded = (id) => {
    const { set } = focusRef.current
    return !!set && !set.has(id)
  }

  // -- interaction -------------------------------------------------------
  const handleSelect = useCallback(
    (node) => {
      // Clicking the selected bubble again releases it, so the graph can be
      // returned to its unfocused state without hunting for empty background.
      if (!controlled) {
        setOwnSelected((current) => (node && current === node.id ? null : node?.id ?? null))
      }
      onSelect?.(node)
    },
    [controlled, onSelect],
  )

  // Dragging pins. A bubble the user has deliberately moved should stay where
  // they put it -- otherwise the layout springs back and the arrangement they
  // were building is lost.
  const handleDragEnd = useCallback((node) => {
    node.fx = node.x
    node.fy = node.y
    node.pinned = true
    setPinTick((t) => t + 1)
  }, [])

  const releaseNode = useCallback((node) => {
    node.fx = undefined
    node.fy = undefined
    node.pinned = false
    setPinTick((t) => t + 1)
    graphRef.current?.d3ReheatSimulation()
  }, [])

  const releaseAll = useCallback(() => {
    for (const node of graphData.nodes) {
      node.fx = undefined
      node.fy = undefined
      node.pinned = false
    }
    setPinTick((t) => t + 1)
    graphRef.current?.d3ReheatSimulation()
  }, [graphData])

  const pinnedCount = useMemo(
    () => graphData.nodes.filter((n) => n.pinned).length,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graphData, pinTick],
  )

  const zoomBy = useCallback((factor) => {
    const fg = graphRef.current
    if (!fg) return
    fg.zoom(fg.zoom() * factor, 250)
  }, [])

  // The addresses worth jumping straight to: the cash-out points and the risk
  // hits. Finding these by hovering a 125-bubble canvas is the slow path even
  // once every bubble is hittable, so list them and fly the camera there.
  // Risk leads for the same reason it owns red -- an outside designation
  // outranks the tool's own matches -- then shallowest, then largest.
  const landmarks = useMemo(() => {
    const rank = { risk: 0, exchange: 1, inferred: 2 }
    return graphData.nodes
      .filter((n) => rank[roleOf(n)] !== undefined)
      .sort((a, b) =>
        rank[roleOf(a)] - rank[roleOf(b)] ||
        (a.depth ?? 0) - (b.depth ?? 0) ||
        flowOf(b) - flowOf(a))
  }, [graphData])

  const flyTo = useCallback(
    (node) => {
      const fg = graphRef.current
      // The live copy carries the simulation's coordinates; the list item is a
      // reference to that same object, but guard anyway for a node the layout
      // has not positioned yet.
      if (fg && Number.isFinite(node.x) && Number.isFinite(node.y)) {
        fg.centerAt(node.x, node.y, 600)
        fg.zoom(Math.max(fg.zoom(), 2.4), 600)
      }
      if (!controlled) setOwnSelected(node.id)
      onSelect?.(node)
    },
    [controlled, onSelect],
  )

  // Escape drops the selection, f re-frames. Ignored while a form field has
  // focus so the search box on the surrounding page keeps working.
  useEffect(() => {
    const onKey = (event) => {
      const tag = event.target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || event.target?.isContentEditable) return
      if (event.key === 'Escape') handleSelect(null)
      else if (event.key === 'f' || event.key === 'F') fitToView()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [handleSelect, fitToView])

  function drawNode(node, ctx, globalScale) {
    const role = roleOf(node)
    const radius = radiusOf(node)
    const isActive = focusRef.current.id === node.id
    const isSelected = selectedRef.current === node.id
    const faded = isFaded(node.id)

    ctx.save()
    if (faded) ctx.globalAlpha = DIMMED_ALPHA

    // Halo on the exchange node so the answer is findable at a glance.
    if (role === 'exchange') {
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius + 4.5, 0, 2 * Math.PI)
      ctx.fillStyle = COLORS.haloExchange
      ctx.fill()
    }
    if (role === 'risk') {
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius + 4.5, 0, 2 * Math.PI)
      ctx.fillStyle = COLORS.haloRisk
      ctx.fill()
    }

    ctx.beginPath()
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI)
    ctx.fillStyle = COLORS[role]
    ctx.fill()

    if (isActive) {
      ctx.strokeStyle = COLORS.text
      ctx.lineWidth = 1.6 / globalScale
      ctx.stroke()
    } else if (role === 'exchange' || role === 'seed' || role === 'inferred') {
      ctx.strokeStyle = COLORS.ring
      ctx.lineWidth = 1.2 / globalScale
      ctx.stroke()
    }

    // A risk ring is drawn on any listed address, including the reported one.
    // Role alone would hide the fact that the victim's own reported address is
    // on a sanctions list, which is precisely the case worth seeing.
    if (node.risk_category) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius + 2.2, 0, 2 * Math.PI)
      ctx.strokeStyle = COLORS.risk
      ctx.lineWidth = 1.6 / globalScale
      ctx.stroke()
    }

    // A pinned bubble is marked, so a deliberate arrangement is readable as
    // deliberate rather than looking like the layout failed to settle.
    if (node.pinned) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius + 2.6, 0, 2 * Math.PI)
      ctx.strokeStyle = COLORS.ringInk
      ctx.lineWidth = 1 / globalScale
      ctx.setLineDash([3 / globalScale, 2.5 / globalScale])
      ctx.stroke()
      ctx.setLineDash([])
    }

    // A held selection reads differently from a passing hover: the outer ring
    // says "this stays until you dismiss it".
    if (isSelected) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius + 5.5, 0, 2 * Math.PI)
      ctx.strokeStyle = COLORS.ringSelected
      ctx.lineWidth = 1.4 / globalScale
      ctx.stroke()
    }

    // --- labels -----------------------------------------------------------
    // Important nodes are always labelled. Ordinary ones appear only once the
    // user has zoomed in far enough for them to be readable, which keeps a
    // large graph legible instead of a wall of text. Anything inside the
    // current focus is labelled too: naming the counterparties is most of the
    // value of focusing an address in the first place.
    const inFocus = !!focusRef.current.set && focusRef.current.set.has(node.id)
    const important = ANSWER_ROLES.has(role) || isActive || inFocus
    if ((!important && globalScale < 1.6) || faded) {
      ctx.restore()
      return
    }

    const text = role === 'risk' && node.risk_entity ? node.risk_entity
      : role === 'exchange' && node.label ? node.label
      : role === 'inferred' ? `${node.inferred_exchange}? ${short(node.address)}`
      : short(node.address)
    const fontSize = Math.max(10 / globalScale, 2.2)
    ctx.font = `${important ? 500 : 400} ${fontSize}px 'IBM Plex Mono', ui-monospace, monospace`

    const width = ctx.measureText(text).width
    const padX = 3 / globalScale
    const padY = 1.6 / globalScale
    const x = node.x
    const y = node.y + radius + fontSize * 0.9
    const box = {
      x0: x - width / 2 - padX,
      y0: y - fontSize / 2 - padY,
      x1: x + width / 2 + padX,
      y1: y + fontSize / 2 + padY,
    }

    // Collision test against labels already drawn this frame.
    const collides = labelBoxes.current.some(
      (b) => box.x0 < b.x1 && box.x1 > b.x0 && box.y0 < b.y1 && box.y1 > b.y0,
    )
    // An important label always wins its space; an ordinary one yields.
    if (collides && !important) {
      ctx.restore()
      return
    }
    labelBoxes.current.push(box)

    ctx.fillStyle = COLORS.labelBox
    ctx.fillRect(box.x0, box.y0, box.x1 - box.x0, box.y1 - box.y0)

    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = important ? COLORS[role] : COLORS.dim
    ctx.fillText(text, x, y)
    ctx.restore()
  }

  const hasData = graphData.nodes.length > 0

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%' }}>
      {hasData && size.width > 0 && (
        <ForceGraph2D
          key={theme}
          ref={graphRef}
          width={size.width}
          height={size.height}
          graphData={graphData}
          backgroundColor={COLORS.background}
          nodeRelSize={4}
          nodeCanvasObject={drawNode}
          nodeLabel={(node) => nodeTooltip(node, unit)}
          nodePointerAreaPaint={(node, color, ctx) => {
            ctx.fillStyle = color
            ctx.beginPath()
            ctx.arc(node.x, node.y, radiusOf(node) + HIT_PAD / zoomRef.current, 0, 2 * Math.PI)
            ctx.fill()
          }}
          onZoom={({ k }) => { zoomRef.current = k || 1 }}
          onRenderFramePre={() => { labelBoxes.current = [] }}
          onNodeHover={handleHover}
          onNodeClick={handleSelect}
          onNodeRightClick={(node) => releaseNode(node)}
          onBackgroundClick={() => handleSelect(null)}
          enableNodeDrag
          onNodeDragEnd={handleDragEnd}
          linkLabel={(link) => linkTooltip(link, unit)}
          onLinkHover={handleLinkHover}
          linkPointerAreaPaint={(link, color, ctx) => {
            const s = link.source
            const t = link.target
            if (!s || !t || !Number.isFinite(s.x) || !Number.isFinite(t.x)) return
            ctx.strokeStyle = color
            ctx.lineWidth = LINK_HIT_PAD / zoomRef.current
            ctx.beginPath()
            ctx.moveTo(s.x, s.y)
            ctx.lineTo(t.x, t.y)
            ctx.stroke()
          }}
          linkColor={(link) => {
            const key = `${idOf(link.source)}>${idOf(link.target)}`
            if (hoverLinkRef.current === link) return COLORS.text
            if (isFaded(idOf(link.source)) || isFaded(idOf(link.target))) {
              return 'rgba(22,25,29,0.05)'
            }
            if (pathEdges.has(key)) return COLORS.linkPath
            if (link.flags?.length) return COLORS.linkFlagged
            return COLORS.link
          }}
          linkWidth={(link) => {
            const key = `${idOf(link.source)}>${idOf(link.target)}`
            const base = 0.6 + 2.2 * Math.sqrt((link.value_native || 0) / maxValue)
            if (hoverLinkRef.current === link) return base + 1.6
            return pathEdges.has(key) ? base + 1 : base
          }}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          linkDirectionalArrowColor={() => COLORS.dim}
          // Animated particles only along the attributed path: a direct visual
          // answer to "where did the money go".
          linkDirectionalParticles={(link) => {
            const key = `${idOf(link.source)}>${idOf(link.target)}`
            return pathEdges.has(key) ? 3 : 0
          }}
          linkDirectionalParticleWidth={2.4}
          linkDirectionalParticleColor={() => COLORS.exchange}
          onEngineStop={handleEngineStop}
          cooldownTicks={200}
          d3VelocityDecay={0.28}
        />
      )}

      {hasData && (
        <>
          <div className="graph-stats">
            {graphData.nodes.length} addresses · {graphData.links.length} transfers
          </div>

          <div className="graph-controls">
            <button onClick={() => zoomBy(1.4)} title="Zoom in" aria-label="Zoom in">+</button>
            <button onClick={() => zoomBy(1 / 1.4)} title="Zoom out" aria-label="Zoom out">&minus;</button>
            <button
              onClick={fitToView}
              title="Fit the whole graph in view (f)"
            >
              Fit
            </button>
            <button
              onClick={releaseAll}
              disabled={pinnedCount === 0}
              title="Release every pinned bubble and let the layout settle again"
            >
              Release {pinnedCount > 0 ? `(${pinnedCount})` : ''}
            </button>
          </div>

          <div className="graph-hint">
            Hover any bubble for detail · click to keep it highlighted · drag to
            pin · right-click to release · scroll to zoom · bubble size = value
            moved
          </div>

          {landmarks.length > 0 && (
            <div className="jump-panel">
              <span className="micro">Jump to</span>
              {landmarks.map((node) => {
                const role = roleOf(node)
                return (
                  <button
                    key={node.id}
                    className={activeSelected === node.id ? 'active' : ''}
                    onClick={() => flyTo(node)}
                    title={node.address}
                  >
                    <span className="swatch" style={{ background: COLORS[role] }} />
                    <span className="name">
                      {role === 'risk'
                        ? node.risk_entity ?? RISK_NAME[node.risk_category] ?? 'Listed'
                        : role === 'inferred' ? `${node.inferred_exchange} deposit (inferred)`
                        : node.label ?? node.exchange}
                    </span>
                    <span className="addr">{short(node.address)}</span>
                  </button>
                )
              })}
            </div>
          )}

          <div className="legend">
            <div className="item">
              <span className="swatch" style={{ background: COLORS.seed }} />
              Reported address
            </div>
            <div className="item">
              <span className="swatch" style={{ background: COLORS.risk }} />
              Sanctioned / mixer
            </div>
            <div className="item">
              <span className="swatch" style={{ background: COLORS.exchange }} />
              Labelled exchange wallet
            </div>
            <div className="item">
              <span className="swatch" style={{ background: COLORS.inferred }} />
              Probable deposit address (inferred)
            </div>
            <div className="item">
              <span className="swatch" style={{ background: COLORS.service }} />
              Service contract / router, not expanded
            </div>
            <div className="item">
              <span className="swatch" style={{ background: COLORS.flagged }} />
              Flagged by a pattern
            </div>
            <div className="item">
              <span className="swatch" style={{ background: COLORS.node }} />
              Traced address
            </div>
          </div>
        </>
      )}
    </div>
  )
}
