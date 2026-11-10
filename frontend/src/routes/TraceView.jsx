import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { fetchCase, fetchRecordedDemo, fetchRelatedCases, runTrace, stopTraceJob, traceJobRemembered } from '../api'
import GraphView from '../components/GraphView'
import FlowView from '../components/FlowView'
import ExportButton from '../components/ExportButton'
import Present from '../components/Present'
import { useCrumb } from '../components/AppShell'
import CaseTabs from '../components/case/CaseTabs'
import Tracing from '../components/case/Tracing'
import EvidenceTab from '../components/case/EvidenceTab'
import TimelineTab from '../components/case/TimelineTab'
import LettersTab from '../components/case/LettersTab'
import VictimFlow from '../components/case/VictimFlow'
import { useCaseTab } from './caseTab'
import './TraceView.css'
import { plain } from '../text'
import { BAND_RULE, bandLabel, bandOf } from '../components/confidence'
import EntitiesTab from '../components/case/EntitiesTab'
import { Address, PATTERN_NAME, RISK_NAME, middle, mmss, num, txUrl, when } from '../components/case/format'
const COMPONENT_NAME = {
  hop_proximity: 'Hop proximity',
  amount_correlation: 'Amount correlation',
  match_directness: 'Match directness',
}

/** OFAC stamps its list "MM/DD/YYYY"; an Indian reader parses that as day-first.
 * Spell the month out so "09/04/2026" cannot be read as 9 April. */
function unambiguousDate(text) {
  return String(text ?? '').replace(/(\d{2})\/(\d{2})\/(\d{4})/, (_, mm, dd, yyyy) => {
    const d = new Date(Date.UTC(+yyyy, +mm - 1, +dd))
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  })
}

// A whole number from the URL, kept within the backend's range; `fallback`
// when absent or not a number.
function clampInt(raw, lo, hi, fallback) {
  const n = raw == null || raw === '' ? NaN : Math.trunc(Number(raw))
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : fallback
}
// A payment hash as the backend accepts it.
const PAY_HASH = /^(0x)?[0-9a-fA-F]{64}$/
// The cap the confirmation card offers, as on the trace form.
const LINK_BUDGET_SECONDS = 90

const Icon = ({ d, size }) => (
  <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" style={size ? { width: size, height: size } : undefined}>
    {d.map((path) => <path key={path} d={path} />)}
  </svg>
)
const ICONS = {
  alert: ['M12 3 2 20h20L12 3z', 'M12 10v4', 'M12 17.5h.01'],
  copy: ['M9 9h10v10H9z', 'M5 15V5h10'],
  redo: ['M4 12a8 8 0 1 1 2.3 5.7', 'M4 18v-6h6'],
  present: ['M3 5h18v11H3z', 'M8 20h8', 'M12 16v4'],
}

