// The Flow tab's Sankey (VictimFlow.jsx), laid out without drawing it, from
// the case's victim_flow (backend/app/victim_flow.py). Three columns: the
// reported wallet, the wallets it paid (hop 1), and on the right edge the
// buckets where the victim's share ended. Money that went further than hop 1
// is carried to its bucket through the hop-1 wallet it left by: pro-rata is
// linear, so each unit a wallet received ends where the flow sends its
// money. Every width is the victim's share (links[].victim), never the gross
// that passed through. Rows follow FlowView's barycentre rule: the first hop
// is ordered (the route to the exchange, then flagged wallets, then by
// amount) and each bucket sits at the weighted average row of its sources.

export const KIND_ORDER = ['exchange', 'instant_exchanger', 'held', 'risk', 'not_followed', 'other', 'beyond_limit', 'left']
const COLOUR = { exchange: 'go', instant_exchanger: 'go', held: 'risk', risk: 'risk' }
const RANK = { solid: 0, faded: 1, dashed: 2 }
const worse = (a, b) => (RANK[a] >= RANK[b] ? a : b)
const EPS = 1e-6
const FOLD = 0.1 // a first-hop wallet below this part of the start folds into "N more wallets"
export const BAR = 12
const PAD = 10
const GAP = 16

export const colourOf = (kind) => COLOUR[kind] ?? 'grey'

/** A share as a percentage with one decimal, cut, never rounded up. */
export function shareText(share) {
  if (!(share > 0)) return '0%'
  const tenths = Math.floor(share * 1000 + 1e-9) / 10
  return tenths >= 0.1 ? `${tenths}%` : 'under 0.1%'
}

/** Where each unit reaching a wallet ends, {"kind style": part}, worked from
 * the far end back (nodes come in topological order); each wallet's own
 * remainder (left, held or not followed) as amounts; and the part of each
 * unit that goes on through a flagged wallet (passed_through), {address:
 * part}. A link back up the walk, or a swap, ends in "other", as the backend
 * counts it. */
function ends(flow, graph) {
  const at = new Map(flow.nodes.map((n, i) => [n.address, i]))
  const swaps = new Set((graph?.edges ?? []).filter((e) => e.swap).map((e) => `${e.source}>${e.target}`))
  const held = new Set(flow.buckets.find((b) => b.kind === 'held')?.addresses ?? [])
  const flagged = new Set((flow.passed_through ?? []).map((p) => p.address))
  const parts = new Map()
  const rests = new Map()
  const vias = new Map()
  // `own` false: where the money ends past the link, without the link's own style.
  const onward = (l, i, own = true) => {
    if (!((at.get(l.target) ?? -1) > i) || swaps.has(`${l.source}>${l.target}`)) return { [`other ${l.style}`]: 1 }
    if (!own) return parts.get(l.target) ?? {}
    const out = {}
    for (const [key, f] of Object.entries(parts.get(l.target) ?? {})) {
      const [kind, style] = key.split(' ')
      const k = `${kind} ${worse(l.style, style)}`
      out[k] = (out[k] ?? 0) + f
    }
    return out
  }
  // Past link l: the part of each unit that goes on through a flagged wallet, its target among them.
  const through = (l, i) => {
    if (!((at.get(l.target) ?? -1) > i) || swaps.has(`${l.source}>${l.target}`)) return {}
    const out = { ...vias.get(l.target) }
    if (flagged.has(l.target)) out[l.target] = (out[l.target] ?? 0) + 1
    return out
  }
  for (let i = flow.nodes.length - 1; i >= 0; i -= 1) {
    const n = flow.nodes[i]
    const part = {}
    const rest = {}
    const via = {}
    const add = (into, key, amount) => { if (amount > EPS) into[key] = (into[key] ?? 0) + amount }
    parts.set(n.address, part)
    rests.set(n.address, rest)
    vias.set(n.address, via)
    if (n.role !== 'seed' && n.role !== 'wallet') { part[`${n.role} solid`] = 1; continue }
    if (!(n.victim_in > 0)) continue
    let sent = 0
    for (const l of flow.links.filter((x) => x.source === n.address)) {
      sent += l.victim
      for (const [key, f] of Object.entries(onward(l, i))) add(part, key, l.victim * f)
      for (const [a, f] of Object.entries(through(l, i))) add(via, a, (l.victim * f) / n.victim_in)
    }
    const style = n.basis === 'traced_only' || n.basis === 'edge_bounds' ? 'dashed' : 'solid'
    add(rest, `${held.has(n.address) ? 'held' : 'left'} ${style}`, n.left)
    add(rest, `not_followed ${style}`, n.victim_in - sent - n.left)
    for (const [key, v] of Object.entries(rest)) add(part, key, v)
    for (const key of Object.keys(part)) part[key] /= n.victim_in
  }
  return { parts, rests, onward, through, at }
}

