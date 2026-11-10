import { useId, useMemo, useState } from 'react'
import { plain } from '../../text'
import { clock } from './timelineStats'
import { middle, num, txUrl } from './format'

// Every transfer at its IST time, one lane per wallet that matters (pack
// 2-glass-05): the reported wallet, the route, the exchange, frozen and split
// wallets, then the rest in one lane. A ring is money in, a filled dot money
// out; green is the path to the exchange, red a frozen wallet; the area of a
// dot follows the amount. The chart is one listbox: the arrow keys walk a
// lane, up and down change lane, and the strip below reads the chosen one.
// Each dot is a hit area of 24 px or more, and a tap picks the dot whose
// centre is nearest. Dots on one day can still sit on top of each other, so
// Earlier and Later in the strip walk the lane for a pointer too.

const DAY = 86400
const IST = 19800 // India keeps +5:30 all year
const istMidnight = (t) => Math.floor((t + IST) / DAY) * DAY - IST
const WINDOW = 14 // days shown first, when the case runs longer than LONG
const LONG = 21
const STEPS = [1, 2, 7, 14, 28, 56, 91, 182, 364]

/** Lanes and dots for a case, or null when it lists no transfers. */
export function buildLanes(result) {
  const transfers = (result.transfers ?? []).filter((t) => t.timestamp)
  if (!transfers.length) return null
  const seed = result.address
  const nodes = new Map((result.graph?.nodes ?? []).map((n) => [n.id, n]))
  const steps = result.trace_path ?? []
  const exchange = steps.find((s) => s.exchange && s.address !== seed)?.address
  const exName = plain(result.exchange) || 'the exchange'
  const lanes = []
  const laneOf = new Map()
  const add = (address, name, tone = '') => {
    if (!address || laneOf.has(address)) return
    laneOf.set(address, address)
    lanes.push({ key: address, name, sub: middle(address, 4, 4), label: `${name}, ${address}`, tone })
  }
  add(seed, 'Reported wallet')
  steps.forEach((s, i) => {
    if (s.address !== seed && s.address !== exchange) add(s.address, `Hop ${s.depth ?? i} · ${result.direction === 'incoming' ? 'from' : 'to'} ${exName}`, 'go')
  })
  add(exchange, plain(nodes.get(exchange)?.label) || plain(result.exchange_label) || exName, 'go')
  const frozen = (result.risk_matches ?? []).filter((m) => m.category === 'frozen').map((m) => m.address)
  frozen.forEach((a) => add(a, 'Frozen wallet', 'risk'))
  for (const f of result.findings ?? []) if (f.pattern === 'amount_split') add(f.evidence?.address, 'Split wallet')

  const red = new Set(frozen.filter((a) => a !== seed))
  const route = new Set(steps.slice(1).map((s, i) => `${steps[i].address}>${s.address}`))
  const known = new Set(transfers.map((t) => t.hash))
  // The reported wallet's money in from outside the trace: the payments and
  // its statement's credits (never a lookalike's dust).
  const paidIn = [
    ...(result.intake?.payments ?? []).map((p) => ({ hash: p.tx_hash, from: p.from, value_native: p.amount, timestamp: p.timestamp })),
    ...(result.statement?.credits ?? []).filter((c) => !c.lookalike).map((c) => ({ hash: c.tx, from: c.counterparty, value_native: c.amount, timestamp: c.time })),
  ].filter((t) => t.hash && t.timestamp && !known.has(t.hash) && (known.add(t.hash), true)).map((t) => ({ ...t, to: seed, outside: true }))

  const dots = []
  const others = new Set()
  for (const t of [...transfers, ...paidIn]) {
    const tone = route.has(`${t.from}>${t.to}`) ? 'go' : red.has(t.from) || red.has(t.to) ? 'risk' : ''
    const ends = t.outside ? [['in', t.to]] : [['out', t.from], ['in', t.to]]
    const placed = ends.map(([kind, address]) => ({ kind, address, lane: laneOf.get(address) ?? 'more' }))
    const both = placed.every((p) => p.lane === 'more')
    for (const p of both ? placed.slice(0, 1) : placed) {
      if (p.lane === 'more') others.add(p.address)
      dots.push({ id: `${dots.length}`, lane: p.lane, kind: p.kind, tone, t: t.timestamp, amount: t.value_native || 0, hash: t.hash, from: t.from, to: t.to })
    }
  }
  if (others.size) lanes.push({ key: 'more', name: `${others.size} more wallet${others.size === 1 ? '' : 's'}`, sub: 'the rest of the trace', label: `${others.size} more wallet${others.size === 1 ? '' : 's'}, the rest of the trace`, tone: '' })
  const biggest = Math.max(...dots.map((d) => d.amount), 1e-9)
  for (const d of dots) d.size = 6 + 12 * Math.sqrt(d.amount / biggest)
  dots.sort((a, b) => a.t - b.t)
  const times = dots.map((d) => d.t)
  return {
    lanes: lanes.filter((l) => dots.some((d) => d.lane === l.key)),
    dots,
    names: new Map([...nodes].filter(([, n]) => n.label).map(([id, n]) => [id, plain(n.label)])),
    start: istMidnight(Math.min(...times)),
    end: istMidnight(Math.max(...times)) + DAY,
  }
}

