import { plain } from '../../text'

// The wallets of a case, grouped by the role each plays in it: who was
// reported, where money reached an exchange, what an issuer froze, the route
// between them, a split and where it went, and the unlabelled rest. Roles,
// not owners: nothing here says two wallets belong to one person
// (backend/app/exchange_matcher.py keeps that line on purpose).
//
// Each wallet goes to the first group it fits, in ORDER. "other" holds any
// wallet another list names (a mixer, a router) that fits none of the rest.
export const ORDER = ['reported', 'exchange', 'deposit', 'frozen', 'route', 'split', 'recipients', 'passed', 'end', 'other']
// Top to bottom within a column: the way to the exchange first.
const ROWS = ['route', 'exchange', 'deposit', 'frozen', 'reported', 'split', 'recipients', 'passed', 'end', 'other']

const unique = (values) => [...new Set(values.filter(Boolean))]
const and = (names) => names.join(' and ')

/** {groups, links} for a case. A group is {key, name, kind (go, risk or
 * plain), inferred, depth (its nearest hop), addresses}; a link is the gross
 * amount sent from one group to another, {from, to, gross, style}. */
export function entityGroups(result) {
  const nodes = result?.graph?.nodes ?? []
  const edges = result?.graph?.edges ?? []
  const reverse = result?.direction === 'incoming'
  const path = (result?.trace_path ?? []).map((s) => s.address)
  const route = new Set(path.slice(1, -1))
  const splits = (result?.findings ?? []).filter((f) => f.pattern === 'amount_split')
  const splitters = new Set(splits.map((f) => f.evidence?.address))
  const recipients = new Set(splits.flatMap((f) => f.evidence?.recipients ?? []))
  // A wallet the trace went on from: it sent on, or on a reverse trace, was paid by another.
  const onward = new Set(edges.map((e) => (reverse ? e.target : e.source)))
  const named = (n) => n.label || n.exchange || n.risk_category || n.inferred_exchange

  const test = {
    reported: (n) => n.is_seed || n.address === result.address,
    exchange: (n) => n.exchange,
    deposit: (n) => n.inferred_exchange,
    frozen: (n) => n.risk_category === 'frozen',
    route: (n) => route.has(n.address),
    split: (n) => splitters.has(n.address),
    recipients: (n) => recipients.has(n.address),
    passed: (n) => !named(n) && onward.has(n.address),
    end: (n) => !named(n),
    other: () => true,
  }
  const members = Object.fromEntries(ORDER.map((k) => [k, []]))
  const groupOf = new Map()
  for (const n of nodes) {
    const key = ORDER.find((k) => test[k](n))
    members[key].push(n)
    groupOf.set(n.address, key)
  }

  const issuers = unique((result?.risk_matches ?? []).filter((m) => m.category === 'frozen').map((m) => plain(m.issuer)))
  const name = {
    reported: () => 'Reported wallet',
    exchange: (ns) => (ns.length === 1 && ns[0].label ? plain(ns[0].label) : and(unique(ns.map((n) => plain(n.exchange))))),
    deposit: (ns) => `Probable ${and(unique(ns.map((n) => plain(n.inferred_exchange))))} deposit`,
    frozen: () => `Frozen by ${issuers.length ? and(issuers) : 'the issuer'}`,
    route: () => (result.exchange ? `Route to ${plain(result.exchange)}` : 'Route to the exchange'),
    split: () => 'Split wallet',
    recipients: () => 'Split recipients',
    passed: () => 'Passed on, no label',
    end: () => 'End of trace, no label',
    other: () => 'Named on other lists',
  }
  const KIND = { exchange: 'go', deposit: 'go', frozen: 'risk' }
  const groups = ORDER.filter((k) => members[k].length).map((key) => ({
    key,
    name: name[key](members[key]),
    kind: KIND[key] ?? 'plain',
    inferred: key === 'deposit' || (key === 'route' && Boolean(result.attribution_inferred)),
    depth: Math.min(...members[key].map((n) => n.depth ?? 0)),
    addresses: members[key].map((n) => n.address),
  }))

  const inferred = new Set(groups.filter((g) => g.inferred).map((g) => g.key))
  const byPair = new Map()
  for (const e of edges) {
    const from = groupOf.get(e.source)
    const to = groupOf.get(e.target)
    if (!from || !to || from === to) continue
    const link = byPair.get(`${from}>${to}`) ?? { from, to, gross: 0, style: inferred.has(from) || inferred.has(to) ? 'dashed' : 'solid' }
    link.gross += e.value_native || 0
    byPair.set(`${from}>${to}`, link)
  }
  return { groups, links: [...byPair.values()] }
}

/** Where each group sits on the map, as fractions of its width and height:
 * one column per hop, the reported wallet first (last on a reverse trace, so
 * money still reads left to right), the way to the exchange on top. */
export function groupLayout(groups, { reverse = false } = {}) {
  const depths = [...new Set(groups.map((g) => g.depth))].sort((a, b) => a - b)
  const at = {}
  for (const [col, depth] of depths.entries()) {
    const column = groups.filter((g) => g.depth === depth).sort((a, b) => ROWS.indexOf(a.key) - ROWS.indexOf(b.key))
    const share = depths.length === 1 ? 0.5 : col / (depths.length - 1)
    const x = 0.14 + 0.72 * (reverse ? 1 - share : share)
    column.forEach((g, i) => { at[g.key] = { x, y: (i + 1) / (column.length + 1) } })
  }
  return at
}
