import { currentTheme } from '../theme'
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { plain } from '../text'
import { useMedia } from '../phone'
import { forceCollide } from 'd3-force-3d'
import RoleSwatch, { DASH, FADED, FADED_ROLES } from './RoleSwatch'
import { isConfirmedRisk } from './mapRoles'
import './GraphView.css'

// Kept in sync with the custom properties in styles.css. The canvas paints in
// JS and cannot read CSS variables, so these values are duplicated here on
// purpose — change one, change both.
//
// Two things carry colour: risk (red) and a confirmed exchange (green). A
// confirmed risk hit (sanctions, mixer, freeze...) is solid red with a halo.
// A possible flag -- a pattern such as a peel chain fired, nothing confirmed
// -- is the same red but faded, with a dashed ring (RoleSwatch), and a
// flagged transfer off the traced route is dashed and red-tinted: dashed
// versus solid carries "possible" versus "confirmed", never colour alone. An
// inferred deposit address is a faded green with a dashed ring. The reported
// address is bright neutral rather than coloured, and ordinary traced
// addresses are dim, so the eye lands on the answer instead of on decoration.
// tokens.test.js holds these to the styles.css tokens.
//
// Solid red outranks the rest. A published government designation is a fact
// from outside this tool, and it should not have to compete for attention
// with the tool's own inferences.
export const PALETTES = {
  light: {
    seed: '#0a0a0a', risk: '#bd2329', exchange: '#196e44', inferred: '#145a37', gambling: '#3d3d3d',
    service: '#b3b3b3', flagged: '#bd2329', node: '#8e8e8e',
    link: 'rgba(10,10,10,0.16)', linkPath: '#196e44', linkFlagged: 'rgba(189,35,41,0.5)', linkFaded: 'rgba(10,10,10,0.05)',
    text: '#0a0a0a', dim: '#3d3d3d', background: '#ffffff',
    haloExchange: 'rgba(25,110,68,0.16)', haloRisk: 'rgba(189,35,41,0.16)', haloGambling: 'rgba(10,10,10,0.1)',
    ring: 'rgba(255,255,255,0.8)', ringInk: 'rgba(10,10,10,0.6)', ringSelected: 'rgba(10,10,10,0.85)',
    labelBox: 'rgba(255,255,255,0.88)',
  },
  dark: {
    seed: '#ededed', risk: '#ff8a80', exchange: '#3dd68c', inferred: '#8eebc0', gambling: '#bdbdbd',
    service: '#4a4a4a', flagged: '#ff8a80', node: '#5e5e5e',
    link: 'rgba(237,237,237,0.13)', linkPath: '#3dd68c', linkFlagged: 'rgba(255,138,128,0.45)', linkFaded: 'rgba(237,237,237,0.05)',
    text: '#ededed', dim: '#bdbdbd', background: '#141414',
    haloExchange: 'rgba(61,214,140,0.18)', haloRisk: 'rgba(255,138,128,0.2)', haloGambling: 'rgba(189,189,189,0.16)',
    ring: 'rgba(20,20,20,0.9)', ringInk: 'rgba(237,237,237,0.6)', ringSelected: 'rgba(237,237,237,0.9)',
    labelBox: 'rgba(20,20,20,0.85)',
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
const ANSWER_ROLES = new Set(['seed', 'exchange', 'inferred', 'risk', 'gambling'])

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
// On a phone a finger, not a cursor, picks the bubble.
const COMPACT_HIT_PAD = 22
// Same reasoning for edges, kept smaller so a link never steals the pointer
// from a bubble sitting on top of it.
const LINK_HIT_PAD = 4

const PATTERN_NAME = { peel_chain: 'Peel chain', amount_split: 'Amount split' }
const RISK_NAME = { sanctioned: 'Sanctioned entity', seized: 'Seizure order', mixer: 'Mixer', frozen: 'Frozen by issuer', stolen: 'Stolen funds', reported: 'TronScan warning', gambling: 'Gambling platform', poisoning: 'Address poisoning', scam: 'Reported scam', laundering: 'Laundering' }
/** The tags a tooltip shows as possible flags: the patterns that fired, never
 * a confirmed category. Real traces carry the confirmed category in flags too
 * ('sanctioned', 'frozen', 'stolen'...); that is a fact, shown solid in the
 * Category row, and must not appear as a dashed "not confirmed" pill. */
export function possibleFlags(item) {
  return (item.flags ?? []).filter((f) => !(f in RISK_NAME) && f !== item.risk_category)
}

/** Roles whose colour means nothing: their text is painted in the dim ink,
 * which holds 4.5:1 on the label box and the tooltip in both themes. */
const QUIET_ROLES = new Set(['node', 'service'])
const inkOf = (role) => (QUIET_ROLES.has(role) ? COLORS.dim : COLORS[role])

const ROLE_NAME = {
  seed: 'Reported address',
  risk: 'Sanctioned / seized / mixer / frozen / stolen / scam / poisoning',
  gambling: 'Gambling platform wallet',
  exchange: 'Labelled exchange wallet',
  inferred: 'Probable deposit address (inferred)',
  service: 'Service contract or router, not expanded',
  flagged: 'Possible flag · pattern (not confirmed)',
  node: 'Traced address',
}

// The hop-by-hop reveal: the reported address first, then each hop
// HOP_MS after the one before, every bubble growing from nothing with the
// motion system's pop easing.
const HOP_MS = 600
const GROW_MS = 450
// After a hop-by-hop reveal the map is framed when the simulation settles;
// this frames it anyway if the simulation never reports that it has.
const SETTLE_FALLBACK_MS = 6000
const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

/** A CSS cubic-bezier(x1, y1, x2, y2) timing function, as t -> eased value. */
export function cubicBezier(x1, y1, x2, y2) {
  const cx = 3 * x1
  const bx = 3 * (x2 - x1) - cx
  const ax = 1 - cx - bx
  const cy = 3 * y1
  const by = 3 * (y2 - y1) - cy
  const ay = 1 - cy - by
  const x = (t) => ((ax * t + bx) * t + cx) * t
  const dx = (t) => (3 * ax * t + 2 * bx) * t + cx
  return (p) => {
    if (p <= 0) return 0
    if (p >= 1) return 1
    let t = p
    for (let i = 0; i < 8; i += 1) {
      const error = x(t) - p
      if (Math.abs(error) < 1e-5) break
      const slope = dx(t)
      if (Math.abs(slope) < 1e-6) break
      t = Math.min(1, Math.max(0, t - error / slope))
    }
    return ((ay * t + by) * t + cy) * t
  }
}
export const EASE_POP = cubicBezier(0.34, 1.56, 0.64, 1)

/** The reveal step an address appears at: the reported address first, then by hop. */
function levelOf(node) {
  if (node.is_seed) return 0
  return Number.isFinite(node.depth) ? Math.max(1, node.depth) : 1
}

/** Kept bright by "Show only flags": possible flags, confirmed risk, the
 * reported address. A gambling platform is an attribution, not a confirmed
 * risk, so it fades with the rest -- the same rule as the hop map's. */
export function keptByFlags(node) {
  return roleOf(node) === 'flagged' || isConfirmedRisk(node) || !!node.is_seed
}

function roleOf(node) {
  if (node.is_seed) return 'seed'
  // A gambling platform is an attribution, like an exchange -- not a risk-list
  // hit -- so it gets its own mark, a dashed halo, instead of sanctions red.
  if (node.risk_category === 'gambling') return 'gambling'
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
    .map(([k, v]) => `<div class="r"><span class="k">${esc(k)}</span><span class="v">${esc(plain(v))}</span></div>`)
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
  const patterns = possibleFlags(node)
  const flags = patterns.length
    ? `<div class="tags">${patterns
        .map((f) => `<span>${esc(PATTERN_NAME[f] ?? f)}</span>`)
        .join('')}</div>`
    : ''
  return `<div class="gt">
    <div class="gt-head" style="color:${inkOf(role)}">${esc(ROLE_NAME[role])}</div>
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
  const patterns = possibleFlags(link)
  const flags = patterns.length
    ? `<div class="tags">${patterns
        .map((f) => `<span>${esc(PATTERN_NAME[f] ?? f)}</span>`)
        .join('')}</div>`
    : ''
  return `<div class="gt">
    <div class="gt-head" style="color:${COLORS.text}">Transfer</div>
    <div class="gt-addr">${esc(short(idOf(link.source)))} → ${esc(short(idOf(link.target)))}</div>
    ${body}${flags}
  </div>`
}

export default function GraphView({
  data, tracePath, onSelect, selected, unit = '',
  // Fade everything but the possible flags, the confirmed risk and the seed.
  flagsOnly = false,
  // Phone layout: tap selects, no hover tooltips, finger-sized controls; the
  // page around the map shows the key and the jump list.
  compact = false,
  // False while the page hides the map: the canvas stops drawing and the
  // camera is not framed until it is shown again.
  active = true,
}) {
  const containerRef = useRef(null)
  const graphRef = useRef(null)
  // The mounted canvas, as state: ForceGraph2D only mounts once the container
  // has a size (and remounts on a theme flip), so anything configured on it
  // has to wait for this, not for the first render.
  const [fg, setFg] = useState(null)
  const attachGraph = useCallback((instance) => {
    graphRef.current = instance
    setFg(instance)
  }, [])
  const [size, setSize] = useState({ width: 0, height: 0 })
  const reducedMotion = useMedia(REDUCED_MOTION)
  // Pause motion: no particles on the route, no reveal. Starts pressed for
  // anyone whose system asks for reduced motion.
  const [paused, setPaused] = useState(reducedMotion)
  useEffect(() => { if (reducedMotion) setPaused(true) }, [reducedMotion])
  const instant = reducedMotion || paused
  const activeRef = useRef(active)
  activeRef.current = active
  const instantRef = useRef(instant)
  instantRef.current = instant
  const flagsRef = useRef(flagsOnly)
  flagsRef.current = flagsOnly
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
      // A page that hides the map collapses it to nothing; keep the last real
      // size so the canvas, and the layout it holds, stay mounted.
      setSize((last) => (width > 0 && height > 0) || last.width === 0 ? { width, height } : last)
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
  //
  // This waits for the mounted canvas (fg). It used to read graphRef in an
  // effect that ran before ForceGraph2D existed -- the canvas mounts only once
  // the container reports a width -- found nothing, and never ran again, so
  // the live map settled with the library's default forces.
  useEffect(() => {
    if (!fg || graphData.nodes.length === 0) return
    fg.d3Force('collide', forceCollide((node) => radiusOf(node) + 2.5).iterations(2))
    // Repulsion scales with bubble size so a big bubble clears room for itself
    // instead of swallowing its neighbours.
    fg.d3Force('charge')?.strength((node) => -18 - 3.2 * radiusOf(node))
    fg.d3Force('link')?.distance((link) => 24 + radiusOf(link.source) + radiusOf(link.target))
    fg.d3ReheatSimulation()
  }, [fg, graphData, radiusOf])

  // A hidden map draws nothing.
  useEffect(() => {
    if (!fg) return
    if (active) fg.resumeAnimation?.()
    else fg.pauseAnimation?.()
  }, [fg, active])

  // -- the hop-by-hop reveal ---------------------------------------------
  // The canvas is fed the graph a hop at a time: the reported address, then
  // each hop's addresses, born at their parent's position and released into
  // the simulation (a new graphData reheats it). Links follow once both ends
  // are on screen. Reduced motion, or Pause motion, shows everything at once.
  const levels = useMemo(
    () => [...new Set(graphData.nodes.map(levelOf))].sort((a, b) => a - b),
    [graphData],
  )
  const nodeById = useMemo(() => new Map(graphData.nodes.map((n) => [n.id, n])), [graphData])
  // Each address's parent: the neighbour nearer the seed that sent or took the
  // most value, preferring the hop just before it.
  const parents = useMemo(() => {
    const best = new Map()
    for (const link of graphData.links) {
      const s = nodeById.get(idOf(link.source))
      const t = nodeById.get(idOf(link.target))
      if (!s || !t) continue
      for (const [child, other] of [[s, t], [t, s]]) {
        const near = levelOf(other)
        const own = levelOf(child)
        if (near >= own) continue
        const score = (near === own - 1 ? 1e15 : 0) + (link.value_native || 0)
        if (!best.has(child.id) || score > best.get(child.id).score) best.set(child.id, { score, parent: other })
      }
    }
    return new Map([...best].map(([id, { parent }]) => [id, parent]))
  }, [graphData, nodeById])

  const [runId, setRunId] = useState(0)
  const revealKey = useMemo(() => ({ graphData, runId }), [graphData, runId])
  const [revealed, setRevealedState] = useState({ key: null, level: 0 })
  const revealedRef = useRef(revealed)
  const setRevealed = useCallback((next) => { revealedRef.current = next; setRevealedState(next) }, [])
  const shownLevel = instant ? Infinity
    : revealed.key === revealKey ? revealed.level
    : levels[0] ?? Infinity
  const revealDone = shownLevel === Infinity
  const revealKeyRef = useRef(revealKey)
  revealKeyRef.current = revealKey
  const revealDoneRef = useRef(revealDone)
  revealDoneRef.current = revealDone
  // The run whose hops were released into the simulation one by one. Its last
  // hop is born packed inside its parents, so it is framed once the layout has
  // settled (engine stop), never on a timer that would crop it.
  const animatedRef = useRef(null)

  const shownData = useMemo(() => {
    if (shownLevel === Infinity) return graphData
    const nodes = graphData.nodes.filter((n) => levelOf(n) <= shownLevel)
    const ids = new Set(nodes.map((n) => n.id))
    return { nodes, links: graphData.links.filter((l) => ids.has(idOf(l.source)) && ids.has(idOf(l.target))) }
  }, [graphData, shownLevel])

  /** Put a hop's addresses beside their parents, born now. */
  const spawnLevel = useCallback((level) => {
    const now = performance.now()
    const seed = graphData.nodes.find((n) => n.is_seed)
    const siblings = new Map()
    for (const node of graphData.nodes) {
      if (levelOf(node) !== level) continue
      node.__bornAt = now
      const parent = parents.get(node.id)
      if (!parent || !Number.isFinite(parent.x) || !Number.isFinite(parent.y)) continue
      const j = siblings.get(parent.id) ?? 0
      siblings.set(parent.id, j + 1)
      // Outward from the seed, fanned; around the seed itself, the golden angle.
      const out = seed && seed !== parent && Number.isFinite(seed.x)
        ? Math.atan2(parent.y - seed.y, parent.x - seed.x) : null
      const angle = out === null ? j * 2.399963 : out + (j % 2 ? 1 : -1) * Math.ceil(j / 2) * 0.35
      const reach = Math.max(3, radiusOf(parent) * 0.55)
      node.x = parent.x + Math.cos(angle) * reach
      node.y = parent.y + Math.sin(angle) * reach
      node.vx = Math.cos(angle) * 1.6
      node.vy = Math.sin(angle) * 1.6
    }
  }, [graphData, parents, radiusOf])

  useEffect(() => {
    if (graphData.nodes.length === 0) return undefined
    const current = revealedRef.current
    const mine = current.key === revealKey
    if (mine && current.level === Infinity) return undefined
    // Motion off, or the map hidden part-way: show the rest at once.
    if (instant || (!active && mine)) {
      setRevealed({ key: revealKey, level: Infinity })
      return undefined
    }
    // Not started, and hidden: wait until it is shown.
    if (!active) return undefined
    let from = mine ? Math.max(0, levels.indexOf(current.level)) : 0
    if (!mine) {
      // A fresh run (a new trace, or Replay): the first step grows in now.
      const now = performance.now()
      for (const node of graphData.nodes) node.__bornAt = levelOf(node) === levels[0] ? now : undefined
      from = 0
      if (levels.length > 1) setRevealed({ key: revealKey, level: levels[0] })
    }
    if (from >= levels.length - 1) {
      setRevealed({ key: revealKey, level: Infinity })
      return undefined
    }
    const timers = []
    for (let i = from + 1; i < levels.length; i += 1) {
      timers.push(setTimeout(() => {
        spawnLevel(levels[i])
        animatedRef.current = revealKey
        setRevealed({ key: revealKey, level: i === levels.length - 1 ? Infinity : levels[i] })
      }, HOP_MS * (i - from)))
    }
    return () => timers.forEach(clearTimeout)
  }, [revealKey, instant, active, graphData, levels, spawnLevel, setRevealed])

  // Replay gathers every address back to the middle before the canvas is
  // handed the first step again, so the simulation never holds a node
  // without a position.
  const replay = useCallback(() => {
    if (instantRef.current) return
    graphData.nodes.forEach((node, i) => {
      node.x = i ? Math.cos(i * 2.399963) * 4 : 0
      node.y = i ? Math.sin(i * 2.399963) * 4 : 0
      node.vx = 0
      node.vy = 0
      node.fx = undefined
      node.fy = undefined
      node.pinned = false
      node.__bornAt = undefined
    })
    setPinTick((t) => t + 1)
    graphRef.current?.centerAt?.(0, 0, 400)
    setRunId((r) => r + 1)
  }, [graphData])

  // Every link of the traced route on screen: only then does money move on it.
  const routeShown = useMemo(() => {
    if (pathEdges.size === 0) return false
    const on = new Set(shownData.links.map((l) => `${idOf(l.source)}>${idOf(l.target)}`))
    return [...pathEdges].every((key) => on.has(key))
  }, [pathEdges, shownData])

  // -- Show only flags -----------------------------------------------------
  const kept = useMemo(() => new Set(graphData.nodes.filter(keptByFlags).map((n) => n.id)), [graphData])
  const keptRef = useRef(kept)
  keptRef.current = kept
  const flagCounts = useMemo(() => ({
    possible: graphData.nodes.filter((n) => roleOf(n) === 'flagged').length,
    confirmed: graphData.nodes.filter(isConfirmedRisk).length,
  }), [graphData])
  const offFlags = (id) => flagsRef.current && !keptRef.current.has(id)
  const linkOffFlags = (link) => offFlags(idOf(link.source)) || offFlags(idOf(link.target))

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
    // A hidden map is framed when it is shown, not while it has no size.
    if (!fg || !activeRef.current) return false
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

  // Framed once the reveal has finished; a map hidden until then is framed
  // when it is first shown.
  useEffect(() => {
    if (graphData.nodes.length > 0 && revealDone) needsFit.current = true
  }, [graphData, runId, revealDone])

  useEffect(() => {
    if (graphData.nodes.length === 0 || !revealDone || !active) return undefined
    // After a hop-by-hop reveal, engine stop frames it; this is only the
    // fallback for a simulation that never reports one.
    const delays = animatedRef.current === revealKey ? [SETTLE_FALLBACK_MS] : [300, 700, 1200, 2000, 3000]
    const timers = delays.map((delay) =>
      setTimeout(() => {
        if (needsFit.current && fitToView()) needsFit.current = false
      }, delay),
    )
    return () => timers.forEach(clearTimeout)
  }, [graphData, runId, revealKey, revealDone, active, fitToView])

  // While a trace is revealed hop by hop the canvas is handed a new graph at
  // every step, and force-graph re-zooms to its node count after each one as
  // long as the camera sits where it last put it -- a jump per hop. On the
  // first tick of a run (after the canvas has applied the reported address
  // alone) the camera is set once to the framing of the whole trace, which
  // takes it off that automatic zoom; the final fit then glides from there.
  const heldCamera = useRef({ key: null, fg: null })
  const handleEngineTick = useCallback(() => {
    const canvas = graphRef.current
    if (!canvas || revealDoneRef.current || instantRef.current) return
    const key = revealKeyRef.current
    const held = heldCamera.current
    if (held.key === key && held.fg === canvas) return
    // A replay eases there from wherever the officer left the camera.
    const replaying = held.key !== null && held.key.graphData === key.graphData
    heldCamera.current = { key, fg: canvas }
    canvas.zoom?.(4 / Math.cbrt(Math.max(1, graphData.nodes.length)), replaying ? 400 : 0)
  }, [graphData])

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
      // A phone has no hover: a tap selects instead.
      if (compact) return
      hoverRef.current = node?.id ?? null
      // Cursor feedback is mutated directly rather than held in state: this
      // fires on every pointer move across the canvas, and a re-render per
      // move would cost far more than it is worth.
      if (containerRef.current) {
        containerRef.current.style.cursor = node ? 'pointer' : 'default'
      }
      resolveFocus()
    },
    [compact, resolveFocus],
  )

  const handleLinkHover = useCallback(
    (link) => {
      if (compact) return
      hoverLinkRef.current = link ?? null
      resolveFocus()
    },
    [compact, resolveFocus],
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
        onSelect?.(node)
        return
      }
      // A parent that owns the selection is told to let go, the same as the
      // hop map does, so a second click clears the selection on both maps.
      onSelect?.(node && selected === node.id ? null : node)
    },
    [controlled, onSelect, selected],
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
    const rank = { risk: 0, gambling: 1, exchange: 2, inferred: 3 }
    return graphData.nodes
      .filter((n) => rank[roleOf(n)] !== undefined)
      .sort((a, b) =>
        rank[roleOf(a)] - rank[roleOf(b)] ||
        (a.depth ?? 0) - (b.depth ?? 0) ||
        flowOf(b) - flowOf(a))
  }, [graphData])

  const [jumpOpen, setJumpOpen] = useState(false)
  const jumpId = useId()

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
      // A hidden map leaves the keys to the one on screen.
      if (!activeRef.current) return
      const tag = event.target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || event.target?.isContentEditable) return
      if (event.key === 'Escape') handleSelect(null)
      // A bare letter is a shortcut only while focus is inside the map, so it
      // never fires from elsewhere on the page (WCAG 2.1.4).
      else if ((event.key === 'f' || event.key === 'F') && containerRef.current?.contains(document.activeElement)) fitToView()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [handleSelect, fitToView])

  function drawNode(node, ctx, globalScale) {
    const role = roleOf(node)
    const radius = radiusOf(node)
    const isActive = focusRef.current.id === node.id
    const isSelected = selectedRef.current === node.id
    const faded = isFaded(node.id) || offFlags(node.id)
    // Show only flags names every flag and risk hit it keeps bright.
    const keptLabel = flagsRef.current && keptRef.current.has(node.id)

    // A bubble just revealed grows from nothing, overshooting a little.
    let grow = 1
    if (node.__bornAt !== undefined && !instantRef.current) {
      const t = (performance.now() - node.__bornAt) / GROW_MS
      if (t < 1) grow = Math.max(EASE_POP(Math.max(0, t)), 0.001)
    }

    ctx.save()
    if (grow !== 1) {
      ctx.translate(node.x, node.y)
      ctx.scale(grow, grow)
      ctx.translate(-node.x, -node.y)
    }
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
    if (role === 'gambling') {
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius + 4.5, 0, 2 * Math.PI)
      ctx.fillStyle = COLORS.haloGambling
      ctx.fill()
    }

    ctx.beginPath()
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI)
    ctx.fillStyle = COLORS[role]
    const alpha = ctx.globalAlpha
    if (FADED_ROLES.has(role)) ctx.globalAlpha = alpha * FADED
    ctx.fill()
    ctx.globalAlpha = alpha

    if (isActive) {
      ctx.strokeStyle = COLORS.text
      ctx.lineWidth = 1.6 / globalScale
      ctx.stroke()
    } else if (role === 'inferred' || role === 'flagged') {
      // An inference or a possible flag: a dashed ring, so it never reads as
      // the confirmed exchange or the confirmed risk hit beside it.
      ctx.strokeStyle = COLORS[role]
      ctx.lineWidth = 1.2 / globalScale
      ctx.setLineDash(DASH.map((d) => d / globalScale))
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius + 1.8, 0, 2 * Math.PI)
      ctx.stroke()
      ctx.setLineDash([])
    } else if (role === 'exchange' || role === 'seed') {
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
      const gambling = node.risk_category === 'gambling'
      ctx.strokeStyle = gambling ? COLORS.gambling : COLORS.risk
      ctx.lineWidth = 1.6 / globalScale
      if (gambling) ctx.setLineDash(DASH.map((d) => d / globalScale))
      ctx.stroke()
      ctx.setLineDash([])
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
    const important = ANSWER_ROLES.has(role) || isActive || inFocus || keptLabel
    if ((!important && globalScale < 1.6) || (faded && !keptLabel) || grow !== 1) {
      ctx.restore()
      return
    }

    const text = (role === 'risk' || role === 'gambling') && node.risk_entity ? plain(node.risk_entity)
      : role === 'exchange' && node.label ? plain(node.label)
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
    ctx.fillStyle = important ? inkOf(role) : COLORS.dim
    ctx.fillText(text, x, y)
    ctx.restore()
  }

  const hasData = graphData.nodes.length > 0
  const hitPad = compact ? COMPACT_HIT_PAD : HIT_PAD
  const particlesOn = !paused && routeShown && !flagsOnly
  const particles = useCallback((link) => {
    const key = `${idOf(link.source)}>${idOf(link.target)}`
    return pathEdges.has(key) ? 3 : 0
  }, [pathEdges])
  const jumpButtons = () => landmarks.map((node) => {
    const role = roleOf(node)
    return (
      <button
        key={node.id}
        type="button"
        className={activeSelected === node.id ? 'active' : ''}
        aria-current={activeSelected === node.id ? 'true' : undefined}
        onClick={() => { flyTo(node); setJumpOpen(false) }}
        title={node.address}
      >
        <RoleSwatch role={role} color={COLORS[role]} />
        <span className="name">
          {role === 'risk' || role === 'gambling'
            ? plain(node.risk_entity) ?? RISK_NAME[node.risk_category] ?? 'Listed'
            : role === 'inferred' ? `${node.inferred_exchange} deposit (inferred)`
            : plain(node.label ?? node.exchange)}
        </span>
        <span className="addr">{short(node.address)}</span>
      </button>
    )
  })
  const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`

  return (
    <div ref={containerRef} className={`graph-view${compact ? ' compact' : ''}`} style={{ width: '100%', height: '100%' }}>
      {hasData && size.width > 0 && (
        <ForceGraph2D
          key={theme}
          ref={attachGraph}
          width={size.width}
          height={size.height}
          graphData={shownData}
          backgroundColor={COLORS.background}
          nodeRelSize={4}
          nodeCanvasObject={drawNode}
          nodeLabel={compact ? null : (node) => nodeTooltip(node, unit)}
          nodePointerAreaPaint={(node, color, ctx) => {
            ctx.fillStyle = color
            ctx.beginPath()
            ctx.arc(node.x, node.y, radiusOf(node) + hitPad / zoomRef.current, 0, 2 * Math.PI)
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
          linkLabel={compact ? null : (link) => linkTooltip(link, unit)}
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
            if (isFaded(idOf(link.source)) || isFaded(idOf(link.target)) || linkOffFlags(link)) {
              return COLORS.linkFaded
            }
            if (pathEdges.has(key)) return COLORS.linkPath
            if (link.flags?.length) return COLORS.linkFlagged
            return COLORS.link
          }}
          linkLineDash={(link) => {
            // Dashed means a pattern fired, never on the traced route itself.
            const key = `${idOf(link.source)}>${idOf(link.target)}`
            return link.flags?.length && !pathEdges.has(key) ? [2, 2] : null
          }}
          linkWidth={(link) => {
            const key = `${idOf(link.source)}>${idOf(link.target)}`
            const base = 0.6 + 2.2 * Math.sqrt((link.value_native || 0) / maxValue)
            if (hoverLinkRef.current === link) return base + 1.6
            return pathEdges.has(key) ? base + 1 : base
          }}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          linkDirectionalArrowColor={(link) => (linkOffFlags(link) ? COLORS.linkFaded : COLORS.dim)}
          // Animated particles only along the attributed path: a direct visual
          // answer to "where did the money go". They start once the whole
          // route is on screen, and Pause motion stops them.
          linkDirectionalParticles={particlesOn ? particles : 0}
          linkDirectionalParticleWidth={2.4}
          linkDirectionalParticleColor={() => COLORS.exchange}
          onEngineTick={handleEngineTick}
          onEngineStop={handleEngineStop}
          cooldownTicks={200}
          d3VelocityDecay={0.28}
        />
      )}

      {hasData && (
        <>
          {/* Along the top: the hint on the left, and the counts over the zoom
              buttons on the right, in one row: on a narrow stage the hint
              narrows instead of covering the counts. */}
          <div className="graph-top">
            <div className="graph-lead">
              {!compact && (
                <div className="graph-hint">
                  Hover any bubble for detail · click to keep it highlighted · drag to
                  pin · right-click to release · scroll to zoom · bubble size = value
                  moved
                </div>
              )}
              {flagsOnly && (
                <div className="graph-flags-chip" role="status">
                  <RoleSwatch role="flagged" color={COLORS.flagged} />
                  <RoleSwatch role="risk" color={COLORS.risk} />
                  <span>
                    Showing {plural(flagCounts.possible, 'possible flag')} · {flagCounts.confirmed}&nbsp;confirmed
                  </span>
                </div>
              )}
            </div>

            <div className="graph-side">
              <div className="graph-stats">
                {/* On a phone the counts break at the dot, never inside one. */}
                {graphData.nodes.length}&nbsp;addresses · {graphData.links.length}&nbsp;transfers
              </div>

              <div className="graph-controls">
                <button onClick={() => zoomBy(1.4)} title="Zoom in"><span aria-hidden="true">+</span><span className="visually-hidden">Zoom in</span></button>
                <button onClick={() => zoomBy(1 / 1.4)} title="Zoom out"><span aria-hidden="true">&minus;</span><span className="visually-hidden">Zoom out</span></button>
                <button
                  onClick={fitToView}
                  title="Fit the whole graph in view (f)"
                >
                  Fit
                </button>
                <button
                  className="wide"
                  onClick={releaseAll}
                  disabled={pinnedCount === 0}
                  title="Release every pinned bubble and let the layout settle again"
                >
                  Release {pinnedCount > 0 ? `(${pinnedCount})` : ''}
                </button>
                <button
                  type="button"
                  className="wide"
                  aria-pressed={paused}
                  onClick={() => setPaused((p) => !p)}
                  title="Stop the moving money on the traced route and the hop-by-hop reveal"
                >
                  Pause motion
                </button>
                <button
                  type="button"
                  className="wide"
                  onClick={replay}
                  disabled={instant}
                  title={reducedMotion ? 'Motion is off (reduced motion setting)'
                    : paused ? 'Motion is paused' : 'Replay the trace hop by hop'}
                >
                  Replay
                </button>
              </div>
            </div>
          </div>

          {/* The landmarks are the keyboard's way to every answer on the map
              (bubbles on a canvas cannot take focus), so a phone keeps them
              too: behind a finger-sized "Jump to" button. */}
          {landmarks.length > 0 && !compact && (
            <div className="jump-panel">
              <span className="micro">Jump to</span>
              {jumpButtons()}
            </div>
          )}
          {landmarks.length > 0 && compact && (
            <div className="graph-jump-compact">
              {jumpOpen && (
                <div className="jump-panel compact" id={jumpId} role="group" aria-label="Jump to a wallet">
                  {jumpButtons()}
                </div>
              )}
              <button
                type="button"
                className="graph-jump-toggle"
                aria-expanded={jumpOpen}
                aria-controls={jumpId}
                onClick={() => setJumpOpen((open) => !open)}
              >
                Jump to · {landmarks.length}
              </button>
            </div>
          )}

          {!compact && <div className="legend">
            <div className="item">
              <RoleSwatch role="seed" color={COLORS.seed} />
              Reported address
            </div>
            <div className="item">
              <RoleSwatch role="risk" color={COLORS.risk} />
              Sanctioned / mixer / frozen (confirmed)
            </div>
            <div className="item">
              <RoleSwatch role="flagged" color={COLORS.flagged} />
              Possible flag · pattern (not confirmed)
            </div>
            <div className="item">
              <RoleSwatch role="gambling" color={COLORS.gambling} />
              Gambling platform wallet
            </div>
            <div className="item">
              <RoleSwatch role="exchange" color={COLORS.exchange} />
              Labelled exchange wallet
            </div>
            <div className="item">
              <RoleSwatch role="inferred" color={COLORS.inferred} />
              Probable deposit address (inferred)
            </div>
            <div className="item">
              <RoleSwatch role="service" color={COLORS.service} />
              Service contract / router, not expanded
            </div>
            <div className="item">
              <RoleSwatch role="node" color={COLORS.node} />
              Traced address
            </div>
          </div>}
        </>
      )}
    </div>
  )
}
