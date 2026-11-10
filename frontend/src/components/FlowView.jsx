import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useMedia } from '../phone'
import { plain } from '../text'
import RoleSwatch from './RoleSwatch'

// The money flow as a layered diagram: one column per hop, the reported
// address at one end and whatever it reached at the other, every arrow
// pointing the way the money moved -- left to right, always. No physics:
// the same graph draws the same picture every time, and a judge at the back
// of the room can read it in one glance because the attributed path is the
// one bold green line -- the money under investigation, on its way to the
// exchange -- and everything else is thin.
//
// Colour carries meaning exactly as elsewhere: green for a labelled exchange,
// an inferred deposit and the traced route, nothing else. Red is risk: solid
// with a halo for a confirmed hit (sanctions, mixer, frozen...), faded with a
// dashed ring for a possible flag (a pattern fired; not confirmed). A gambling
// platform's wallet is grey with a dashed halo (an attribution, not a
// designation). The key draws them the same way (RoleSwatch). Dashed means
// unconfirmed, so the traced funds stay solid even where a pattern fired on them.
//
// In motion: the columns arrive one after another on first sight, the lines
// drawing on as their far end appears, then a light runs the traced funds.
// "Pause motion" stops the light and the sweeps; reduced motion draws the
// final picture at once and runs nothing.

const ROLE_NAME = {
  seed: 'Reported address',
  risk: 'Sanctioned / mixer / frozen (confirmed)',
  gambling: 'Gambling platform wallet',
  exchange: 'Labelled exchange wallet',
  inferred: 'Probable deposit address (inferred)',
  service: 'Service contract or router, not expanded',
  flagged: 'Possible flag · pattern (not confirmed)',
  node: 'Traced address',
}
const ROLE_VAR = {
  seed: 'var(--text)', risk: 'var(--risk)', gambling: 'var(--text-2)', exchange: 'var(--go)', inferred: 'var(--go-soft)',
  service: 'var(--line-strong)', flagged: 'var(--risk)', node: 'var(--text-3)',
}
const RADIUS = { seed: 7, risk: 6.5, gambling: 6.5, exchange: 6.5, inferred: 6, service: 4, flagged: 4.5, node: 3.5 }

function roleOf(node) {
  if (node.is_seed) return 'seed'
  if (node.risk_category === 'gambling') return 'gambling'
  if (node.risk_category) return 'risk'
  if (node.exchange && !node.inferred_exchange) return 'exchange'
  if (node.inferred_exchange) return 'inferred'
  if (node.is_router || node.is_service_contract) return 'service'
  if (node.flags?.length) return 'flagged'
  return 'node'
}

const short = (a) => `${a.slice(0, 6)}…${a.slice(-4)}`
const short4 = (a) => `${a.slice(0, 4)}…${a.slice(-4)}`
const num = (value) =>
  value >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : Number((value || 0).toFixed(6)).toString()
const when = (seconds) =>
  seconds ? new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ') : ''

const RISK_WORD = { sanctioned: 'sanctioned', seized: 'seizure order', mixer: 'mixer', frozen: 'frozen by issuer', stolen: 'stolen funds', reported: 'TronScan warning', gambling: 'gambling platform', poisoning: 'address poisoning', scam: 'reported scam', laundering: 'laundering' }

/** What a node is called on the canvas: the label if it has one, else nothing. */
function captionOf(node, role) {
  if (role === 'seed') return node.risk_category ? `Reported · ${RISK_WORD[node.risk_category] ?? 'flagged'}` : 'Reported'
  if (role === 'exchange') return node.label ?? node.exchange
  if (role === 'inferred') return `probable ${node.inferred_exchange} deposit`
  if (role === 'risk') return node.risk_entity ?? node.risk_label ?? RISK_WORD[node.risk_category] ?? 'flagged'
  if (role === 'gambling') return node.risk_entity ?? 'gambling platform'
  if (role === 'service') return node.router ?? node.label ?? null
  return null
}

