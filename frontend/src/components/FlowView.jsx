import { useEffect, useMemo, useRef, useState } from 'react'

// The money flow as a layered diagram: one column per hop, the reported
// address at one end and whatever it reached at the other, every arrow
// pointing the way the money moved -- left to right, always. No physics:
// the same graph draws the same picture every time, and a judge at the back
// of the room can read it in one glance because the attributed path is the
// one bold red line -- the money under investigation -- and everything else is thin.
//
// Colour carries meaning exactly as elsewhere: green for a labelled exchange,
// amber for an inference or a fired pattern, red for a sanctions or mixer hit.

const ROLE_NAME = {
  seed: 'Reported address',
  risk: 'Sanctioned / mixer',
  exchange: 'Labelled exchange wallet',
  inferred: 'Probable deposit address (inferred)',
  service: 'Service contract or router, not expanded',
  flagged: 'Flagged by a pattern',
  node: 'Traced address',
}
const ROLE_VAR = {
  seed: 'var(--ink)', risk: 'var(--red)', exchange: 'var(--green)', inferred: 'var(--amber)',
  service: 'var(--rule-strong)', flagged: 'var(--amber)', node: 'var(--faint)',
}
const RADIUS = { seed: 7, risk: 6.5, exchange: 6.5, inferred: 6, service: 4, flagged: 4.5, node: 3.5 }

function roleOf(node) {
  if (node.is_seed) return 'seed'
  if (node.risk_category) return 'risk'
  if (node.exchange && !node.inferred_exchange) return 'exchange'
  if (node.inferred_exchange) return 'inferred'
  if (node.is_router || node.is_service_contract) return 'service'
  if (node.flags?.length) return 'flagged'
  return 'node'
}

const short = (a) => `${a.slice(0, 6)}…${a.slice(-4)}`
const num = (value) =>
  value >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : Number((value || 0).toFixed(6)).toString()
const when = (seconds) =>
  seconds ? new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ') : ''

/** What a node is called on the canvas: the label if it has one, else nothing. */
function captionOf(node, role) {
  if (role === 'seed') return node.risk_category ? 'Reported · sanctioned' : 'Reported'
  if (role === 'exchange') return node.label ?? node.exchange
  if (role === 'inferred') return `probable ${node.inferred_exchange} deposit`
  if (role === 'risk') return node.risk_entity ?? node.risk_label ?? 'sanctioned'
  if (role === 'service') return node.router ?? node.label ?? null
  return null
}

const PAD_X = 70
const PAD_TOP = 34
const PAD_BOTTOM = 18
const ROW_GAP_MAX = 30
const ROW_GAP_MIN = 9

/**
 * Column per depth; rows ordered by the average row of their neighbours one
 * column nearer the seed, so an edge is drawn as close to horizontal as the
 * graph allows and the picture reads as a flow rather than a tangle.
 */