// A count and its noun: "1 wallet", "30 wallets".
const many = (n, noun) => <><b>{n}</b> {noun}{n === 1 ? '' : 's'}</>
// A date as it was in India, spelled out: "15 Nov 2023".
const dayIST = (seconds) => new Date(seconds * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' })

const METHOD_NAME = { fifo: 'FIFO', prorata: 'pro-rata', libr: 'LIBR' }

// R4: how much reached the exchange by each tracing rule, and the figure a
// letter states. Shown only when the trace computed more than one method.
function MethodRange({ methods, unit }) {
  const figures = methods?.figures ?? {}
  const names = ['fifo', 'prorata', 'libr'].filter((m) => figures[m] != null)
  if (names.length < 2 || !methods.range) return null
  const same = methods.range.low === methods.range.high
  return (
    <div className="method-range">
      {same
        ? <>All {names.length} tracing rules agree: <span className="num">{num(methods.range.low)} {unit}</span></>
        : <>By tracing rule: <span className="num">{num(methods.range.low)} to {num(methods.range.high)} {unit}</span></>}
      {' · '}{names.map((m) => `${METHOD_NAME[m]} ${num(figures[m])}`).join(' · ')}
      {!same && <span className="note"> · a letter states the smallest, {num(methods.conservative)} {unit} ({METHOD_NAME[methods.conservative_method]})</span>}
    </div>
  )
}

/** What a /trace link would run, with a button to run it. Shown instead of
 * starting the trace when the link was opened rather than started here. */
function ConfirmTrace({ address, chain, asset, depth, direction, budget, hashes, onRun }) {
  const [capped, setCapped] = useState(!budget)
  const bad = hashes.filter((h) => !PAY_HASH.test(h))
  return (
    <section className="card confirm-trace" aria-labelledby="confirm-trace-title">
      <div className="body">
        <span className="micro">This link asks for a new trace</span>
        <h2 id="confirm-trace-title">Run this trace?</h2>
        <p className="note">Opening a trace link does not start it. A trace reads the chain under this browser's key and counts against the hourly allowance, so check what it will do first.</p>
        <div className="kv"><span className="k">Address</span><span className="v mono confirm-address">{address}</span></div>
        <div className="kv"><span className="k">Chain</span><span className="v">{chain} · {asset}</span></div>
        <div className="kv"><span className="k">Direction</span><span className="v">{direction === 'incoming' ? 'Who paid in' : 'Where it went'}</span></div>
        <div className="kv"><span className="k">Depth</span><span className="v">{depth} hop{depth === 1 ? '' : 's'}</span></div>
        {budget && <div className="kv"><span className="k">Time limit</span><span className="v mono">{mmss(budget)}</span></div>}
        {hashes.length > 0 && (
          <div className="kv">
            <span className="k">Payments</span>
            <ul className="v confirm-hashes">
              {hashes.map((h) => (
                <li key={h} className="mono">{middle(h)}{bad.includes(h) ? <span className="error-line"> · not a transaction hash</span> : null}</li>
              ))}
            </ul>
          </div>
        )}
        {!budget && (
          <label className="confirm-cap">
            <input type="checkbox" checked={capped} onChange={(e) => setCapped(e.target.checked)} />
            Stop after <span className="mono">1:30</span>
          </label>
        )}
        <div className="verify-actions">
          <button className="primary" disabled={bad.length > 0} onClick={() => onRun(capped)}>Run this trace</button>
          <Link to="/" className="quiet-link">Back to the console</Link>
        </div>
      </div>
    </section>
  )
}

// A wallet a link asks the watch panel to offer, only when the case's flow
// leaves some of the victim's money there: a link alone says nothing of a case.
function flowWallet(result, address) {
  const flow = result.victim_flow
  if (!address || flow?.status !== 'estimated') return null
  return (flow.buckets ?? []).some((b) => b.kind === 'left' && b.amount > 0 && b.addresses?.includes(address)) ? address : null
}

export default function TraceView() {
  // One component serves all three routes. /trace/:address runs a fresh
  // traversal; /case/:caseId opens what was stored, and /demo/:demoNo a
  // recorded DEMO.md trace, both without touching the chain.
  const { address: routeAddress, caseId, demoNo } = useParams()
  const [params] = useSearchParams()
  const [tab, setTab] = useCaseTab()
  const navigate = useNavigate()
  const location = useLocation()
  const recorded = Boolean(demoNo)
  const stored = Boolean(caseId) || recorded
  // A trace that has just finished arrives here by redirect with its result
  // in the navigation state, so the case view does not fetch what it already
  // holds. Distinguished from an archived case only in the header pill.
  const justTraced = Boolean(caseId) && location.state?.result?.case_id === caseId

  const chain = params.get('chain') || 'ethereum'
  const asset = params.get('asset') || 'ETH'
  const depth = clampInt(params.get('depth'), 1, 6, 4)
  const requestedDirection = params.get('direction') || 'outgoing'
  // Optional wall-clock cap, in seconds; absent means the trace runs its course.
  const budget = Number(params.get('budget')) > 0 ? clampInt(params.get('budget'), 10, 600, null) : null
  // R1: the victim's payment hashes, from the URL; the NCRP number and the
  // victim's own wallet only ever travel in the navigation state (see TraceForm).
  const pay = params.get('pay') || ''
  const ncrpAck = location.state?.ncrpAck || null
  const victimAddress = location.state?.victimAddress || null
  // A trace link alone never starts a trace: it would run under whoever opens
  // it (their key, their access code, their hourly allowance) with whatever
  // the link asks for. The form and Re-trace say they started it here; a
  // reload of a trace this tab is running re-attaches without asking.
  const startedHere = location.state?.startedHere === true
  const traceParams = {
    address: routeAddress, maxDepth: depth, chain, asset, direction: requestedDirection, timeBudgetSeconds: budget,
    payments: pay ? pay.split(',').filter(Boolean) : [], ncrpAck, victimAddress,
  }
  const needsConfirm = !stored && !justTraced && !startedHere && !traceJobRemembered(traceParams)

  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [elapsed, setElapsed] = useState(0)
  // What the background trace reports as it runs: stage, hop, addresses read.
  const [progress, setProgress] = useState(null)
  // The running job, so the person who started the trace can stop it.
  const [jobId, setJobId] = useState(null)
  const [stopping, setStopping] = useState(false)
  const [revealed, setRevealed] = useState(0)
  const [showAll, setShowAll] = useState(false)
  const [view, setView] = useState('flow') // 'flow' | 'bubbles'
  const [everyWallet, setEveryWallet] = useState(false)
  // Present mode: the case as four big screens. P opens it, Esc closes it.
  const [presenting, setPresenting] = useState(false)
  const timers = useRef([])

  // Stored cases that share an intermediary with this one (GET
  // /cases/correlate). Loaded after the trace, from the case store only; a
  // failure here must not disturb the trace.
  const [correlation, setCorrelation] = useState(null)
  const related = correlation?.related_cases ?? []
  useEffect(() => {
    setCorrelation(null)
    if (!result?.case_id) return undefined
    let cancelled = false
    fetchRelatedCases(result.case_id)
      .then((r) => { if (!cancelled) setCorrelation(r) })
      .catch(() => { if (!cancelled) setCorrelation({ failed: true }) })
    return () => { cancelled = true }
  }, [result?.case_id])

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(null); setResult(null); setRevealed(0); setElapsed(0); setShowAll(false)
    const started = Date.now()
    const tick = setInterval(() => setElapsed((Date.now() - started) / 1000), 200)
    if (justTraced) {
      setResult(location.state.result); setLoading(false); clearInterval(tick)
      return undefined
    }
    setProgress(null); setJobId(null); setStopping(false)
    if (needsConfirm) { setLoading(false); clearInterval(tick); return undefined }
    const request = recorded
      ? fetchRecordedDemo(demoNo)
      : stored
      ? fetchCase(caseId)
      : runTrace(
        traceParams,
        (snap) => {
          if (cancelled) return
          if (snap?.job_id) setJobId(snap.job_id)
          if (snap?.progress) setProgress(snap.progress)
        },
      )
    request
      .then((data) => {
        if (cancelled) return
        if (stored) { setResult(data); setLoading(false); return }
        // Not stored (the store is full, or the save failed): there is no
        // case page to open, so show the result here with its warning.
        if (!data.case_id) { setResult(data); setLoading(false); return }
        // The trace is stored the moment it completes, so the URL becomes the
        // case's own. A refresh or the back button then reopens the stored
        // case instead of running the traversal again -- another wait on the
        // provider and a duplicate row in the case store.
        navigate(`/case/${data.case_id}${tab === 'flow' ? '' : `?tab=${tab}`}`, { replace: true, state: { result: data } })
      })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false) } })
      .finally(() => clearInterval(tick))
    return () => {
      cancelled = true
      clearInterval(tick)
      timers.current.forEach(clearTimeout)
      timers.current = []
    }
  }, [stored, caseId, demoNo, routeAddress, chain, asset, depth, requestedDirection, budget, pay, needsConfirm]) // eslint-disable-line react-hooks/exhaustive-deps

  // Hops, ordered the way the traversal found them: nearest the seed first,
  // then by value within a hop.
  const hops = useMemo(() => {
    if (!result) return []
    const byId = new Map(result.graph.nodes.map((n) => [n.id, n]))
    const onPath = new Set()
    const path = result.trace_path ?? []
    for (let i = 0; i < path.length - 1; i += 1) onPath.add(`${path[i].address}>${path[i + 1].address}`)
    const backwards = result.direction === 'incoming'
    return result.graph.edges
      .map((e) => {
        const to = byId.get(e.target) ?? {}
        const from = byId.get(e.source) ?? {}
        return {
          ...e,
          // How far from the reported address this transfer sits: the far end
          // of the edge, which is the sender on a reverse trace.
          hop: (backwards ? from.depth : to.depth) ?? 1,
          toLabel: plain(to.label),
          toKind: to.risk_category ? 'red' : to.exchange ? 'green' : '',
          onPath: onPath.has(`${e.source}>${e.target}`),
        }
      })
      .sort((a, b) => a.hop - b.hop || b.value_native - a.value_native)
  }, [result])

  // Reveal in sequence once the data lands: the order the traversal found it.
  useEffect(() => {
    timers.current.forEach(clearTimeout)
    timers.current = []
    if (!hops.length) return undefined
    const step = hops.length > 60 ? 6 : 20
    for (let i = 1; i <= hops.length; i += 1) timers.current.push(setTimeout(() => setRevealed(i), i * step))
    return () => timers.current.forEach(clearTimeout)
  }, [hops])

  const address = routeAddress ?? result?.address ?? ''
  useCrumb(result ? middle(plain(address)) : null)
  const reverse = (result?.direction ?? requestedDirection) === 'incoming'
  // Contract v2 (docs/contracts/case.md): a payment trace started from the
  // victim's payments; anything else followed the wallet's own history.
  const paymentTrace = result?.intake?.mode === 'payment'
  const payments = result?.intake?.payments ?? []
  // A hash that carried several transfers has one entry per transfer (leg),
  // so payments are counted by hash. A copy for anyone but the officer who
  // traced the case has the hashes withheld (backend/app/case_privacy.py):
  // each transfer is then its own row.
  const paidByHash = useMemo(() => {
    const byHash = new Map()
    for (const [i, p] of payments.entries()) {
      const key = p.tx_hash ?? `withheld-${i}`
      const row = byHash.get(key) ?? { key, tx_hash: p.tx_hash, timestamp: p.timestamp, amount: 0, legs: 0, senders: [], labels: [], checks: [], found_by: p.found_by }
      row.amount += p.amount || 0
      row.legs += 1
      if (p.from && !row.senders.includes(p.from)) row.senders.push(p.from)
      if (p.payer_label && !row.labels.includes(p.payer_label)) row.labels.push(p.payer_label)
      row.checks.push(p.payer_is_victim)
      byHash.set(key, row)
    }
    // Any leg from another wallet marks the payment; all from the victim's clears it.
    return [...byHash.values()].map((r) => ({
      ...r, payerIsVictim: r.checks.includes(false) ? false : r.checks.length && r.checks.every((c) => c === true) ? true : null,
    }))
  }, [payments])
  const paymentCount = paidByHash.length
  const hashesWithheld = payments.length > 0 && payments.every((p) => !p.tx_hash)
  const windowStart = payments.length ? Math.min(...payments.map((p) => p.timestamp || Infinity)) : null
  const ncrp = result?.intake?.ncrp_ack
  const hopLimit = result?.max_depth ?? (stored ? null : depth)
  // Wallets the issuer froze, counted per issuer: "2 frozen by Tether".
  const frozenBy = Object.entries((result?.risk_matches ?? []).filter((m) => m.category === 'frozen').reduce((by, m) => {
    const issuer = plain(m.issuer) || 'the issuer'
    return { ...by, [issuer]: (by[issuer] ?? 0) + 1 }
  }, {}))
  const unit = result?.asset ?? result?.native_symbol ?? asset
  const tracedAt = result?.created_at ? result.created_at.replace('T', ' ').slice(0, 16) : null
  const riskMatches = result?.risk_matches ?? []
  const swaps = result?.swaps ?? []
  const followOns = (result?.follow_ons ?? []).filter((f) => f.result)
  const followed = result?.followed_attribution
  const inferred = result?.inferred_deposits ?? []
  const components = result?.confidence_detail?.components ?? []
  // What the score cannot see, as the report lists it under its limitations.
  const caveats = result?.confidence_detail?.caveats ?? []
  // Pro-rata started from at most the victim's payments or the swap's output.
  const capped = result?.prorata?.seed_cap?.applied ? result.prorata.seed_cap : null
  const path = result?.trace_path ?? []
  const pathHashes = path.reduce((n, step) => n + (step.tx_hashes?.length ?? 0), 0)
  const primaryInference = inferred.find((m) => m.address === result?.exchange_address)
  // The rows worth reading first: the attributed path, anything flagged or
  // red, any swap. With no exchange, the largest transfers instead.
  const notable = useMemo(() => {
    const picked = hops.filter((h) => h.onPath || h.toKind === 'red' || h.swap || h.flags?.length)
    return picked.length ? picked : hops.slice(0, 12)
  }, [hops])
  const visible = showAll ? hops : notable
  const shown = visible.slice(0, revealed)

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'p' && e.key !== 'P') return
      if (e.target && /input|textarea|select/i.test(e.target.tagName)) return
      if (result && !presenting) { e.preventDefault(); setPresenting(true) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [result, presenting])

  // The case traced again, at its own depth or deeper. Re-trace says it was
  // started here; a deeper trace from a Flow card asks first (ConfirmTrace),
  // as it spends the allowance.
  const traceAgain = useCallback((deeper) => {
    if (!result) return
    const q = new URLSearchParams({
      chain: result.chain, asset: result.asset,
      depth: String(deeper ?? result.max_depth ?? result.depth_reached ?? 3), direction: result.direction ?? 'outgoing',
    })
    if (result.time_budget_seconds) q.set('budget', String(result.time_budget_seconds))
    // A payment case is re-traced from the same payments (public chain data).
    const hashes = [...new Set((result.intake?.mode === 'payment' ? result.intake.payments ?? [] : []).map((p) => p.tx_hash).filter(Boolean))]
    if (hashes.length) q.set('pay', hashes.join(','))
    navigate(`/trace/${result.address}?${q}`, deeper ? undefined : { state: { startedHere: true } })
  }, [navigate, result])
  // A Flow card's action opens another view and puts the keyboard there,
  // unless the view already took it (the letter the card asked for).
  const jump = useRef(null)
  const openTab = (to, asks) => { jump.current = to; setTab(to, asks) }
  useEffect(() => {
    if (jump.current !== tab) return
    jump.current = null
    const panel = document.querySelector('.case-tabs [role="tabpanel"]:not([hidden])')
    if (panel && !panel.contains(document.activeElement)) panel.focus()
  }, [tab])

  // Run the trace a link asked for, once the officer has seen what it does.
  const confirmRun = useCallback((capped) => {
    const q = new URLSearchParams(params)
    q.set('depth', String(depth))
    if (budget) q.set('budget', String(budget))
    else if (capped) q.set('budget', String(LINK_BUDGET_SECONDS))
    else q.delete('budget')
    navigate(`${location.pathname}?${q}`, { replace: true, state: { ...(location.state ?? {}), startedHere: true } })
  }, [navigate, params, depth, budget, location.pathname, location.state])

  // Every wallet and transfer, by hop or as bubbles: the Flow tab when the
  // case has no victim flow, and a click away under it when it has one.
  const moneyFlow = result && (
    <div className="card graph-card">
      <div className="head">
        <span className="micro">Money flow · {result.graph.nodes.length} addresses · {result.graph.edges.length} transfers</span>
        <span className="seg">
          <button className={view === 'flow' ? 'on' : ''} onClick={() => setView('flow')}>By hop</button>
          <button className={view === 'bubbles' ? 'on' : ''} onClick={() => setView('bubbles')}>Bubbles</button>
        </span>
      </div>
      {view === 'flow'
        ? <FlowView data={result.graph} tracePath={result.trace_path} unit={unit} direction={result.direction} />
        : <div className="stage"><GraphView data={result.graph} tracePath={result.trace_path} unit={unit} /></div>}
    </div>
  )

  return (
    <div className="results">
      {presenting && result && <Present result={result} related={related} unit={unit} onClose={() => setPresenting(false)} />}
      {/* A case's pills describe it, so none until it has loaded: a broken
          link must not look like an archived Ethereum case. */}
      {result && <header className="case-top">
        <div className="case-top-row">
          <h1 className="subject">
            <span className="micro">{reverse ? 'Reported address (funded by)' : 'Reported address'}</span>
            <Address value={address} head={12} tail={10} />
          </h1>
          <div className="actions">
            {stored && (
              <button onClick={() => traceAgain()} title="Run the traversal again against current chain data"><Icon d={ICONS.redo} />{recorded ? 'Trace live' : 'Re-trace'}</button>
            )}
            <button className="icon-btn" onClick={() => setPresenting(true)} title="The case as four big screens (P)"><Icon d={ICONS.present} size={16} /><span className="visually-hidden">Present</span></button>
            {result.case_id && <ExportButton caseId={result.case_id} address={address} icon />}
          </div>
        </div>
        <div className="case-pills">
          <span className="case-pill"><b>{result.chain_name ?? chain}</b> {unit}</span>
          {paymentTrace && result.reported_amount > 0 && <span className="case-pill"><b>{num(result.reported_amount)}</b> {unit} paid{windowStart > 0 && windowStart !== Infinity ? ` · ${dayIST(windowStart)}` : ''}</span>}
          {hopLimit > 0 && <span className="case-pill">{many(hopLimit, 'hop')}</span>}
          <span className="case-pill">{many(result.graph.nodes.length, 'wallet')}</span>
          <span className="case-pill">{many(result.graph.edges.length, 'transfer')}</span>
          {frozenBy.map(([issuer, n]) => <span className="case-pill risk" key={issuer}><b>{n}</b> frozen by {issuer}</span>)}
          {reverse && <span className="case-pill" title="Incoming transfers walked backwards to the addresses that funded this one">Reverse trace</span>}
          {result.time_budget_seconds > 0 && <span className="case-pill" title="The walk stopped expanding once this much time was spent">{mmss(result.time_budget_seconds)} cap</span>}
          {recorded && <span className="case-pill" title="A verified trace as it came out when recorded. Live data moves; Trace live runs it again now.">Verified example {String(demoNo).padStart(2, '0')}{tracedAt ? ` · ${tracedAt.slice(0, 10)}` : ''}</span>}
          {stored && !recorded && !justTraced && <span className="case-pill" title="Loaded from the case store — the evidence as it stood, not re-traced">Archived{tracedAt ? ` · ${tracedAt}` : ''}</span>}
          {justTraced && <span className="case-pill go" title="Stored the moment it completed; this URL reopens it without re-tracing">Saved{tracedAt ? ` · ${tracedAt}` : ''}</span>}
          {/* Where the trace began, at the right end of the row (pack CaseTop). */}
          {!reverse && (
            <p className="case-origin">
              {paymentTrace
                ? <><svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" strokeWidth="1.5"><circle cx="8" cy="8" r="6.2" /><path d="M5.2 8.2l1.9 1.9 3.8-4" /></svg>Traced from the victim's payment{ncrp ? <> · NCRP <span aria-hidden="true">••••</span><span className="visually-hidden">ending </span>{String(ncrp).slice(-4)}</> : null}</>
                : 'Exploratory, traced from the address'}
            </p>
          )}
        </div>
      </header>}

      <div className="results-body">
        {error && <div className="banner error">{error}</div>}

        {needsConfirm && (
          <ConfirmTrace
            address={routeAddress} chain={chain} asset={asset} depth={depth} direction={requestedDirection}
            budget={budget} hashes={traceParams.payments} onRun={confirmRun}
          />
        )}

        {loading && !stored && !needsConfirm && (
          <Tracing
            address={routeAddress} chain={chain} asset={asset} reverse={reverse} payments={traceParams.payments.length > 0}
            progress={progress} elapsed={elapsed} budget={budget} canStop={Boolean(jobId)} stopping={stopping}
            onStop={() => { setStopping(true); stopTraceJob(jobId).catch((err) => { setStopping(false); setError(err.message) }) }}
          />
        )}

        {loading && stored && (
          <div className="card">
            <div className="body loading">
              <span className="micro">{recorded ? 'Opening verified example' : 'Opening stored case'}</span>
              <span className="elapsed">{elapsed.toFixed(1)} s</span>
              <div className="bar"><span /></div>
              <p className="note">{recorded ? 'Read from the recording; the chain is not consulted.' : 'Read from the case store; the chain is not consulted.'}</p>
            </div>
          </div>
        )}

        {/* A live trace that came back without a case id was not stored (the
            store is full, or the save failed): say so where it cannot be missed,
            since the result is gone once the page is left. */}
        {result && !stored && !result.case_id && (
          <div className="alert unsaved" role="status">
            <Icon d={ICONS.alert} />
            <div>
              <div className="title">Not saved</div>
              {(result.warnings ?? []).filter((w) => /not saved|could not be saved/i.test(w)).map((w) => <div className="line" key={w}>{w}</div>)}
            </div>
          </div>
        )}

        {/* Sanctions, mixers and stolen funds: a published designation or theft
            outranks anything the tool inferred, so it comes before the finding. */}
        {riskMatches.length > 0 && (
          <div className="alert" role="alert">
            <Icon d={ICONS.alert} />
            <div>
              <div className="title">
                {riskMatches.length === 1 ? 'Risk screening hit' : `${riskMatches.length} risk screening hits`}
                {/* A mixer tag that is not a pinned pool is shown, but the trace went past it. */}
                {riskMatches.some((m) => m.category === 'mixer' && m.is_terminal !== false) ? ' — the trace stops at a mixer' : ''}
              </div>
              {riskMatches.map((m) => (
                <div className="line" key={m.address}>
                  <strong>{RISK_NAME[m.category] ?? m.category}:</strong> {plain(m.entity)} — <Address value={m.address} />
                  {' · '}{m.depth === 0 ? 'the reported address itself' : `${m.depth} hop${m.depth === 1 ? '' : 's'} away, ${num(m.value_received_native)} ${unit} reached it`}
                  {' · '}<span className="mono">{unambiguousDate(m.source)}</span>
                  {m.is_terminal && ' · A mixer pays out from a commingled pool, so transfers leaving it have no established link to the funds that arrived.'}
                </div>
              ))}
            </div>
          </div>
        )}

        {result && (
          <section className="card finding-bar">
            {/* The answer */}
            <div className="answer">
              <span className="q">{reverse ? 'Where the money came from' : 'Where the money went'}</span>
              {!reverse && (paymentTrace ? (
                <span className="intake" title="The trace read the reported wallet only from when the first payment arrived.">
                  From the victim's <span className="num">{num(result.reported_amount)} {unit}</span> in {paymentCount} payment{paymentCount === 1 ? '' : 's'}
                  {payments.length > paymentCount ? ` (${payments.length} transfers)` : ''}
                  {result.intake.ncrp_ack ? <> · NCRP <span className="mono">{result.intake.ncrp_ack}</span> <span className="note">as entered</span></> : null}
                  {!result.intake.ncrp_ack && result.redacted?.includes('intake.ncrp_ack') ? <> · NCRP on file (visible to the officer who traced it)</> : null}
                </span>
              ) : (
                <span className="intake exploratory" title="Traced from the address alone: it follows the wallet's whole recent history, which can include other people's money. Start from the victim's payment hashes to trace their money only.">
                  Exploratory · traced from the address, not from a reported payment
                </span>
              ))}
              {result.exchange ? (
                <>
                  <h2 className="green">{result.exchange}</h2>
                  <div className="basis">
                    {result.attribution_inferred
                      ? <><strong>Inferred, not labelled</strong> — probable deposit address</>
                      : <><strong>Exact match</strong> · label <span className="mono">{plain(result.exchange_label)}</span></>}
                    {' · '}{result.hop_count} hop{result.hop_count === 1 ? '' : 's'}{reverse ? ' upstream' : ''}
                    {' · '}{reverse
                      ? <><span className="num">{num(result.value_received_native ?? 0)} {unit}</span> sent</>
                      : result.prorata?.status === 'estimated'
                        ? <><span className="num">≈ {num(result.prorata.estimated)} of {num(capped ? capped.amount : result.prorata.sent)} {unit}</span> {capped
                            ? <>{capped.basis === 'swap_output' ? 'the swap returned' : 'the victim reported paying'} likely arrived</>
                            : paymentTrace
                              ? <>sent on after the victim's payment likely arrived</>
                              : <>this wallet sent on this route likely arrived</>} <span className="note">(pro-rata{result.prorata.arrived_total > result.prorata.estimated * 1.05 ? `; ${num(result.prorata.arrived_total)} ${unit} arrived in total, the rest from other sources` : ''})</span>
                            {!capped && !paymentTrace && <span className="note"> · may include other people's money, not only the complainant's</span>}</>
                        : <><span className="num">{num(result.value_received_native ?? 0)} {unit}</span> reached it along this path, including any funds from other sources</>}
                  </div>
                  {!reverse && result.prorata?.status === 'unknown' && (
                    <p className="note prorata-unknown">Pro-rata: not estimated — {result.prorata.reason}. The score gives the amount no credit.</p>
                  )}
                  {!reverse && <MethodRange methods={result.tracing_methods} unit={unit} />}
                  <div className="cite">
                    <span className="micro">{result.attribution_inferred ? 'Address to ask the exchange about' : 'Address to cite in the request'}</span>
                    <Address value={result.exchange_address} head={22} tail={20} />
                  </div>
                </>
              ) : followed ? (
                <>
                  <h2 className="green">{followed.exchange}</h2>
                  <div className="basis">
                    <strong>After a swap to {followed.asset}</strong> · {followed.attribution_inferred ? 'probable deposit address' : <>label <span className="mono">{plain(followed.exchange_label)}</span></>}
                    {' · '}{followed.hop_count} hop{followed.hop_count === 1 ? '' : 's'} in the {followed.asset} trace
                    {' · '}{bandOf(followed.confidence) ?? 'no'} confidence within that trace
                  </div>
                  <div className="cite">
                    <span className="micro">{followed.attribution_inferred ? 'Address to ask the exchange about' : 'Address to cite in the request'}</span>
                    <Address value={followed.exchange_address} head={22} tail={20} />
                  </div>
                  <p className="note">No exchange was reached in {unit}; the money was swapped for {followed.asset}, and the {followed.asset} was followed from the swap. The two traces are scored separately — see the follow-on below.</p>
                </>
              ) : (
                <>
                  <h2 className="none">{reverse ? 'No source exchange matched' : 'No exchange matched'}</h2>
                  <p className="note">{result.message ?? 'No address in the trace is in a published exchange label file. This is a finding, not a failure, and it is not scored.'}</p>
                </>
              )}
            </div>

            {/* How sure */}
            <div className="sure">
              <span className="q">How sure</span>
              {result.confidence == null ? (
                <div className="score"><span className="big na">n/a</span><span className="band">nothing attributed, so nothing to score</span></div>
              ) : (
                <>
                  <div className="score">
                    <span className={`big ${result.confidence_detail?.band ?? ''}`}>{bandLabel(result.confidence_detail?.band ?? bandOf(result.confidence))}</span>
                    <span className="band">a rule of three inputs, not a probability</span>
                  </div>
                  <div className="components">
                    {components.map((c) => (
                      <div className="component" key={c.name} title={c.explanation}>
                        <span className="k">{COMPONENT_NAME[c.name] ?? c.name}</span>
                        <span className="bar"><span style={{ width: `${Math.round(c.raw_value * 100)}%` }} /></span>
                        <span className="v">{c.raw_value.toFixed(2)} × {c.weight}</span>
                      </div>
                    ))}
                  </div>
                  <details className="more">
                    <summary>How the score is built</summary>
                    <div className="why-list">
                      {components.map((c) => <p key={c.name}><strong>{COMPONENT_NAME[c.name] ?? c.name}.</strong> {c.explanation}</p>)}
                      <p className="score-working">Score <span className="num">{result.confidence.toFixed(2)}</span>, the sum of each input × its weight. {BAND_RULE}</p>
                      <p className="note">The score is the weighted sum of these three inputs and nothing else. A pattern never moves it. An exchange match identifies where funds arrived, not who controls the account; only the exchange can link an address to a customer, on a lawful request (PMLA s.12, s.50).</p>
                      {primaryInference && <p className="confirm">{primaryInference.evidence?.confirmation}</p>}
                      {caveats.length > 0 && <p className="limitations-head"><strong>Limitations.</strong></p>}
                      {caveats.map((c) => <p className="note limitation" key={c}>{c}</p>)}
                    </div>
                  </details>
                </>
              )}
            </div>
          </section>
        )}

        {result && (
          <CaseTabs value={tab} onChange={setTab} panels={{
            flow: <>
              {result.victim_flow?.status === 'estimated' && <>
                <VictimFlow result={result} unit={unit} onDeeper={traceAgain}
                  onLetters={(letter) => openTab('letters', { letter })} onWatch={(watch) => openTab('letters', { watch })} />
                <details className="card sec every-wallet" onToggle={(e) => setEveryWallet(e.currentTarget.open)}>
                  <summary><span className="micro">Every wallet · {result.graph.nodes.length} addresses · {result.graph.edges.length} transfers</span></summary>
                  {everyWallet && moneyFlow}
                </details>
              </>}
              {result.victim_flow?.status !== 'estimated' && moneyFlow}

              {followOns.map((f) => (
                <div className="card graph-card" key={`${f.address}-${f.asset}`}>
                  <div className="head">
                    <span className="micro">
                      Continued in {f.asset} after the swap · {f.result.graph.nodes.length} addresses · {f.result.exchange ? `reached ${plain(f.result.exchange_label)} · ${f.result.confidence?.toFixed(2)}` : 'no exchange reached'}
                    </span>
                    <span className="note">from <Address value={f.address} head={8} tail={6} /> · swap tx <Address value={f.swap?.tx} head={8} tail={6} /></span>
                  </div>
                  <FlowView data={f.result.graph} tracePath={f.result.trace_path} unit={f.asset} direction="outgoing" />
                  {(f.result.risk_notes ?? []).map((note) => <p className="note risk-note" key={note}>{note}</p>)}
                </div>
              ))}
            </>,
            timeline: <>
              <TimelineTab result={result} unit={unit} />
              <div className="card">
                <div className="head">
                  <span className="micro">{showAll ? 'All transfers' : 'Transfers that matter'} · {visible.length}</span>
                  {hops.length > notable.length && (
                    <button className="quiet" onClick={() => { setShowAll((v) => !v); setRevealed(hops.length) }}>
                      {showAll ? 'Show fewer' : `Show all ${hops.length}`}
                    </button>
                  )}
                </div>
                <div className="feed">
                  {hops.length === 0 && (
                    <p className="note" style={{ padding: 12 }}>
                      {result.message ?? (reverse ? 'No incoming transfers found for this address.' : 'No outgoing transfers found for this address.')}
                    </p>
                  )}
                  {shown.map((h) => (
                    <div key={`${h.source}>${h.target}`} className={`row${h.onPath ? ' on-path' : ''}${h.toKind === 'red' ? ' to-red' : ''}`}>
                      <div className="hop">HOP {h.hop}</div>
                      <div>
                        <div className="pair">
                          <Address value={h.source} head={8} tail={6} />
                          <span className="arrow">→</span>
                          {h.toLabel
                            ? <span className={`to ${h.toKind}`} title={h.target}>{h.toLabel}</span>
                            : <Address value={h.target} head={8} tail={6} className={h.toKind} />}
                        </div>
                        <div className="sub">
                          <span>{h.tx_count} transfer{h.tx_count === 1 ? '' : 's'}{h.internal_tx_count ? ` (${h.internal_tx_count} by contract call)` : ''}</span>
                          {h.last_seen ? <span>{when(h.last_seen)}</span> : null}
                          {h.onPath && <span className="pill green">traced funds</span>}
                          {h.swap && <span className="pill amber">swap at {h.swap.router_label}</span>}
                          {h.flags?.map((f) => <span className="pill amber" key={f}>{PATTERN_NAME[f] ?? f}</span>)}
                        </div>
                      </div>
                      <div className="amount">{num(h.value_native)}<span className="unit">{unit}</span></div>
                    </div>
                  ))}
                </div>
              </div>

              {paymentTrace && payments.length > 0 && (
                <details className="card sec payments-card" open>
                  <summary>
                    <span className="micro">Victim's payments · {paymentCount}</span>
                    <span className="note">confirm each against the complaint{windowStart && windowStart !== Infinity ? ` · the trace reads the wallet from ${when(windowStart)} UTC` : ''}{hashesWithheld ? ' · hashes and times visible to the officer who traced it' : ''}</span>
                  </summary>
                  <div className="feed">
                    {paidByHash.map((p) => {
                      const link = p.tx_hash ? txUrl(result.explorer_url, result.chain, p.tx_hash) : null
                      return (
                        <div className="row" key={p.key}>
                          <div className="hop">PAY</div>
                          <div>
                            <div className="pair">
                              {p.tx_hash ? <Address value={p.tx_hash} head={10} tail={8} /> : <span className="note">hash withheld</span>}
                              {link && <a className="note" href={link} target="_blank" rel="noreferrer">explorer</a>}
                              {p.legs > 1 && <span className="note">{p.legs} transfers</span>}
                            </div>
                            <div className="sub">
                              <span>{when(p.timestamp)}</span>
                              <span>from {p.senders.length
                                ? p.senders.map((a) => <Address key={a} value={a} head={8} tail={6} />)
                                : <span className="note">hidden</span>}</span>
                              {p.labels.map((l) => <span className="pill" key={l}>{l}</span>)}
                              {p.payerIsVictim === true && <span className="pill green">the victim's wallet</span>}
                              {p.payerIsVictim === false && <span className="pill red" title="A sender is not the victim's wallet entered with the complaint">not the victim's wallet</span>}
                              {p.found_by === 'officer_search' && <span className="pill">found by the officer</span>}
                            </div>
                          </div>
                          <div className="amount">{num(p.amount)}<span className="unit">{unit}</span></div>
                        </div>
                      )
                    })}
                    <p className="note" style={{ padding: '8px 12px' }}>Check these against the complaint before sending letters: the trace reads the wallet from the first one.</p>
                  </div>
                </details>
              )}

              {result.statement && (result.statement.credits.length > 0 || result.statement.debits.length > 0) && (
                <details className="card sec">
                  <summary>
                    <span className="micro">Wallet statement · {unit}</span>
                    <span className="note">
                      {result.statement.credits.length} in · {result.statement.debits.length} out · latest {result.statement.rows_per_side} each
                      {result.statement.lookalikes > 0 && ` · ${result.statement.lookalikes} lookalike`}
                    </span>
                  </summary>
                  <div className="feed">
                    {[['credits', 'Money in', 'from', '+'], ['debits', 'Money out', 'to', '−'], ['poisoning', 'Address-poisoning dust (lookalike senders)', 'from', '!']].filter(([key]) => key !== 'poisoning' || (result.statement.poisoning ?? []).length > 0).map(([key, title, dir, sign]) => (
                      <div key={key}>
                        <p className="note" style={{ padding: '10px 12px 4px' }}><strong>{title}</strong>{key === 'credits' && result.redacted?.includes('statement.credits') ? ' — withheld: they list the victim\'s payments (visible to the officer who traced it)' : (result.statement[key] ?? []).length === 0 ? ' — none found' : ''}{key === 'poisoning' ? ` — ${result.statement.lookalikes} in all; never copy an address from wallet history` : ''}</p>
                        {(result.statement[key] ?? []).map((r) => (
                          <div className={`row${r.before_window ? ' before-window' : ''}`} key={r.tx + key}>
                            <div className="hop">{sign}</div>
                            <div>
                              <div className="pair"><span className="note">{dir}</span> <Address value={r.counterparty} head={8} tail={6} /></div>
                              <div className="sub">
                                <span>{when(r.time)}</span>
                                {r.before_window && <span className="pill" title="Before the victim's first payment arrived, so it cannot be the victim's money">before the payment</span>}
                                {r.lookalike && <span className="pill red" title="A stranger's address copying the start and end of one this wallet really paid — address poisoning. Never copy an address from history.">lookalike · address poisoning</span>}
                              </div>
                            </div>
                            <div className="amount">{num(r.amount)}<span className="unit">{unit}</span></div>
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </>,
            letters: <LettersTab result={result} recorded={recorded ? demoNo : null}
              pick={params.get('letter')} watch={flowWallet(result, params.get('watch'))} />,
            entities: <EntitiesTab result={result} unit={unit} correlation={correlation} />,
            evidence: <EvidenceTab result={result} unit={unit} depth={depth} recorded={recorded} recheckId={recorded ? `demo-${demoNo}` : result.case_id ?? null} />,
          }} />
        )}
      </div>
    </div>
  )
}