/** A transfer as a gentle S from the sender's dot to the receiver's. */
function curve(a, b) {
  const x1 = a.x + a.r; const x2 = b.x - b.r
  const dx = Math.max(24, (x2 - x1) * 0.45)
  return `M${x1},${a.y} C${x1 + dx},${a.y} ${x2 - dx},${b.y} ${x2},${b.y}`
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
        onPath: onPath.has(n.id), caption: plain(captionOf(n, role)), column: c,
      })
    })
    // Adjacent addresses with the same caption would print it on top of
    // itself when the rows are tighter than a line of text; say it once, with
    // a count, on the first of the run.
    if (rowGap < 24) {
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
        edge: e, a, b, d: curve(a, b),
        onPath: pathEdges.has(`${e.source}>${e.target}`),
        pathIndex: pathEdges.get(`${e.source}>${e.target}`),
        width: 0.8 + 2.2 * Math.sqrt((e.value_native || 0) / maxValue),
        flagged: Boolean(e.flags?.length),
        // A line draws on as its far end's column arrives.
        column: Math.max(a.column, b.column),
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

// The stage is a fixed-height window onto the diagram. A big trace is drawn
// at full size and scaled to fit; the viewer zooms into a region for detail.
const STAGE_HEIGHT = 560
const ZOOM_MIN = 0.15
const ZOOM_MAX = 4
// Room above the diagram for the map's controls, so they never sit on a
// column heading. On a phone the controls are 44 px tall.
const TOP_RESERVE = 40
const TOP_RESERVE_COMPACT = 62

const COMET_HEAD = 0.28   // fraction of a segment the light covers
const COMET_SEGMENT_MS = 700
const COMET_PAUSE_MS = 900

// The entrance (the motion system): a column every 450 ms, its dots popping
// top to bottom 40 ms apart (spread over at most 360 ms, so a tall column
// keeps time), its lines drawing on in 500 ms as their far end arrives.
export const COLUMN_STEP_MS = 450
const NODE_STAGGER_MS = 40
const STAGGER_SPAN_MS = 360
const POP_MS = 450
const DRAW_MS = 500
const REVEAL_TAIL_MS = Math.max(STAGGER_SPAN_MS + POP_MS, DRAW_MS)
const WAITING = -1
const DONE = Number.POSITIVE_INFINITY

// "Show only flags": everything but the flags, the confirmed risk wallets and
// the reported address recedes this far.
const FLAGS_NODE_ALPHA = 0.12
const FLAGS_LINK_ALPHA = 0.08
// A phone tap selects the nearest dot within this many screen pixels: rows
// sit close there, so a big hit circle would pick a neighbour.
const TAP_REACH = 22
// A held selection sweeps at most this many of its transfers.
const HELD_SWEEPS = 12
// Captions in one column closer than this many lines collide.
const CAPTION_GAP_LINES = 1.2

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

/**
 * The hop map.
 *
 * selected / onSelect: the selected address. With onSelect the selection is
 * the caller's (shared with the bubble map): a click copies the address and
 * calls onSelect(id); a second click, a click on the empty stage or Escape on
 * the focused stage calls onSelect(null). Without it the map keeps its own.
 * flagsOnly: fade everything but possible flags, confirmed risk and the seed.
 * compact: the phone layout (tap to select, no tooltip, 44 px controls).
 * active: false while the map is hidden; the moving light stops.
 */
export default function FlowView({
  data, tracePath, unit = '', direction = 'outgoing',
  selected = null, onSelect, flagsOnly = false, compact = false, active = true,
}) {
  const box = useRef(null)
  const svg = useRef(null)
  const cometRefs = useRef(new Map()) // pathIndex -> [glow, core] elements
  const uid = `flow${useId().replace(/[^\w-]/g, '')}`
  const reduced = useMedia(REDUCED_MOTION)
  const [width, setWidth] = useState(900)
  const [hover, setHover] = useState(null) // { kind: 'node'|'link', item, x, y }
  const [copied, setCopied] = useState(null)
  const [ownSelected, setOwnSelected] = useState(null)
  const [motionPaused, setMotionPaused] = useState(false)
  const [said, setSaid] = useState('')
  // How far the entrance has got: the last column shown, WAITING before it
  // starts, DONE once everything is in place.
  const [stage, setStage] = useState(() => (reduced ? DONE : WAITING))
  const [run, setRun] = useState(0)

  useEffect(() => {
    const el = box.current
    if (!el) return undefined
    // A page that hides the map (display: none) collapses it to nothing; keep
    // the last real width, so the layout, the fit and the officer's zoom and
    // pan survive the map being hidden and shown again.
    const ro = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width
      if (w > 0) setWidth(Math.max(320, w))
    })
    ro.observe(el)
    if (el.clientWidth > 0) setWidth(Math.max(320, el.clientWidth))
    return () => ro.disconnect()
  }, [])

  // Layout in world units, then the scale that fits it in the stage under
  // the controls. The world is laid out wider when it will be scaled down,
  // so at fit it fills the stage edge to edge rather than shrinking into the middle.
  const reserve = compact ? TOP_RESERVE_COMPACT : TOP_RESERVE
  const { placed, links, height, columns, fit } = useMemo(() => {
    const first = layout(data, tracePath, direction, width)
    const k = Math.min(1, (STAGE_HEIGHT - reserve) / first.height)
    const world = k < 1 ? layout(data, tracePath, direction, width / k) : first
    return { ...world, fit: { k, tx: 0, ty: reserve } }
  }, [data, tracePath, direction, width, reserve])
  const maxColumn = Math.max(0, ...columns.map((c) => c.column))
  const stageHeight = Math.min(STAGE_HEIGHT, Math.round(height * fit.k) + reserve)

  const [view, setView] = useState(fit)
  useEffect(() => { setView(fit) }, [fit])
  const drag = useRef(null)
  const justDragged = useRef(false)

  // Each dot's delay inside its column, top to bottom.
  const delays = useMemo(() => {
    const byColumn = new Map()
    placed.forEach((p) => {
      if (!byColumn.has(p.column)) byColumn.set(p.column, [])
      byColumn.get(p.column).push(p)
    })
    const out = new Map()
    byColumn.forEach((list) => {
      const step = list.length > 1 ? Math.min(NODE_STAGGER_MS, STAGGER_SPAN_MS / (list.length - 1)) : 0
      list.sort((a, b) => a.y - b.y).forEach((p, i) => out.set(p.node.id, Math.round(i * step)))
    })
    return out
  }, [placed])

  // The entrance plays once, the first time the map is shown, and again on
  // Replay. Hiding and showing the map (active) does not replay it.
  const played = useRef(null)
  useEffect(() => {
    if (reduced) { setStage(DONE); return undefined }
    if (!active || played.current === run) return undefined
    played.current = run
    setStage(0)
    let finished = false
    const timers = []
    for (let c = 1; c <= maxColumn; c += 1) timers.push(setTimeout(() => setStage(c), c * COLUMN_STEP_MS))
    timers.push(setTimeout(() => { finished = true; setStage(DONE) }, maxColumn * COLUMN_STEP_MS + REVEAL_TAIL_MS))
    return () => {
      timers.forEach(clearTimeout)
      // Interrupted (hidden mid-way): play it from the start next time.
      if (!finished) played.current = null
    }
  }, [run, active, reduced, maxColumn])
  const revealing = stage !== DONE
  const replay = () => { setStage(WAITING); setRun((r) => r + 1) }

  // Hidden: nothing is under the pointer any more.
  useEffect(() => {
    if (!active) { setHover(null); drag.current = null }
  }, [active])

  const zoomBy = (factor, cx = width / 2, cy = stageHeight / 2) => {
    setView((v) => {
      const k = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, v.k * factor))
      // Keep the point under the cursor where it is.
      const ratio = k / v.k
      return { k, tx: cx - (cx - v.tx) * ratio, ty: cy - (cy - v.ty) * ratio }
    })
  }
  // The wheel handler must not be passive, or the page scrolls as well.
  useEffect(() => {
    const el = box.current
    if (!el) return undefined
    const onWheel = (e) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      zoomBy(Math.exp(-e.deltaY * 0.0015), e.clientX - rect.left, e.clientY - rect.top)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [width, stageHeight])

  const onMouseDown = (e) => {
    if (e.button !== 0) return
    justDragged.current = false
    drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty, moved: false }
  }
  const onMouseMove = (e) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x; const dy = e.clientY - d.y
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true
    if (d.moved) setView((v) => ({ ...v, tx: d.tx + dx, ty: d.ty + dy }))
  }
  const endDrag = () => {
    if (drag.current?.moved) justDragged.current = true
    drag.current = null
  }
  // A click that ends a drag is not a click.
  const wasDrag = () => {
    const was = justDragged.current
    justDragged.current = false
    return was
  }
  // Captions and dots stay legible when the world is scaled down.
  const counter = Math.min(1 / view.k, 2.2)
  const textCounter = Math.min(1 / view.k, 3.2)

  // The selection: the caller's when it listens, else this map's own.
  const controlled = typeof onSelect === 'function'
  const selectedId = (controlled ? selected : ownSelected) || null
  const selectedPlace = selectedId ? placed.get(selectedId) ?? null : null
  const select = (id) => {
    // A caller that owns the selection announces it (once, for both maps).
    if (controlled) { onSelect(id); return }
    setSaid(id ? `Selected ${short(id)}` : 'Selection cleared')
    setOwnSelected(id)
  }

  // Hovering an address lights its own transfers; everything else recedes.
  // Without a hover the selected address stays lit the same way.
  const focus = useMemo(
    () => hover ?? (selectedPlace ? { kind: 'node', item: selectedPlace } : null),
    [hover, selectedPlace],
  )
  const lit = useMemo(() => {
    if (!focus) return null
    if (focus.kind === 'node') {
      const id = focus.item.node.id
      const s = new Set([id])
      links.forEach((l) => { if (l.a.node.id === id || l.b.node.id === id) { s.add(l.a.node.id); s.add(l.b.node.id) } })
      return s
    }
    return new Set([focus.item.a.node.id, focus.item.b.node.id])
  }, [focus, links])
  // A selection held without a hover lights its busiest transfers only (the
  // route first), slowly and without the blurred glow: it can stay on for
  // minutes, so it must not repaint dozens of lines.
  const held = useMemo(() => {
    if (hover || !selectedPlace) return null
    const id = selectedPlace.node.id
    return new Set(
      links
        .filter((l) => l.a.node.id === id || l.b.node.id === id)
        .sort((p, q) => Number(q.onPath) - Number(p.onPath) || (q.edge.value_native || 0) - (p.edge.value_native || 0))
        .slice(0, HELD_SWEEPS),
    )
  }, [hover, selectedPlace, links])

  // "Show only flags": what stays, and the counts the chip states.
  const flags = useMemo(() => {
    const keep = new Set()
    let possible = 0; let confirmed = 0
    data.nodes.forEach((n) => {
      const role = roleOf(n)
      if (role === 'flagged') possible += 1
      if (n.risk_category && n.risk_category !== 'gambling') confirmed += 1
      if (role === 'flagged' || role === 'risk' || n.is_seed) keep.add(n.id)
    })
    return { keep, possible, confirmed }
  }, [data])

  // Where each caption goes. By default beside the dot in the first and last
  // columns and everywhere on a phone, above it in the middle columns. Where
  // captions in a column would print over each other (rows closer than a
  // line of text), the next one moves to the other side of its dot; where
  // neither side is free, a run of possible-flag captions folds into one,
  // with a count, on its first row (each address is still a tap or a hover away).
  const captions = useMemo(() => {
    const out = new Map()
    const byColumn = new Map()
    placed.forEach((p) => {
      let text = p.caption
      let flag = false
      if (!text && flagsOnly && p.role === 'flagged') {
        text = compact ? short4(p.node.id) : `possible flag · ${short4(p.node.id)}`
        flag = true
      }
      if (!text) return
      if (!byColumn.has(p.column)) byColumn.set(p.column, [])
      byColumn.get(p.column).push({ p, text, flag })
    })
    const gap = CAPTION_GAP_LINES * 11 * textCounter // in world units
    byColumn.forEach((list, column) => {
      const first = column === 0; const last = column === maxColumn
      const sides = first ? ['start'] : last ? ['end'] : ['start', 'end']
      const preferred = first || (compact && !last) ? 'start' : last ? 'end' : 'above'
      // The y of the lowest caption so far on each side of the dots. One
      // above a dot is centred on it, so it takes both sides.
      const lastY = { start: -Infinity, end: -Infinity }
      let head = null // the open run of folded possible flags
      list.sort((a, b) => a.p.y - b.p.y).forEach((c) => {
        const { p } = c
        const aboveY = p.y - (p.r + 5) * counter
        const clearOf = (side) => (side === 'above'
          ? aboveY - Math.max(lastY.start, lastY.end) >= gap
          : p.y - lastY[side] >= gap)
        let side = [preferred, ...sides].find(clearOf) ?? null
        if (!side && c.flag && head) {
          head.count += 1
          return
        }
        side ??= preferred
        if (side === 'above') { lastY.start = aboveY; lastY.end = aboveY } else lastY[side] = p.y
        const entry = { ...c, side, count: 1 }
        out.set(p.node.id, entry)
        head = c.flag ? entry : null
      })
    })
    out.forEach((c) => {
      if (c.count > 1) c.text = `possible flags ×${c.count}`
    })
    return out
  }, [placed, flagsOnly, compact, maxColumn, counter, textCounter])

  const flagsSeen = useRef(flagsOnly)
  useEffect(() => {
    if (flagsSeen.current === flagsOnly) return
    flagsSeen.current = flagsOnly
    setSaid(flagsOnly ? 'Showing only possible flags and confirmed risk wallets' : 'Showing every address')
  }, [flagsOnly])

  // Moving light, on or off: off while paused, hidden, entering or reduced.
  const moving = active && !motionPaused && !reduced && !revealing

  // The traced funds as one light running the whole chain, hop by hop, with
  // a breath at the end before it runs again. Paused while something is
  // hovered: the animation then belongs to what is under the pointer.
  const chainLength = (tracePath?.length ?? 1) - 1
  const cometOn = moving && chainLength >= 1 && !hover
  useEffect(() => {
    const refs = cometRefs.current
    if (!cometOn) {
      refs.forEach((els) => els.forEach((el) => { if (el) el.style.opacity = 0 }))
      return undefined
    }
    const cycle = chainLength * COMET_SEGMENT_MS + COMET_PAUSE_MS
    let frame = 0
    const start = performance.now()
    const ease = (u) => u * u * (3 - 2 * u) // smoothstep
    const tick = (now) => {
      const t = Math.max(0, now - start) % cycle
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
  }, [chainLength, cometOn, links])

  const copy = (address) => {
    navigator.clipboard?.writeText(address).then(() => {
      setCopied(address); setTimeout(() => setCopied(null), 1100)
    }, () => {})
  }
  // A click copies the address and selects it; a second click clears it.
  const pick = (id) => {
    copy(id)
    select(selectedId === id ? null : id)
  }

  const place = (event) => {
    const rect = box.current.getBoundingClientRect()
    return { x: event.clientX - rect.left, y: event.clientY - rect.top }
  }

  // Phone taps: the nearest shown address within TAP_REACH screen pixels.
  const nearest = (event) => {
    const rect = svg.current.getBoundingClientRect()
    const sx = width / (rect.width || width)
    const sy = stageHeight / (rect.height || stageHeight)
    const wx = ((event.clientX - rect.left) * sx - view.tx) / view.k
    const wy = ((event.clientY - rect.top) * sy - view.ty) / view.k
    const reach = (TAP_REACH * sx) / view.k
    let best = null; let bestDistance = Infinity
    placed.forEach((p) => {
      if (p.column > stage) return
      const d = Math.hypot(p.x - wx, p.y - wy)
      if (d <= reach && d < bestDistance) { best = p; bestDistance = d }
    })
    return best
  }
  const onStageClick = (e) => {
    if (wasDrag()) return
    if (compact) {
      const near = nearest(e)
      if (near) { pick(near.node.id); return }
    }
    if (selectedId) select(null)
  }
  const onNodeClick = (e, p) => {
    // On the phone the stage resolves the tap to the nearest dot.
    if (compact) return
    e.stopPropagation()
    if (wasDrag()) return
    pick(p.node.id)
  }
  // Keyboard selection: ] and [ step through the shown addresses, column by
  // column, top to bottom (only the kept ones while only flags show), and
  // bring the one selected into view.
  const order = useMemo(
    () => [...placed.values()]
      .filter((p) => !flagsOnly || flags.keep.has(p.node.id))
      .sort((a, b) => a.column - b.column || a.y - b.y),
    [placed, flagsOnly, flags],
  )
  const step = (by) => {
    const shown = order.filter((p) => p.column <= stage)
    if (!shown.length) return
    const at = shown.indexOf(selectedPlace)
    const next = at < 0 ? (by > 0 ? 0 : shown.length - 1) : (at + by + shown.length) % shown.length
    const p = shown[next]
    select(p.node.id)
    setView((v) => {
      const sx = p.x * v.k + v.tx; const sy = p.y * v.k + v.ty
      const margin = 40
      if (sx >= margin && sx <= width - margin && sy >= reserve && sy <= stageHeight - margin) return v
      return { ...v, tx: width / 2 - p.x * v.k, ty: (reserve + stageHeight) / 2 - p.y * v.k }
    })
  }
  const onKey = (e) => {
    if (e.target !== e.currentTarget) return
    const pan = (dx, dy) => setView((v) => ({ ...v, tx: v.tx + dx, ty: v.ty + dy }))
    switch (e.key) {
      case ']': step(1); break
      case '[': step(-1); break
      case '+': case '=': zoomBy(1.4); break
      case '-': case '_': zoomBy(1 / 1.4); break
      case '0': setView(fit); break
      case 'ArrowLeft': pan(60, 0); break
      case 'ArrowRight': pan(-60, 0); break
      case 'ArrowUp': pan(0, 60); break
      case 'ArrowDown': pan(0, -60); break
      case 'Escape': setHover(null); if (selectedId) select(null); break
      default: return
    }
    e.preventDefault()
  }

  const alpha = (id) => (lit && !lit.has(id) ? 0.18 : 1)
  // What the entrance does to an element of a column: hidden until its
  // column arrives, animated in while the entrance runs, plain after.
  const entering = (column) => (column > stage ? ' pre' : revealing ? ' in' : '')
  const narrow = compact || width < 640
  const hoverOn = !compact && active

  return (
    <div className={`flow${drag.current?.moved ? ' dragging' : ''}${compact ? ' compact' : narrow ? ' narrow' : ''}`} ref={box}>
      <div
        className="flow-stage" tabIndex={0} role="group" onKeyDown={onKey}
        aria-label={`Hop map. Drag to pan, scroll to zoom. ${compact ? 'Tap' : 'Click'} an address to select it and copy it. Keys: plus and minus zoom, arrows pan, 0 fits the whole trace, right and left square brackets select the next and previous address, Escape clears the selection.`}
      >
      <svg
        ref={svg}
        width={width} height={stageHeight} viewBox={`0 0 ${width} ${stageHeight}`} role="img" aria-label="Money flow by hop"
        onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={endDrag} onMouseLeave={endDrag} onClick={onStageClick}
      >
        <defs>
          <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0 0.5 L8 4 L0 7.5 z" style={{ fill: 'var(--faint)' }} />
          </marker>
          <marker id="arrow-path" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M0 0.5 L8 4 L0 7.5 z" style={{ fill: 'var(--go)' }} />
          </marker>
          {/* A dashed line cannot draw itself on with its own dashes: a mask does it. */}
          {revealing && links.map((l, i) => (l.flagged && !l.onPath && l.column <= stage ? (
            <mask key={i} id={`${uid}-m${i}`} maskUnits="userSpaceOnUse" x="-100000" y="-100000" width="200000" height="200000">
              <path d={l.d} pathLength="1" className="flow-draw-mask" />
            </mask>
          ) : null))}
        </defs>

        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>
        {columns.map((h) => (
          <text key={h.column} className={`flow-col${entering(h.column)}`} x={h.x} y={16} textAnchor="middle" style={{ fontSize: 10.5 * textCounter }}>{h.text}</text>
        ))}

        {links.map((l, i) => {
          const d = l.d
          const faded = lit && !(lit.has(l.a.node.id) && lit.has(l.b.node.id))
          // Under the pointer (or on the selected address) the movement
          // belongs to that line, or every transfer of that address.
          // Otherwise the traced funds run on their own (the comet below,
          // driven per frame).
          const swept = moving && focus && (
            held ? held.has(l)
              : focus.kind === 'link' ? focus.item === l
                : (focus.item.node.id === l.a.node.id || focus.item.node.id === l.b.node.id)
          )
          const tone = l.onPath ? ' on-path' : l.flagged ? ' flagged' : ''
          const key = `${l.edge.source}>${l.edge.target}`
          const shown = l.column <= stage
          const drawing = shown && revealing
          const masked = drawing && l.flagged && !l.onPath
          // The selected address's own transfers stay readable as well.
          const kept = (flags.keep.has(l.a.node.id) && flags.keep.has(l.b.node.id))
            || (selectedId != null && (l.a.node.id === selectedId || l.b.node.id === selectedId))
          const enter = hoverOn ? (e) => setHover({ kind: 'link', item: l, ...place(e) }) : undefined
          const move = hoverOn ? (e) => setHover((h) => (h ? { ...h, ...place(e) } : h)) : undefined
          const leave = hoverOn ? () => setHover(null) : undefined
          return (
            <g
              key={key} className={`flow-lg${shown ? '' : ' pre'}`} data-edge={key}
              style={flagsOnly && !kept ? { opacity: FLAGS_LINK_ALPHA } : undefined}
              mask={masked ? `url(#${uid}-m${i})` : undefined}
            >
              <path
                d={d}
                className={`flow-link${tone}${drawing && !masked ? ' drawing' : ''}`}
                pathLength={drawing && !masked ? 1 : undefined}
                strokeWidth={l.onPath ? Math.max(2.4, l.width) : l.width}
                vectorEffect="non-scaling-stroke"
                style={{ opacity: faded ? 0.08 : undefined }}
                markerEnd={l.onPath ? 'url(#arrow-path)' : 'url(#arrow)'}
              />
              {l.onPath && !swept && (
                <>
                  <path
                    d={d} pathLength="1" className="flow-comet glow on-path" vectorEffect="non-scaling-stroke"
                    strokeDasharray={`${COMET_HEAD} 2`} style={{ opacity: 0 }}
                    ref={(el) => { const pair = cometRefs.current.get(l.pathIndex) ?? [null, null]; pair[0] = el; cometRefs.current.set(l.pathIndex, pair) }}
                  />
                  <path
                    d={d} pathLength="1" className="flow-comet core on-path" vectorEffect="non-scaling-stroke"
                    strokeDasharray={`${COMET_HEAD} 2`} style={{ opacity: 0 }}
                    ref={(el) => { const pair = cometRefs.current.get(l.pathIndex) ?? [null, null]; pair[1] = el; cometRefs.current.set(l.pathIndex, pair) }}
                  />
                </>
              )}
              {swept && (held ? (
                <path d={d} pathLength="1" className={`flow-sweep core held${tone}`} vectorEffect="non-scaling-stroke" />
              ) : (
                <>
                  <path d={d} pathLength="1" className={`flow-sweep glow${tone}`} vectorEffect="non-scaling-stroke" />
                  <path d={d} pathLength="1" className={`flow-sweep core${tone}`} vectorEffect="non-scaling-stroke" />
                </>
              ))}
              {/* A wide invisible stroke so a thin line is easy to hover. */}
              <path d={d} className="flow-hit" vectorEffect="non-scaling-stroke" onMouseEnter={enter} onMouseMove={move} onMouseLeave={leave} />
            </g>
          )
        })}

        {[...placed.values()].map((p) => {
          const id = p.node.id
          const enter = entering(p.column)
          const delay = enter === ' in' ? { animationDelay: `${delays.get(id) ?? 0}ms` } : undefined
          const isSelected = selectedPlace === p
          // The selected address stays plain to see, whatever the filter.
          const kept = flags.keep.has(id) || isSelected
          const colour = p.node.risk_category === 'gambling' ? ROLE_VAR.gambling : p.node.risk_category ? ROLE_VAR.risk : ROLE_VAR[p.role]
          const halo = p.role === 'exchange' || p.role === 'risk' || p.role === 'gambling' || Boolean(p.node.risk_category)
          // Outside the halo or the green path ring when there is one.
          const ringGap = halo || p.onPath ? 9 : 5
          // While only flags show, every possible flag carries its address
          // (placed clear of its neighbours: see captions above).
          const cap = captions.get(id)
          const caption = cap?.text ?? null
          const side = cap?.side ?? 'above'
          const capX = side === 'start' ? p.x + (p.r + 6) * counter : side === 'end' ? p.x - (p.r + 6) * counter : p.x
          const capY = side === 'above' ? p.y - (p.r + 5) * counter : p.y
          // Phone: the reported wallet's long caption would run into hop 1, so
          // it takes two short lines.
          const cut = compact && p.column === 0 && caption ? caption.indexOf(' · ') : -1
          return (
            <g
              key={id} data-address={id}
              className={`flow-node role-${p.role}${p.onPath ? ' on-path' : ''}${isSelected ? ' selected' : ''}`}
              style={{ opacity: alpha(id) * (flagsOnly && !kept ? FLAGS_NODE_ALPHA : 1) }}
              onMouseEnter={hoverOn ? (e) => setHover({ kind: 'node', item: p, ...place(e) }) : undefined}
              onMouseMove={hoverOn ? (e) => setHover((h) => (h ? { ...h, ...place(e) } : h)) : undefined}
              onMouseLeave={hoverOn ? () => setHover(null) : undefined}
              onClick={(e) => onNodeClick(e, p)}
            >
              <g className={`flow-pop${enter}`} style={delay}>
                {halo && <circle cx={p.x} cy={p.y} r={(p.r + 5) * counter} className="halo" vectorEffect="non-scaling-stroke" style={p.node.risk_category ? { stroke: p.node.risk_category === 'gambling' ? ROLE_VAR.gambling : ROLE_VAR.risk } : undefined} />}
                <circle cx={p.x} cy={p.y} r={(p.r + 6) * counter} fill="transparent" />
                <circle cx={p.x} cy={p.y} r={p.r * counter} className="dot" fill={colour} vectorEffect="non-scaling-stroke" />
                {isSelected && <circle cx={p.x} cy={p.y} r={(p.r + ringGap) * counter} className="sel-ring" vectorEffect="non-scaling-stroke" />}
              </g>
              {caption && (
                <text
                  className={`flow-cap${enter}`}
                  style={{ fontSize: 11 * textCounter, ...delay }}
                  x={capX}
                  y={capY}
                  textAnchor={side === 'above' ? 'middle' : side}
                  dominantBaseline={side === 'above' ? 'auto' : 'middle'}
                  fill={colour}
                >
                  {cut > 0 ? (
                    <>
                      <tspan x={capX} y={p.y - 6.5 * textCounter}>{caption.slice(0, cut)}</tspan>
                      <tspan x={capX} y={p.y + 6.5 * textCounter}>{caption.slice(cut + 3)}</tspan>
                    </>
                  ) : caption}
                </text>
              )}
            </g>
          )
        })}
        </g>
      </svg>

      <div className="flow-controls" role="group" aria-label="Map controls">
        <button type="button" onClick={() => zoomBy(1.4)} title="Zoom in">+</button>
        <button type="button" onClick={() => zoomBy(1 / 1.4)} title="Zoom out">−</button>
        <button type="button" onClick={() => setView(fit)} title="Fit the whole trace on screen">Fit</button>
        <button
          type="button" aria-pressed={motionPaused} aria-label="Pause motion" disabled={reduced}
          title={reduced ? 'Motion is reduced on this device' : 'Stop the moving light on the traced funds'}
          onClick={() => setMotionPaused((v) => !v)}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" className="ico"><path d="M4.5 3v8M9.5 3v8" /></svg>
          {!narrow && <span>Pause motion</span>}
        </button>
        <button
          type="button" aria-label="Replay the entrance" disabled={reduced}
          title={reduced ? 'Motion is reduced on this device' : 'Play the column-by-column entrance again'}
          onClick={replay}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" className="ico"><path d="M3.2 7.6a4 4 0 1 0 1.1-3.6" /><path d="M3.6 1.6v2.8h2.8" /></svg>
          {!narrow && <span>Replay</span>}
        </button>
      </div>
      {flagsOnly ? (
        <div className="flow-chip">
          <RoleSwatch role="flagged" color={ROLE_VAR.flagged} />
          <span>Showing {flags.possible} possible flag{flags.possible === 1 ? '' : 's'} · {flags.confirmed} confirmed</span>
        </div>
      ) : !compact && fit.k < 1 && view.k === fit.k && (
        <div className="flow-hint">Scaled to fit · scroll to zoom · drag to pan</div>
      )}
      </div>
      <div className="visually-hidden" aria-live="polite">{said}</div>

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
              <div className="gt-foot">{selectedId === hover.item.node.id ? 'selected · click again to clear the selection' : 'click to select and copy the address'}</div>
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
        {['seed', 'exchange', 'inferred', 'risk', 'gambling', 'flagged', 'service'].map((r) => (
          <span key={r}><RoleSwatch role={r} color={ROLE_VAR[r]} />{ROLE_NAME[r].replace(' (inferred)', '').replace(', not expanded', '')}</span>
        ))}
        <span><i className="line" />the traced funds (attributed path)</span>
      </div>
    </div>
  )
}
