import { useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useMedia } from '../../phone'
import { plain, plainSentence } from '../../text'
import { bandLabel, bandOf } from '../confidence'
import { instantService } from './letterChecks'
import { KIND_ORDER, shareText, spreadColumns, victimFlowLayout } from './victimFlowLayout'
import { countFrames, particleRoutes, stagger } from './victimFlowMotion'
import './VictimFlow.css'

// The Flow tab (pack Flow): where the victim's share went, as a Sankey sized
// by the victim's money (victim_flow, backend/app/victim_flow.py), and a card
// for each place it ended with what an officer can do there. On a phone the
// cards alone, under "N% can be acted on": only what is not an upper bound,
// with the bound said apart. A display: letters and the score
// keep the conservative estimate. Every name from outside goes through plain();
// the flow's notes, Exchequer's own sentences that may quote an address,
// through plainSentence().

const H = 420
const LABEL_GAP = 24
const short = (a) => { const p = plain(a ?? ''); return p.length > 10 ? `${p.slice(0, 4)}…${p.slice(-4)}` : p }
const fmt = (v) => Number(v ?? 0).toLocaleString('en-US', !v || Math.abs(v) >= 1 ? { maximumFractionDigits: 2 } : { maximumSignificantDigits: 2 })
const day = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const RULES = [['prorata', 'Pro-rata'], ['fifo', 'FIFO'], ['libr', 'LIBR']]
const FROM = { seed_outflow: 'the reported wallet sent on', swap_output: 'the swap returned' }
const DEEPEST = 6 // the most hops a trace takes (TraceView's depth limit)
const ENDS = { mixer: 'At a mixer', bridge: 'At a bridge to another chain', privacy: 'At a privacy service' }
const STILL = '(prefers-reduced-motion: reduce)'
const easeOut = (t) => 1 - (1 - t) ** 3

/** A figure that counts up once, from zero to its own text. The text in the
 * page is always the final figure (a screen reader, a copy and a test read
 * it); while it counts, that text is see-through and the running number is
 * drawn over it by an aria-hidden mark. With reduced motion it never counts. */
function Count({ text, motion, delay = 0, ms = 1100 }) {
  const ref = useRef(null)
  useLayoutEffect(() => {
    const box = ref.current
    const frame = motion ? countFrames(text) : null
    if (!box || !frame || typeof requestAnimationFrame !== 'function') return undefined
    const run = box.lastChild
    const from = performance.now() + delay
    let raf = 0
    const done = () => { delete box.dataset.counting; delete run.dataset.n }
    const tick = (now) => {
      const t = Math.min(1, Math.max(0, (now - from) / ms))
      if (t >= 1) { done(); return }
      run.dataset.n = frame(easeOut(t))
      raf = requestAnimationFrame(tick)
    }
    box.dataset.counting = ''
    run.dataset.n = frame(0)
    raf = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(raf); done() }
  }, [text, motion, delay, ms])
  return <span className="vf-count" ref={ref}>{text}<span className="vf-run" aria-hidden="true" /></span>
}