export default function TimelineLanes({ result, unit }) {
  const model = useMemo(() => buildLanes(result), [result])
  const [whole, setWhole] = useState(false)
  const [picked, setPicked] = useState(null)
  const uid = useId()
  if (!model) return null

  const days = Math.round((model.end - model.start) / DAY)
  const long = days > LONG
  const to = long && !whole ? model.start + WINDOW * DAY : model.end
  const span = (to - model.start) / DAY
  const step = STEPS.find((s) => span / s <= 14) ?? STEPS.at(-1)
  const ticks = Array.from({ length: Math.ceil(span / step) }, (_, i) => model.start + i * step * DAY)
  const x = (t) => `${((t - model.start) / (to - model.start)) * 100}%`
  const shown = model.dots.filter((d) => d.t < to)
  const byLane = model.lanes.map((l) => shown.filter((d) => d.lane === l.key))
  const chosen = shown.find((d) => d.id === picked) ?? shown.find((d) => d.tone === 'go' && d.kind === 'out') ?? shown[0]
  const who = (address) => (address ? model.names.get(address) ?? middle(address, 4, 4) : 'hidden')
  const optionId = (d) => `${uid}-dot-${d.id}`
  const describe = (d) => {
    const c = clock(d.t)
    const what = d.kind === 'out' ? `out to ${who(d.to)}` : `in from ${who(d.from)}`
    const why = d.tone === 'go' ? ', on the path to the exchange' : d.tone === 'risk' ? ', frozen wallet' : ''
    return `${c.day}, ${c.time} IST: ${num(d.amount)} ${unit} ${what}${why}`
  }

  const li = chosen ? model.lanes.findIndex((l) => l.key === chosen.lane) : -1
  const row = byLane[li] ?? []
  const i = row.indexOf(chosen)
  const go = (next) => {
    if (!next) return
    setPicked(next.id)
    document.getElementById(optionId(next))?.scrollIntoView?.({ block: 'nearest' })
  }
  // Of the dots whose hit area holds the tap, the one centred nearest it: a
  // dot under a later one's hit area is still reached. (No layout, as in a
  // test: the dot that was clicked.)
  const pickAt = (e, dots) => {
    let best = dots.find((d) => optionId(d) === e.target.id)
    let gap = Infinity
    for (const d of dots) {
      const r = document.getElementById(optionId(d))?.getBoundingClientRect()
      if (!r?.width) continue
      const dx = Math.abs(e.clientX - r.left - r.width / 2)
      const dy = Math.abs(e.clientY - r.top - r.height / 2)
      if (dx <= r.width / 2 && dy <= r.height / 2 && Math.hypot(dx, dy) < gap) [gap, best] = [Math.hypot(dx, dy), d]
    }
    if (best) setPicked(best.id)
  }
  const onKey = (e) => {
    if (!chosen) return
    let next
    if (e.key === 'ArrowRight') next = row[i + 1]
    else if (e.key === 'ArrowLeft') next = row[i - 1]
    else if (e.key === 'Home') next = row[0]
    else if (e.key === 'End') next = row.at(-1)
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const way = e.key === 'ArrowDown' ? 1 : -1
      let j = li + way
      while (byLane[j] && !byLane[j].length) j += way
      next = byLane[j]?.reduce((best, d) => (Math.abs(d.t - chosen.t) < Math.abs(best.t - chosen.t) ? d : best))
    } else return
    e.preventDefault()
    go(next)
  }

  const ist = chosen && clock(chosen.t)
  const utc = chosen && clock(chosen.t, 'UTC')
  const link = chosen && txUrl(result.explorer_url, result.chain, chosen.hash)
  const listed = result.transfers_omitted > 0 ? `${(result.transfers ?? []).length} of ${result.transfers_total} listed` : null
  return <>
    <section className="card tl-chart" aria-labelledby={`${uid}-title`}>
      <div className="tl-head">
        <h2 id={`${uid}-title`}>Every transfer, in IST</h2>
        {listed && <span className="note">{listed}</span>}
        {long && (
          <span className="seg tl-seg">
            <button type="button" className={whole ? '' : 'on'} aria-pressed={!whole} onClick={() => setWhole(false)}>First {WINDOW} days</button>
            <button type="button" className={whole ? 'on' : ''} aria-pressed={whole} onClick={() => setWhole(true)}>All {days} days</button>
          </span>
        )}
        <ul className="tl-legend">
          <li><span className="tl-key in" aria-hidden="true" />money in</li>
          <li><span className="tl-key" aria-hidden="true" />money out</li>
          <li><span className="tl-key go" aria-hidden="true" />on the path to the exchange</li>
          <li><span className="tl-key risk" aria-hidden="true" />frozen wallet</li>
          <li>size = amount</li>
        </ul>
      </div>
      <div className="tl-axis" aria-hidden="true">
        {ticks.map((t) => <span key={t} style={{ left: x(t) }}>{clock(t).short}</span>)}
      </div>
      <div className="tl-lanes" role="listbox" tabIndex={0} aria-labelledby={`${uid}-title`} aria-activedescendant={chosen ? optionId(chosen) : undefined} onKeyDown={onKey}>
        {model.lanes.map((l, li) => (
          <div className="tl-lane" role="group" aria-label={l.label} key={l.key}>
            <div className={`tl-name ${l.tone}`} aria-hidden="true">{l.name}<span className="mono">{l.sub}</span></div>
            <div className="tl-track" onClick={(e) => pickAt(e, byLane[li])}>
              {ticks.map((t) => <span className="tl-grid" key={t} style={{ left: x(t) }} aria-hidden="true" />)}
              {byLane[li].map((d) => (
                <span
                  key={d.id} id={optionId(d)} role="option" aria-selected={d === chosen} aria-label={describe(d)}
                  className={`tl-dot ${d.kind} ${d.tone}${d === chosen ? ' on' : ''}`}
                  style={{ left: x(d.t), '--d': `${d.size}px` }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
    {chosen && (
      <section className={`card tl-picked ${chosen.tone}`} aria-label="Selected transfer">
        <div aria-live="polite"><span className="micro">Selected</span><strong>{ist.day}, {ist.time} IST</strong><span className="note">{utc.time} UTC{utc.day === ist.day ? '' : ` · ${utc.day}`}</span></div>
        <div><span className="micro">From → to</span><span className="mono">{who(chosen.from)} → {who(chosen.to)}</span></div>
        <div><span className="micro">Amount</span><span>{num(chosen.amount)} {unit}</span></div>
        <div className="tl-tx"><span className="micro">Transaction</span><span className="mono">{chosen.hash?.slice(0, 32)}<wbr />{chosen.hash?.slice(32)}</span></div>
        {link && <a className="tl-open" href={link} target="_blank" rel="noreferrer">{result.explorer_url.replace(/^https?:\/\/(www\.)?/, '')} <span aria-hidden="true">↗</span></a>}
        <div className="tl-step">
          <span className="note">{i + 1} of {row.length} in this lane</span>
          <span>
            <button type="button" className="tl-open" aria-label="Earlier transfer in this lane" disabled={i <= 0} onClick={() => go(row[i - 1])}><span aria-hidden="true">‹</span> Earlier</button>
            <button type="button" className="tl-open" aria-label="Later transfer in this lane" disabled={i >= row.length - 1} onClick={() => go(row[i + 1])}>Later <span aria-hidden="true">›</span></button>
          </span>
        </div>
      </section>
    )}
  </>
}
