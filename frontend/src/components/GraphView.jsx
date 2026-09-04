import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { forceCollide } from 'd3-force-3d'

// Kept in sync with the custom properties in styles.css. The canvas paints in
// JS and cannot read CSS variables, so these values are duplicated here on
// purpose — change one, change both.
//
// Only two things carry colour: a confirmed exchange (accent green) and a
// fired pattern (amber). The reported address is bright neutral rather than
// coloured, and ordinary traced addresses are dim, so the eye lands on the
// answer instead of on decoration.
const COLORS = {
  seed: '#e6e8ea',
  exchange: '#2fd3a2',
  flagged: '#e0a44a',
  node: '#5b6167',
  link: 'rgba(255,255,255,0.10)',
  linkPath: '#2fd3a2',
  linkFlagged: '#e0a44a',
  text: '#e6e8ea',
  dim: '#6b7075',
}

// Bubble sizing. Area is proportional to value, not radius -- a wallet that
// moved 100x more than another should look 100x bigger by area, which is what
// the eye actually compares. Radius therefore scales with the square root.
const MIN_RADIUS = 3.2
const MAX_RADIUS = 22
// The seed and the matched exchange are the two addresses the user came to
// find, so they never shrink below this however little value passed through.
const FLOOR_RADIUS = 8

// How far a non-highlighted element fades when something is highlighted.
const DIMMED_ALPHA = 0.12

function roleOf(node) {
  if (node.is_seed) return 'seed'
  if (node.exchange) return 'exchange'
  if (node.flags?.length) return 'flagged'
  return 'node'
}

/** Value that passed through an address, in the chain's native unit. */
function flowOf(node) {
  return Math.max(node.total_in_native || 0, node.total_out_native || 0)
}

const short = (a) => `${a.slice(0, 6)}…${a.slice(-4)}`
const idOf = (end) => (typeof end === 'object' ? end.id : end)

export default function GraphView({ data, tracePath, onSelect, selected }) {
  const containerRef = useRef(null)
  const graphRef = useRef(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  // Highlight state lives in refs, not React state, and the canvas callbacks
  // read it at draw time. react-force-graph holds on to the callback closures
  // it was given, so a value captured from render scope goes stale and the
  // canvas keeps drawing the highlight that was current when it bound them --
  // which is to say, none. A ref is read live on every frame, so it cannot go
  // stale. The canvas already repaints continuously, so no re-render is needed
  // to show a change.
  const hoverRef = useRef(null)
  const selectedRef = useRef(null)
  const focusRef = useRef({ id: null, set: null })
  const neighboursRef = useRef(new Map())
  // Bumped whenever a node is pinned or released, purely so the control bar
  // re-renders with a current count. The pin itself lives on the node object,
  // because that is what the physics simulation reads.
  const [pinTick, setPinTick] = useState(0)

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
      const role = roleOf(node)
      if (role === 'seed' || role === 'exchange') return Math.max(scaled, FLOOR_RADIUS)
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

  // A selection made elsewhere (or cleared on a new trace) has to reach the
  // renderer too.
  useEffect(() => {
    selectedRef.current = selected ?? null
    applyFocus(hoverRef.current ?? selected ?? null)
  }, [selected, applyFocus])

  const handleHover = useCallback(
    (node) => {
      hoverRef.current = node?.id ?? null
      applyFocus(hoverRef.current ?? selectedRef.current)
    },
    [applyFocus],
  )

  const isFaded = (id) => {
    const { set } = focusRef.current
    return !!set && !set.has(id)
  }

  // -- interaction -------------------------------------------------------
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

  function drawNode(node, ctx, globalScale) {
    const role = roleOf(node)
    const radius = radiusOf(node)
    const isActive = focusRef.current.id === node.id
    const faded = isFaded(node.id)

    ctx.save()
    if (faded) ctx.globalAlpha = DIMMED_ALPHA

    // Halo on the exchange node so the answer is findable at a glance.
    if (role === 'exchange') {
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius + 4.5, 0, 2 * Math.PI)
      ctx.fillStyle = 'rgba(47,211,162,0.14)'
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
    } else if (role === 'exchange' || role === 'seed') {
      ctx.strokeStyle = 'rgba(255,255,255,0.55)'
      ctx.lineWidth = 1.2 / globalScale
      ctx.stroke()
    }

    // A pinned bubble is marked, so a deliberate arrangement is readable as
    // deliberate rather than looking like the layout failed to settle.
    if (node.pinned) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius + 2.6, 0, 2 * Math.PI)
      ctx.strokeStyle = 'rgba(230,237,243,0.75)'
      ctx.lineWidth = 1 / globalScale
      ctx.setLineDash([3 / globalScale, 2.5 / globalScale])
      ctx.stroke()
      ctx.setLineDash([])
    }

    // --- labels -----------------------------------------------------------
    // Important nodes are always labelled. Ordinary ones appear only once the
    // user has zoomed in far enough for them to be readable, which keeps a
    // large graph legible instead of a wall of text.
    const important = role === 'seed' || role === 'exchange' || isActive
    if ((!important && globalScale < 1.6) || faded) {
      ctx.restore()
      return
    }

    const text = role === 'exchange' && node.label ? node.label : short(node.address)
    const fontSize = Math.max(10 / globalScale, 2.2)
    ctx.font = `${important ? 500 : 400} ${fontSize}px 'JetBrains Mono', ui-monospace, monospace`

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

    ctx.fillStyle = 'rgba(10,11,13,0.85)'
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
          ref={graphRef}
          width={size.width}
          height={size.height}
          graphData={graphData}
          backgroundColor="#0a0b0d"
          nodeRelSize={4}
          nodeCanvasObject={drawNode}
          nodePointerAreaPaint={(node, color, ctx) => {
            ctx.fillStyle = color
            ctx.beginPath()
            ctx.arc(node.x, node.y, radiusOf(node) + 3, 0, 2 * Math.PI)
            ctx.fill()
          }}
          onRenderFramePre={() => { labelBoxes.current = [] }}
          onNodeHover={handleHover}
          onNodeClick={(node) => onSelect?.(node)}
          onNodeRightClick={(node) => releaseNode(node)}
          onBackgroundClick={() => onSelect?.(null)}
          enableNodeDrag
          onNodeDragEnd={handleDragEnd}
          linkColor={(link) => {
            const key = `${idOf(link.source)}>${idOf(link.target)}`
            if (isFaded(idOf(link.source)) || isFaded(idOf(link.target))) {
              return 'rgba(255,255,255,0.035)'
            }
            if (pathEdges.has(key)) return COLORS.linkPath
            if (link.flags?.length) return COLORS.linkFlagged
            return COLORS.link
          }}
          linkWidth={(link) => {
            const key = `${idOf(link.source)}>${idOf(link.target)}`
            const base = 0.6 + 2.2 * Math.sqrt((link.value_native || 0) / maxValue)
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
            <button onClick={() => zoomBy(1.4)} title="Zoom in">+</button>
            <button onClick={() => zoomBy(1 / 1.4)} title="Zoom out">−</button>
            <button
              onClick={fitToView}
              title="Fit the whole graph in view"
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
            Drag a bubble to pin it · right-click to release · hover to isolate its
            transfers · scroll to zoom · bubble size = value moved
          </div>

          <div className="legend">
            <div className="item">
              <span className="swatch" style={{ background: COLORS.seed }} />
              Reported address
            </div>
            <div className="item">
              <span className="swatch" style={{ background: COLORS.exchange }} />
              Matched exchange
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