export default function VictimFlow({ result, unit, onLetters, onWatch, onDeeper }) {
  const id = useId()
  const [rule, setRule] = useState('prorata')
  // Motion plays once as the figure opens; with reduced motion every part is
  // drawn final at once. Pause stops the loops (the lights, the glow).
  const motion = !useMedia(STILL)
  const [paused, setPaused] = useState(false)
  const flow = result.victim_flow
  // Worked out once per case: a dense case's layout takes tens of ms.
  const lay = useMemo(() => victimFlowLayout(flow, { graph: result.graph, height: H }), [flow, result.graph])
  const lights = useMemo(() => particleRoutes(lay), [lay])
  if (!lay) return null
  const bucket = Object.fromEntries(flow.buckets.map((b) => [b.kind, b]))
  const amount = (kind) => bucket[kind]?.amount ?? 0
  const stop = (kind) => (flow.stops ?? []).find((s) => s.kind === kind)
  const known = new Map((result.graph?.nodes ?? []).map((n) => [n.address, n]))
  const match = (a) => (result.risk_matches ?? []).find((m) => m.address === a)
  const hops = result.max_depth
  const deeper = hops ? Math.min(2, DEEPEST - hops) : 0
  // What reached an exchange, an instant exchanger or a held wallet; the part
  // through a wallet whose share is an upper bound is never stated as fact.
  // Worked from the amounts: the shares are rounded, the bound part is not.
  const acted = (bucket.exchange?.share ?? 0) + (bucket.instant_exchanger?.share ?? 0) + (bucket.held?.share ?? 0)
  const bounded = (kind) => bucket[kind]?.bounded_amount ?? 0
  const upTo = (kind) => (bounded(kind) > 1e-6 * flow.totals.denominator ? 'up to ' : '')
  const ACTED = ['exchange', 'instant_exchanger', 'held']
  const solid = ACTED.reduce((sum, kind) => sum + amount(kind) - bounded(kind), 0)
  const firm = solid > 1e-6 * flow.totals.denominator ? solid / flow.totals.denominator : 0
  const loose = ACTED.some(upTo) ? shareText(acted) : null
  // Said by what it is, never by how the chart draws it (a phone has none).
  const BOUND = 'counting money through wallets whose shares are only upper bounds'
  const band = bandLabel(result.confidence_detail?.band ?? bandOf(result.confidence))
  const victimAt = new Map(flow.nodes.map((n) => [n.address, n.victim_in]))
  // Each exchange address with its own share: one deposit address's label
  // never stands for money that reached another.
  const exchangeAt = bucket.exchange?.addresses ?? []
  const named = Boolean(result.exchange) && exchangeAt.includes(result.exchange_address)
  const exRows = exchangeAt.map((a) => {
    const n = known.get(a) ?? {}
    const own = named && a === result.exchange_address
    return { address: a, amount: victimAt.get(a) ?? 0, name: plain(own ? result.exchange : n.exchange ?? n.inferred_exchange), label: plain(own ? result.exchange_label : n.label) }
  })
  const exOne = exRows.length === 1 ? exRows[0] : null
  // A no-KYC swap service (an instant exchanger): a card of its own, dashed when every wallet in it is inferred.
  const instAt = bucket.instant_exchanger?.addresses ?? []
  const instOwn = Boolean(result.exchange) && instAt.includes(result.exchange_address)
  const instRows = instAt.map((a) => {
    const n = known.get(a) ?? {}
    const own = instOwn && a === result.exchange_address
    return { address: a, amount: victimAt.get(a) ?? 0, name: plain(own ? result.exchange : n.exchange ?? n.inferred_exchange), inferred: Boolean(n.inferred_exchange && !n.exchange) }
  })
  const exName = named || instOwn ? plain(result.exchange) : exOne?.name
  const exNames = [...new Set(exRows.map((r) => r.name).filter(Boolean))]
  const leftAt = bucket.left?.addresses ?? []
  const heldAt = bucket.held?.addresses ?? []
  const methods = result.tracing_methods
  const figures = methods?.figures
  const off = RULES.slice(1).filter(([key]) => figures?.[key] == null)
  const reason = (key) => plainSentence(methods?.[key]?.reason)?.replace(/\.$/, '')
  const why = !off.length ? null : off.some(([key]) => reason(key))
    ? off.map(([key, name]) => `${name}: ${reason(key) || 'not worked out for this case'}.`).join(' ')
    : `${off.map(([, name]) => name).join(' and ')} ${off.length === 1 ? 'was' : 'were'} not worked out for this case.`
  const riskEnd = (flow.stops ?? []).find((s) => ENDS[s.kind])
  // Only the hop limit's wallets are beyond the hops; the rest of the bucket
  // a time or record limit left unopened, and a deeper trace would not reach it.
  const tiny = 1e-6 * flow.totals.denominator
  const hopAmount = Math.min(stop('hop_limit')?.amount ?? 0, amount('beyond_limit'))
  const unopened = amount('beyond_limit') - hopAmount
  const allHops = hopAmount > 0 && unopened <= tiny
  const NAME = {
    exchange: exOne ? exOne.label || exOne.name || 'Exchange' : exNames.length === 1 ? `At ${exNames[0]}` : 'At exchanges',
    instant_exchanger: 'At an instant exchanger', held: 'Held', risk: ENDS[riskEnd?.kind] ?? 'At a mixer', not_followed: 'Not followed',
    other: 'Other', beyond_limit: allHops ? `Beyond ${hops} hops` : 'Not opened', left: leftAt.length === 1 ? `Left in ${short(leftAt[0])}` : `Left in ${leftAt.length} wallets`,
  }
  const SAYS = {
    exchange: 'reached an exchange', instant_exchanger: 'reached an instant exchanger', held: 'is held where it was stopped', risk: 'reached a mixer, bridge or privacy service',
    not_followed: 'was not followed', other: 'went to a swap or back up the route', beyond_limit: allHops ? `is beyond the trace's ${hops} hops` : 'is in wallets the trace did not open',
    left: `is left in ${leftAt.length === 1 ? 'a wallet' : `${leftAt.length} wallets`}`,
  }
  const summary = `Of ${fmt(flow.totals.denominator)} ${unit} ${FROM[flow.totals.basis] ?? 'the victim reported paying'}: ${lay.buckets.map((b) => `${fmt(b.amount)} ${unit} ${SAYS[b.kind]}`).join(', ')}.`
  const top = (y) => ({ top: `${y}px` })
  const hopLabels = lay.hop1.filter((h) => !h.gap)
  const mid = (n) => (n.y0 + n.y1) / 2
  const [hopYs, bucketYs] = spreadColumns([hopLabels.map(mid), lay.buckets.map(mid)], LABEL_GAP, H)
  const chip = (n, text) => `${text} · ${fmt(n.amount)}${n.risk ? ` · ${plain(n.risk)}` : ''}`
  const barOrder = [...lay.buckets].sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind))
  let askTether = true // one Ask Tether: every one opens the same letter
  const tether = (address) => {
    if (!askTether || plain(match(address)?.issuer) !== 'Tether') return null
    askTether = false
    return <button type="button" onClick={() => onLetters('tether')}>Ask Tether</button>
  }
  // A card's figure; on a phone, with a bar of its part of the start.
  // Each card's figure counts up as its card comes in (the cards cascade 60 ms apart).
  const figure = (v, after = '', before = '') => <>
    <p className="vf-amount">{before}<b><Count text={fmt(v)} motion={motion} delay={stagger(cards.length, 450)} /></b> {unit}{after}</p>
    <span className="vf-meter" aria-hidden="true"><span style={{ width: `${Math.min(100, (v / flow.totals.denominator) * 100)}%` }} /></span>
  </>

  const cards = []
  if (amount('exchange') > 0) cards.push(
    <article key="exchange" className="vf-card go">
      <div className="vf-card-top"><h3>At an exchange</h3>{named && band && <span className="vf-tag">{band} · {result.attribution_inferred ? 'inferred' : 'exact label'}</span>}</div>
      {figure(amount('exchange'), '', upTo('exchange'))}
      {exOne ? <>
        <p className="vf-name">{[exOne.name, exOne.label].filter(Boolean).join(' · ')}</p>
        <p className="mono vf-address">{plain(exOne.address)}</p>
      </> : <ul className="vf-rows">{exRows.map((r) => (
        <li key={r.address}>
          <span className="vf-name">{[r.name, r.label].filter(Boolean).join(' · ') || 'Exchange'}</span>
          <span className="mono vf-address">{plain(r.address)}</span>
          <span className="num">{fmt(r.amount)} {unit}</span>
        </li>))}
      </ul>}
      {flow.lead?.reached != null && Math.abs(flow.lead.reached - amount('exchange')) > 0.005 && <p className="note">{fmt(flow.lead.reached)} {unit} of it along the route the finding names.</p>}
      {/* The urgent freeze letter: it goes first (the Letters tab falls back to the information letter). */}
      {result.exchange && !instOwn && <button type="button" className="primary" onClick={() => onLetters('exchange-freeze')}>Draft letter to {plain(result.exchange)}</button>}
    </article>)
  if (amount('instant_exchanger') > 0) cards.push(
    <article key="instant" className={`vf-card vf-instant${instRows.every((r) => r.inferred) ? ' inferred' : ''}`}>
      <div className="vf-card-top"><h3>At an instant exchanger</h3>{instOwn && band && <span className="vf-tag">{band} · {result.attribution_inferred ? 'inferred' : 'exact label'}</span>}</div>
      {figure(amount('instant_exchanger'), '', upTo('instant_exchanger'))}
      <ul className="vf-rows">{instRows.map((r) => (
        <li key={r.address}>
          <span className="vf-name">{[r.name || 'Swap service', r.inferred && 'inferred'].filter(Boolean).join(' · ')}</span>
          <span className="mono vf-address">{plain(r.address)}</span>
          {instRows.length > 1 && <span className="num">{fmt(r.amount)} {unit}</span>}
        </li>))}
      </ul>
      <p className="note">A swap service that checks no identity. It can say which order this paid for and where the payout went.</p>
      {/* Named as the letter is: the case's own exchange first, else the first one reached, not the largest. */}
      <button type="button" className="primary" onClick={() => onLetters('instant-freeze')}>Draft letter to {instantService(result) ?? ((instOwn ? plain(result.exchange) : instRows[0]?.name) || 'the swap service')}</button>
    </article>)
  // A frozen wallet that still holds money has its Held card, not this one too.
  for (const p of (flow.passed_through ?? []).filter((x) => !heldAt.includes(x.address))) {
    const issuer = plain(match(p.address)?.issuer)
    const frozenOn = match(p.address)?.frozen_on
    cards.push(
      <article key={p.address} className="vf-card risk">
        <h3>{p.category === 'frozen' ? `Through a wallet ${issuer || 'its issuer'} froze` : `Through a ${plain(p.category)} wallet`}</h3>
        {figure(p.victim_in, ' reached it')}
        <p className="mono vf-address">{plain(p.address)}{frozenOn ? ` · frozen ${day(frozenOn)}` : ''}</p>
        {p.category === 'sanctioned' && <p className="note">A sanctions listing freezes nothing: the money can still move unless a token's issuer has frozen it.</p>}
        {tether(p.address)}
      </article>)
  }
  const note = (kind, text) => amount(kind) > 0 && cards.push(
    <article key={kind} className={`vf-card ${kind === 'risk' ? 'risk' : 'quiet'}`}><h3>{NAME[kind]}</h3>{figure(amount(kind))}<p className="note">{text}</p></article>)
  if (amount('held') > 0) {
    const at = heldAt[0]
    const category = plain(known.get(at)?.risk_category ?? 'stopped')
    const issuer = plain(match(at)?.issuer)
    const came = heldAt.length === 1 ? (flow.passed_through ?? []).find((p) => p.address === at)?.victim_in : null
    const frozenOn = match(at)?.frozen_on
    cards.push(
      <article key="held" className="vf-card risk">
        <h3>{category === 'frozen' ? `Held at a wallet ${issuer || 'its issuer'} froze` : `Held at a ${category} wallet`}</h3>
        {figure(amount('held'), came > amount('held') + tiny ? ` of the ${fmt(came)} ${unit} that reached it` : '', upTo('held'))}
        <p className="mono vf-address">{plain(at)}{heldAt.length > 1 ? ` and ${heldAt.length - 1} more` : ''}{frozenOn ? ` · frozen ${day(frozenOn)}` : ''}</p>
        {heldAt.map(tether).find(Boolean)}
      </article>)
  }
  note('risk', plainSentence(riskEnd?.note) ?? '')
  if (hopAmount > 0) cards.push(
    <article key="beyond" className="vf-card dashed">
      <h3>Beyond the trace's {hops} hops</h3>{figure(hopAmount)}
      <p className="note">Wallets at the trace's last hop, reached but not opened.</p>
      {deeper > 0 && <button type="button" onClick={() => onDeeper(hops + deeper)}>Trace {deeper} hop{deeper === 1 ? '' : 's'} deeper</button>}
    </article>)
  if (unopened > tiny) cards.push(
    <article key="unopened" className="vf-card dashed">
      <h3>Not opened</h3>{figure(unopened)}
      <p className="note">Wallets the trace reached but did not open: a time or record limit stopped it short of its hop limit.</p>
    </article>)
  if (amount('left') > 0) cards.push(
    <article key="left" className="vf-card quiet vf-left">
      <div><h3>{NAME.left}</h3>{figure(amount('left'))}</div>
      <button type="button" onClick={() => onWatch(leftAt[0])}>Watch</button>
    </article>)
  note('not_followed', plainSentence(stop('fanout_limit')?.note) ?? 'Sent on to destinations the trace did not follow.')
  note('other', 'A swap, or money that came back to a wallet earlier on the route, counted once.')

  // Only money at an exchange or an instant exchanger glows: green is for exchanges and the route.
  const glows = amount('exchange') + amount('instant_exchanger') > 0
  const looping = motion && (glows || lights.length > 0)
  const pause = (where) => looping && (
    <button type="button" className={`vf-pause ${where}`} aria-pressed={paused} onClick={() => setPaused((p) => !p)}>
      <span className="vf-pause-mark" aria-hidden="true" />Pause motion
    </button>)
  // The two stages the ribbons are drawn in, left to right: to the first hop, then on to where it ended.
  const stages = [lay.ribbons.map((r, i) => [r, i]).filter(([r]) => r.x0 < lay.width / 2), lay.ribbons.map((r, i) => [r, i]).filter(([r]) => r.x0 >= lay.width / 2)]
  const ribbon = ([r, i]) => <path key={i} className={`vf-ribbon vf-${r.colour} vf-${r.style}`} d={r.path} />
  const at = (d) => ({ '--vf-d': `${d}ms` })
  const rulePos = Math.max(0, RULES.findIndex(([key]) => key === rule))

  return (
    <div className="vf-box"><div className={`vflow${motion ? ' vf-motion' : ''}${paused ? ' vf-paused' : ''}`}>
      <div className={`vf-phone vf-hero${glows ? ' vf-glow' : ''}`}>
        <div className="vf-hero-top"><p className="vf-kicker">Where the money is now</p>{pause('vf-pause-phone')}</div>
        <h2><Count text={shareText(firm)} motion={motion} delay={200} /> can be acted on</h2>
        {loose && <p className="note">up to {loose} {BOUND}</p>}
      </div>
      <section className="card vf-chart" aria-labelledby={`${id}-title`}>
        <div className="vf-head">
          <h2 id={`${id}-title`}>Where the victim's share went</h2>
          <div className="vf-tools">
            {pause('vf-pause-chart')}
            <fieldset className="vf-rule" aria-describedby={why ? `${id}-rule` : undefined}>
              <legend className="visually-hidden">Tracing rule</legend>
              {/* The chosen rule's pill: it slides to the rule picked. */}
              <span className="vf-rule-pill" aria-hidden="true" style={{ '--vf-at': rulePos }} />
              {RULES.map(([key, name]) => (
                <label key={key} className={rule === key ? 'on' : ''}>
                  <input type="radio" name={`${id}-rule`} checked={rule === key} disabled={key !== 'prorata' && figures?.[key] == null} onChange={() => setRule(key)} />{name}
                </label>
              ))}
            </fieldset>
          </div>
        </div>
        {why && <p className="note" id={`${id}-rule`}>{why}</p>}
        {rule !== 'prorata' && <p className="note">By {RULES.find(([k]) => k === rule)[1]}, {fmt(figures[rule])} {unit} reached {exName || 'the exchange'}. The drawing stays pro-rata, the one rule worked out on every branch.</p>}
        <div className="vf-cols" aria-hidden="true"><span>Reported wallet</span><span>Hop 1</span><span>Where it is now</span></div>
        <div className="vf-stage" role="img" aria-label={summary} style={{ height: H }}>
          <svg viewBox={`0 0 ${lay.width} ${H}`} preserveAspectRatio="none" aria-hidden="true">
            <g className="vf-stage1">{stages[0].map(ribbon)}</g>
            <g className="vf-stage2">{stages[1].map(ribbon)}</g>
            {/* The columns grow in: the reported wallet, then hop 1, then where it ended, 60 ms apart. */}
            {[[lay.seed, 100], ...hopLabels.map((h, i) => [h, stagger(i, 300)]), ...lay.buckets.map((b, i) => [b, stagger(i, 1000)])].map(([n, d], i) => (
              <rect key={i} className={`vf-bar${n.risk ? ' risk' : ''}${n.colour === 'go' ? ' go' : ''}`} x={n.x} width={lay.bar}
                y={Math.min(n.y0, (n.y0 + n.y1) / 2 - 1)} height={Math.max(2, n.y1 - n.y0)} style={at(d)} />
            ))}
          </svg>
          {/* A few slow lights along the ribbons, after they are drawn; green only on the way to an exchange. */}
          {motion && lights.length > 0 && <div className="vf-lights" aria-hidden="true">{lights.map((l) => (
            <span key={l.key} className={`vf-light ${l.colour}`} style={{ '--x0': `${l.x[0]}%`, '--x1': `${l.x[1]}%`, '--x2': `${l.x[2]}%`, '--y0': `${l.y[0]}px`, '--y1': `${l.y[1]}px`, '--y2': `${l.y[2]}px`, '--vf-d': `${l.delay}s` }}>
              <span><i /></span>
            </span>))}
          </div>}
          <span className={`vf-chip mono vf-at-seed${lay.seed.risk ? ' risk' : ''}`} style={{ ...top((lay.seed.y0 + lay.seed.y1) / 2), ...at(350) }}>{chip(lay.seed, short(lay.seed.address))}</span>
          {hopLabels.map((h, i) => (
            <span key={h.id} className={`vf-chip mono vf-at-hop${h.risk ? ' risk' : h.lead ? ' go' : ''}`} style={{ ...top(hopYs[i]), ...at(stagger(i, 700)) }}>
              {chip(h, h.address ? short(h.address) : `${h.count} more wallets`)}
              {h.via?.[0] && <span className="vf-via"> · {fmt(h.via[0].amount)} via {plain(h.via[0].category)} {plain(h.via[0].address).slice(0, 4)}</span>}
            </span>
          ))}
          {lay.buckets.map((b, i) => <span key={b.kind} className={`vf-chip vf-at-end ${b.colour}`} style={{ ...top(bucketYs[i]), ...at(stagger(i, 1500)) }}>{NAME[b.kind]} · {fmt(b.amount)}</span>)}
        </div>
        <div className="vf-foot">
          {/* The share bar fills in stages: what can be acted on first, then the rest, in its order. */}
          <div className="vf-bar-all" aria-hidden="true">{barOrder.map((b, i) => <span key={b.kind} className={`${b.colour} ${b.kind}`} style={{ width: `${(b.amount / flow.totals.denominator) * 100}%`, ...at(stagger(i, 1700, 300)) }} />)}</div>
          <p><b><Count text={shareText(firm)} motion={motion} delay={1700} /></b> reached a place someone can act on{loose && <>, up to <b><Count text={loose} motion={motion} delay={2000} /></b> {BOUND}</>}</p>
          {hopAmount > 0 && <p><b><Count text={shareText(hopAmount / flow.totals.denominator)} motion={motion} delay={2000} /></b> is beyond the trace's {hops} hops</p>}
          <p className="note">widths are the victim's money, not the totals that passed through</p>
        </div>
      </section>
      <div className="vf-cards">{cards}</div>
      {(named || instOwn) && band && <p className="vf-phone vf-band"><span className="vf-tag">{band}</span> that it reached {exName} · not a probability</p>}
      <div className="card vf-notes">
        {flow.stops?.length > 0 && <>
          <h3>Where tracing stopped</h3>
          <ul>{flow.stops.map((s) => <li key={`${s.kind}${s.inferred}`}><span className="num">{fmt(s.amount)} {unit}</span> <span>{plainSentence(s.note)}</span></li>)}</ul>
        </>}
        {(flow.notes ?? []).map((n) => <p className="note" key={n}>{plainSentence(n)}</p>)}
      </div>
    </div></div>
  )
}