function layout(data, tracePath, direction, width) {
  const nodes = data.nodes
  const edges = data.edges
  if (!nodes.length) return { placed: new Map(), links: [], height: 200, columns: [] }

  const maxDepth = Math.max(...nodes.map((n) => n.depth ?? 0))
  const columnOf = (d) => (direction === 'incoming' ? maxDepth - d : d)

  const onPath = new Set()
  const pathEdges = new Map() // edge key -> position along the chain
  ;(tracePath ?? []).forEach((step, i, arr) => {
    onPath.add(step.address)
    if (i < arr.length - 1) pathEdges.set(`${step.address}>${arr[i + 1].address}`, i)
  })

  // Neighbours one hop nearer the seed, whichever way the edge points.
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const nearer = new Map(nodes.map((n) => [n.id, []]))
  edges.forEach((e) => {
    const s = byId.get(e.source); const t = byId.get(e.target)
    if (!s || !t) return
    if ((s.depth ?? 0) < (t.depth ?? 0)) nearer.get(t.id).push(s.id)
    else if ((t.depth ?? 0) < (s.depth ?? 0)) nearer.get(s.id).push(t.id)
  })

  const columns = []
  for (let d = 0; d <= maxDepth; d += 1) columns.push(nodes.filter((n) => (n.depth ?? 0) === d))

  const row = new Map()
  columns.forEach((col, d) => {
    if (d === 0) {
      col.forEach((n, i) => row.set(n.id, i))
      return
    }
    const key = (n) => {
      const ns = nearer.get(n.id).filter((id) => row.has(id))
      const bary = ns.length ? ns.reduce((s, id) => s + row.get(id), 0) / ns.length : Number.MAX_SAFE_INTEGER
      return [bary, onPath.has(n.id) ? 0 : 1, -(n.total_in_native || 0)]
    }
    col
      .map((n) => ({ n, k: key(n) }))
      .sort((a, b) => a.k[0] - b.k[0] || a.k[1] - b.k[1] || a.k[2] - b.k[2])
      .forEach(({ n }, i) => row.set(n.id, i))
  })

  const tallest = Math.max(...columns.map((c) => c.length))
  const rowGap = Math.max(ROW_GAP_MIN, Math.min(ROW_GAP_MAX, 620 / Math.max(tallest, 1)))
  const height = Math.max(300, Math.round(PAD_TOP + PAD_BOTTOM + tallest * rowGap))
  const colWidth = (width - PAD_X * 2) / Math.max(maxDepth, 1)

  const placed = new Map()
  columns.forEach((col, d) => {
    const c = columnOf(d)
    const x = maxDepth === 0 ? width / 2 : PAD_X + c * colWidth
    const block = col.length * rowGap
    const top = PAD_TOP + ((height - PAD_TOP - PAD_BOTTOM) - block) / 2
    const ordered = [...col].sort((a, b) => row.get(a.id) - row.get(b.id))
    ordered.forEach((n) => {
      const role = roleOf(n)
      placed.set(n.id, {
        node: n, role, x, y: top + (row.get(n.id) + 0.5) * rowGap,
        r: onPath.has(n.id) ? Math.max(RADIUS[role], 5) : RADIUS[role],
        onPath: onPath.has(n.id), caption: captionOf(n, role), column: c,
      })
    })
    // Adjacent addresses with the same caption would print it on top of
    // itself when the rows are tighter than a line of text; say it once, with
    // a count, on the first of the run.
    if (rowGap < 14) {
      let run = null
      ordered.forEach((n) => {
        const p = placed.get(n.id)
        if (run && p.caption && p.caption === run.caption) {
          run.count += 1
          p.caption = null
        } else {
          if (run && run.count > 1) run.first.caption = `${run.caption} ×${run.count}`
          run = p.caption ? { caption: p.caption, first: p, count: 1 } : null
        }
      })
      if (run && run.count > 1) run.first.caption = `${run.caption} ×${run.count}`
    }
  })

  const maxValue = Math.max(...edges.map((e) => e.value_native || 0), 1e-9)
  const links = edges
    .map((e) => {
      const a = placed.get(e.source); const b = placed.get(e.target)
      if (!a || !b) return null
      return {
        edge: e, a, b,
        onPath: pathEdges.has(`${e.source}>${e.target}`),
        pathIndex: pathEdges.get(`${e.source}>${e.target}`),
        width: 0.8 + 2.2 * Math.sqrt((e.value_native || 0) / maxValue),
        flagged: Boolean(e.flags?.length),
      }
    })
    .filter(Boolean)
    // Path last, so it is drawn on top.
    .sort((p, q) => Number(p.onPath) - Number(q.onPath))

  const headers = columns.map((_, d) => ({
    column: columnOf(d), text: d === 0 ? 'Reported' : `Hop ${d}`,
    x: maxDepth === 0 ? width / 2 : PAD_X + columnOf(d) * colWidth,
  }))
  return { placed, links, height, columns: headers, maxDepth, colWidth }
}

const COMET_HEAD = 0.28   // fraction of a segment the light covers
const COMET_SEGMENT_MS = 700
const COMET_PAUSE_MS = 900