const scaled = (part, amount) => Object.fromEntries(Object.entries(part).map(([k, f]) => [k, f * amount]))
function merge(into, more) {
  for (const [k, v] of Object.entries(more)) into[k] = (into[k] ?? 0) + v
  return into
}

/** Labels of several columns that share one lane (the hop chips run into
 * the bucket chips' space), spaced as one column: each column's order kept,
 * no two labels nearer than `gap`. */
export function spreadColumns(columns, gap, max) {
  const all = columns.flatMap((ys, c) => ys.map((y, i) => ({ y, c, i }))).sort((a, b) => a.y - b.y || a.c - b.c)
  const ys = spread(all.map((l) => l.y), gap, max)
  const out = columns.map((ys2) => new Array(ys2.length))
  all.forEach((l, j) => { out[l.c][l.i] = ys[j] })
  return out
}

/** Space labels at least `gap` apart, in order, inside [0, max]. */
export function spread(ys, gap, max) {
  const out = []
  for (const y of ys) out.push(Math.max(y, out.length ? out.at(-1) + gap : gap / 2))
  const over = (out.at(-1) ?? 0) - (max - gap / 2)
  return over > 0 ? out.map((y) => Math.max(gap / 2, y - over)) : out
}

/** The Sankey's geometry in a width × height box (SVG units), or null when
 * the flow starts from nothing. */