export default function FlowView({ data, tracePath, unit = '', direction = 'outgoing' }) {
  const box = useRef(null)
  const cometRefs = useRef(new Map()) // pathIndex -> [glow, core] elements
  const [width, setWidth] = useState(900)
  const [hover, setHover] = useState(null) // { kind: 'node'|'link', item, x, y }
  const [copied, setCopied] = useState(null)

  useEffect(() => {
    const el = box.current
    if (!el) return undefined
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(320, entry.contentRect.width)))
    ro.observe(el)
    setWidth(Math.max(320, el.clientWidth))
    return () => ro.disconnect()
  }, [])

  const { placed, links, height, columns } = useMemo(
    () => layout(data, tracePath, direction, width), [data, tracePath, direction, width],
  )
  const maxColumn = Math.max(0, ...columns.map((c) => c.column))

  // Hovering an address lights its own transfers; everything else recedes.
  const lit = useMemo(() => {
    if (!hover) return null
    if (hover.kind === 'node') {
      const id = hover.item.node.id
      const s = new Set([id])
      links.forEach((l) => { if (l.a.node.id === id || l.b.node.id === id) { s.add(l.a.node.id); s.add(l.b.node.id) } })
      return s
    }
    return new Set([hover.item.a.node.id, hover.item.b.node.id])
  }, [hover, links])

  // The traced funds as one light running the whole chain, hop by hop, with
  // a breath at the end before it runs again. Paused while something is
  // hovered: the animation then belongs to what is under the pointer.
  const chainLength = (tracePath?.length ?? 1) - 1
  const paused = Boolean(hover)
  useEffect(() => {
    const refs = cometRefs.current
    if (chainLength < 1 || paused) {
      refs.forEach((els) => els.forEach((el) => { if (el) el.style.opacity = 0 }))
      return undefined
    }
    const cycle = chainLength * COMET_SEGMENT_MS + COMET_PAUSE_MS
    let frame = 0
    const start = performance.now()
    const ease = (u) => u * u * (3 - 2 * u) // smoothstep
    const tick = (now) => {
      const t = (now - start) % cycle
      const travelling = t < chainLength * COMET_SEGMENT_MS
      const c = travelling ? t / COMET_SEGMENT_MS : chainLength + 1
      const k = Math.floor(c)
      const u = travelling ? ease(c - k) : 0
      refs.forEach((els, i) => {
        // Head on segment k at u; the tail may still lie on segment k - 1.
        let offset = null
        if (i === k) offset = COMET_HEAD - u
        else if (i === k - 1 && u < COMET_HEAD) offset = COMET_HEAD - (1 + u)
        els.forEach((el) => {
          if (!el) return
          if (offset === null) { el.style.opacity = 0; return }
          el.style.opacity = 1
          el.setAttribute('stroke-dashoffset', String(offset))
        })
      })
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [chainLength, paused, links])

  const copy = (address) => {
    navigator.clipboard?.writeText(address).then(() => {
      setCopied(address); setTimeout(() => setCopied(null), 1100)
    }, () => {})
  }

  const place = (event) => {
    const rect = box.current.getBoundingClientRect()
    return { x: event.clientX - rect.left, y: event.clientY - rect.top }
  }

  const alpha = (id) => (lit && !lit.has(id) ? 0.18 : 1)

  return (
    <div className="flow" ref={box}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Money flow by hop">
        <defs>
          <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0 0.5 L8 4 L0 7.5 z" style={{ fill: 'var(--faint)' }} />
          </marker>
          <marker id="arrow-path" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M0 0.5 L8 4 L0 7.5 z" style={{ fill: 'var(--red)' }} />
          </marker>
        </defs>

        {columns.map((h) => (
          <text key={h.column} className="flow-col" x={h.x} y={16} textAnchor="middle">{h.text}</text>
        ))}

        {links.map((l) => {
          const x1 = l.a.x + l.a.r; const x2 = l.b.x - l.b.r
          const dx = Math.max(24, (x2 - x1) * 0.45)
          const d = `M${x1},${l.a.y} C${x1 + dx},${l.a.y} ${x2 - dx},${l.b.y} ${x2},${l.b.y}`
          const faded = lit && !(lit.has(l.a.node.id) && lit.has(l.b.node.id))
          // Under the pointer the movement belongs to what is hovered: that
          // line, or every transfer of that address. Otherwise the traced
          // funds run on their own (the comet below, driven per frame).
          const swept = hover && (
            hover.kind === 'link' ? hover.item === l
              : (hover.item.node.id === l.a.node.id || hover.item.node.id === l.b.node.id)
          )
          const tone = l.onPath ? ' on-path' : l.flagged ? ' flagged' : ''
          const key = `${l.edge.source}>${l.edge.target}`
          const enter = (e) => setHover({ kind: 'link', item: l, ...place(e) })
          const move = (e) => setHover((h) => (h ? { ...h, ...place(e) } : h))
          const leave = () => setHover(null)
          return (
            <g key={key}>
              <path
                d={d}
                className={`flow-link${l.onPath ? ' on-path' : ''}${l.flagged ? ' flagged' : ''}`}
                strokeWidth={l.onPath ? Math.max(2.4, l.width) : l.width}
                style={{ opacity: faded ? 0.08 : undefined }}
                markerEnd={l.onPath ? 'url(#arrow-path)' : 'url(#arrow)'}
              />
              {l.onPath && !swept && (
                <>
                  <path
                    d={d} pathLength="1" className="flow-comet glow on-path"
                    strokeDasharray={`${COMET_HEAD} 2`} style={{ opacity: 0 }}
                    ref={(el) => { const pair = cometRefs.current.get(l.pathIndex) ?? [null, null]; pair[0] = el; cometRefs.current.set(l.pathIndex, pair) }}
                  />
                  <path
                    d={d} pathLength="1" className="flow-comet core on-path"
                    strokeDasharray={`${COMET_HEAD} 2`} style={{ opacity: 0 }}
                    ref={(el) => { const pair = cometRefs.current.get(l.pathIndex) ?? [null, null]; pair[1] = el; cometRefs.current.set(l.pathIndex, pair) }}
                  />
                </>
              )}
              {swept && (
                <>
                  <path d={d} pathLength="1" className={`flow-sweep glow${tone}`} />
                  <path d={d} pathLength="1" className={`flow-sweep core${tone}`} />
                </>
              )}
              {/* A wide invisible stroke so a thin line is easy to hover. */}
              <path d={d} className="flow-hit" onMouseEnter={enter} onMouseMove={move} onMouseLeave={leave} />
            </g>
          )
        })}

        {[...placed.values()].map((p) => (
          <g
            key={p.node.id}
            className={`flow-node role-${p.role}${p.onPath ? ' on-path' : ''}`}
            style={{ opacity: alpha(p.node.id) }}
            onMouseEnter={(e) => setHover({ kind: 'node', item: p, ...place(e) })}
            onMouseMove={(e) => setHover((h) => (h ? { ...h, ...place(e) } : h))}
            onMouseLeave={() => setHover(null)}
            onClick={() => copy(p.node.id)}
          >
            {(p.role === 'exchange' || p.role === 'risk' || p.node.risk_category) && <circle cx={p.x} cy={p.y} r={p.r + 5} className="halo" style={p.node.risk_category ? { stroke: 'var(--red)' } : undefined} />}
            <circle cx={p.x} cy={p.y} r={p.r + 6} fill="transparent" />
            <circle cx={p.x} cy={p.y} r={p.r} fill={p.node.risk_category ? ROLE_VAR.risk : ROLE_VAR[p.role]} />
            {p.caption && (
              <text
                className="flow-cap"
                x={p.column === 0 ? p.x + p.r + 6 : p.column === maxColumn ? p.x - p.r - 6 : p.x}
                y={p.column === 0 || p.column === maxColumn ? p.y : p.y - p.r - 5}
                textAnchor={p.column === 0 ? 'start' : p.column === maxColumn ? 'end' : 'middle'}
                dominantBaseline={p.column === 0 || p.column === maxColumn ? 'middle' : 'auto'}
                fill={p.node.risk_category ? ROLE_VAR.risk : ROLE_VAR[p.role]}
              >{p.caption}</text>
            )}
          </g>
        ))}
      </svg>

      {hover && (
        <div className="flow-tip" style={{ left: Math.min(hover.x + 14, width - 300), top: hover.y + 14 }}>
          {hover.kind === 'node' ? (
            <>
              <div className="gt-head" style={{ color: ROLE_VAR[hover.item.role] }}>{ROLE_NAME[hover.item.role]}{hover.item.onPath ? ' · on the attributed path' : ''}</div>
              <div className="gt-addr">{copied === hover.item.node.id ? 'copied' : hover.item.node.id}</div>
              <div className="r"><span className="k">hop</span><span className="v">{hover.item.node.depth}</span></div>
              <div className="r"><span className="k">received</span><span className="v">{num(hover.item.node.total_in_native)} {unit}</span></div>
              <div className="r"><span className="k">sent on</span><span className="v">{num(hover.item.node.total_out_native)} {unit}</span></div>
              {hover.item.node.excluded_by_time > 0 && <div className="r"><span className="k">left out (before arrival)</span><span className="v">{hover.item.node.excluded_by_time}</span></div>}
              {hover.item.node.flags?.length > 0 && <div className="r"><span className="k">pattern</span><span className="v">{hover.item.node.flags.join(', ').replace(/_/g, ' ')}</span></div>}
              <div className="gt-foot">click to copy the address</div>
            </>
          ) : (
            <>
              <div className="gt-head">{hover.item.onPath ? 'On the attributed path' : 'Transfer'}</div>
              <div className="gt-addr">{short(hover.item.edge.source)} → {short(hover.item.edge.target)}</div>
              <div className="r"><span className="k">moved</span><span className="v">{num(hover.item.edge.value_native)} {unit}</span></div>
              <div className="r"><span className="k">transfers</span><span className="v">{hover.item.edge.tx_count}{hover.item.edge.internal_tx_count ? ` (${hover.item.edge.internal_tx_count} by contract call)` : ''}</span></div>
              {hover.item.edge.last_seen ? <div className="r"><span className="k">last</span><span className="v">{when(hover.item.edge.last_seen)}</span></div> : null}
              {hover.item.edge.swap && <div className="r"><span className="k">swap</span><span className="v">{hover.item.edge.swap.router_label}</span></div>}
            </>
          )}
        </div>
      )}

      <div className="flow-legend">
        {['seed', 'exchange', 'inferred', 'risk', 'flagged', 'service'].map((r) => (
          <span key={r}><i style={{ background: ROLE_VAR[r] }} />{ROLE_NAME[r].replace(' (inferred)', '').replace(', not expanded', '')}</span>
        ))}
        <span><i className="line" />the traced funds (attributed path)</span>
      </div>
    </div>
  )
}