export function victimFlowLayout(flow, { graph, width = 1000, height = 420 } = {}) {
  const total = flow?.totals?.denominator
  const seedNode = flow?.nodes?.find((n) => n.role === 'seed')
  if (!(total > 0) || !seedNode) return null
  const { rests, onward, through, at } = ends(flow, graph)
  const lead = new Set(flow.lead?.path ?? [])
  const flagged = new Map((flow.passed_through ?? []).map((p) => [p.address, p.category]))
  const known = new Map((graph?.nodes ?? []).map((n) => [n.address, n]))
  const riskOf = (a) => flagged.get(a) ?? known.get(a)?.risk_category ?? null

  // The first hop: one row per wallet the reported wallet paid.
  let hop1 = flow.links.filter((l) => l.source === seedNode.address && l.victim > EPS).map((l) => ({
    id: l.target, address: l.target, amount: l.victim, style: l.style, lead: lead.has(l.target), risk: riskOf(l.target),
    dest: scaled(onward(l, at.get(seedNode.address), false), l.victim),
    through: scaled(Object.fromEntries(Object.entries(through(l, at.get(seedNode.address))).filter(([a]) => a !== l.target)), l.victim),
  }))
  hop1.sort((a, b) => Number(b.lead) - Number(a.lead) || Number(Boolean(b.risk)) - Number(Boolean(a.risk)) || b.amount - a.amount || a.id.localeCompare(b.id))
  const small = hop1.filter((h) => !h.lead && !h.risk && h.amount < FOLD * total)
  if (small.length >= 2) {
    hop1 = hop1.filter((h) => !small.includes(h))
    hop1.push({
      id: 'more', address: null, count: small.length, amount: small.reduce((s, h) => s + h.amount, 0),
      style: small.map((h) => h.style).reduce(worse), dest: small.reduce((d, h) => merge(d, h.dest), {}),
      through: small.reduce((d, h) => merge(d, h.through), {}),
    })
  }
  // A row's money that went on through a flagged wallet: the chart marks it there.
  for (const h of hop1) {
    h.via = Object.entries(h.through).filter(([, v]) => v > EPS).sort((a, b) => b[1] - a[1])
      .map(([address, amount]) => ({ address, category: flagged.get(address), amount }))
    delete h.through
  }
  const own = rests.get(seedNode.address)
  const ownTotal = Object.values(own).reduce((s, v) => s + v, 0)
  if (ownTotal > EPS) hop1.push({ id: 'gap', gap: true, address: null, amount: ownTotal, style: 'solid', dest: { ...own } })

  // The buckets, ordered by the weighted row of the money that reaches them.
  const kinds = flow.buckets.filter((b) => b.amount > EPS).map((b) => b.kind)
  const weight = Object.fromEntries(kinds.map((k) => [k, [0, 0]]))
  hop1.forEach((h, row) => {
    for (const [key, v] of Object.entries(h.dest)) {
      const w = weight[key.split(' ')[0]]
      if (w) { w[0] += row * v; w[1] += v }
    }
  })
  const bary = (k) => (weight[k][1] > 0 ? weight[k][0] / weight[k][1] : Infinity)
  kinds.sort((a, b) => bary(a) - bary(b) || KIND_ORDER.indexOf(a) - KIND_ORDER.indexOf(b))
  const order = (key) => {
    const [kind, style] = key.split(' ')
    return kinds.indexOf(kind) * 3 + RANK[style]
  }

  // Geometry: one scale for every column, each column's stack centred.
  const inner = height - 2 * PAD
  const k = (inner - (Math.max(hop1.length, kinds.length) - 1) * GAP) / total
  const stack = (amounts, x) => {
    let y = PAD + (inner - amounts.reduce((s, a) => s + a * k, 0) - (amounts.length - 1) * GAP) / 2
    return amounts.map((a) => { const y0 = y; y += a * k + GAP; return { x, y0, y1: y0 + a * k } })
  }
  const mid = (width - BAR) / 2
  const seed = { address: seedNode.address, amount: total, risk: riskOf(seedNode.address), ...stack([total], 0)[0] }
  stack(hop1.map((h) => h.amount), mid).forEach((g, i) => Object.assign(hop1[i], g))
  const byKind = Object.fromEntries(kinds.map((kind) => [kind, { kind, amount: flow.buckets.find((b) => b.kind === kind).amount, colour: colourOf(kind) }]))
  const inflow = kinds.map((kind) => hop1.reduce((s, h) => s + Object.entries(h.dest).filter(([key]) => key.startsWith(`${kind} `)).reduce((t, [, v]) => t + v, 0), 0))
  stack(inflow, width - BAR).forEach((g, i) => Object.assign(byKind[kinds[i]], g))
  const buckets = kinds.map((kind) => byKind[kind])

  // Ribbons: the reported wallet to each first-hop row, split by where the
  // money ended, then each row to its buckets, stacked in row order.
  const ribbons = []
  const cursor = { seed: seed.y0, ...Object.fromEntries(kinds.map((kind) => [kind, byKind[kind].y0])) }
  const ribbon = (from, to, kind, style, amount, x0, sy0, x1, ty0) => {
    const [sy1, ty1, xm] = [sy0 + amount * k, ty0 + amount * k, (x0 + x1) / 2]
    ribbons.push({ from, to, kind, colour: colourOf(kind), style, amount, x0, x1, sy0, sy1, ty0, ty1,
      path: `M${x0} ${sy0}C${xm} ${sy0} ${xm} ${ty0} ${x1} ${ty0}L${x1} ${ty1}C${xm} ${ty1} ${xm} ${sy1} ${x0} ${sy1}Z` })
  }
  for (const h of hop1) {
    let y = h.y0
    const keys = Object.keys(h.dest).filter((key) => byKind[key.split(' ')[0]]).sort((a, b) => order(a) - order(b))
    for (const key of keys) {
      const [kind, style] = key.split(' ')
      const v = h.dest[key]
      ribbon(seed.address, h.id, kind, h.gap ? style : h.style, v, BAR, cursor.seed, h.gap ? mid + BAR : mid, y)
      ribbon(h.id, kind, kind, style, v, mid + BAR, y, width - BAR, cursor[kind])
      cursor.seed += v * k
      cursor[kind] += v * k
      y += v * k
    }
  }
  return { width, height, bar: BAR, seed, hop1, buckets, ribbons }
}
