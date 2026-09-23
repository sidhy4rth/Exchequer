import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { fetchCase, fetchRelatedCases, traceAddress } from '../api'
import GraphView from '../components/GraphView'
import FlowView from '../components/FlowView'
import ThemeToggle from '../components/ThemeToggle'
import Mark from '../components/Mark'
import ExportButton from '../components/ExportButton'
import Present from '../components/Present'

const PATTERN_NAME = { peel_chain: 'Peel chain', amount_split: 'Amount split' }
const RISK_NAME = { sanctioned: 'Sanctioned entity', mixer: 'Mixer', frozen: 'Frozen by Tether', stolen: 'Stolen funds', reported: 'TronScan warning' }
const COMPONENT_NAME = {
  hop_proximity: 'Hop proximity',
  amount_correlation: 'Amount correlation',
  match_directness: 'Match directness',
}

/** Truncation reasons come back one sentence per address. Grouped by kind
 * they read as a summary rather than a wall. */
function groupReasons(reasons) {
  const counts = { depth: 0, nodes: 0, fanout: 0, service: 0, fetch: 0, other: [] }
  ;(reasons ?? []).forEach((r) => {
    if (r.startsWith('time budget')) counts.other.push(r)
    else if (r.startsWith('depth limit')) counts.depth += 1
    else if (r.startsWith('node limit')) counts.nodes += 1
    else if (r.startsWith('fan-out limit')) counts.fanout += 1
    else if (r.includes('pays out to many addresses')) counts.service += 1
    else if (r.includes('could not be fetched')) counts.fetch += 1
    else counts.other.push(r)
  })
  const out = []
  if (counts.depth) out.push('the hop limit was reached')
  if (counts.nodes) out.push('the address limit was reached')
  if (counts.fanout) out.push(`only the 10 largest counterparties were followed at ${counts.fanout} address${counts.fanout === 1 ? '' : 'es'}`)
  if (counts.service) out.push(`${counts.service} service contract${counts.service === 1 ? '' : 's'} not expanded`)
  if (counts.fetch) out.push(`${counts.fetch} address${counts.fetch === 1 ? '' : 'es'} could not be fetched`)
  return out.concat(counts.other)
}

/** OFAC stamps its list "MM/DD/YYYY"; an Indian reader parses that as day-first.
 * Spell the month out so "09/04/2026" cannot be read as 9 April. */
function unambiguousDate(text) {
  return String(text ?? '').replace(/(\d{2})\/(\d{2})\/(\d{4})/, (_, mm, dd, yyyy) => {
    const d = new Date(Date.UTC(+yyyy, +mm - 1, +dd))
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  })
}

/** Middle-truncated address: both ends carry identity, the middle does not. */
function middle(address, head = 10, tail = 8) {
  if (!address || address.length <= head + tail + 1) return address
  return `${address.slice(0, head)}…${address.slice(-tail)}`
}
const mmss = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
const when = (seconds) =>
  seconds ? new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ') : ''
const num = (value) =>
  value >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : Number((value || 0).toFixed(6)).toString()

const Icon = ({ d, size }) => (
  <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" style={size ? { width: size, height: size } : undefined}>
    {d.map((path) => <path key={path} d={path} />)}
  </svg>
)
const ICONS = {
  alert: ['M12 3 2 20h20L12 3z', 'M12 10v4', 'M12 17.5h.01'],
  copy: ['M9 9h10v10H9z', 'M5 15V5h10'],
  back: ['M15 6l-6 6 6 6'],
  redo: ['M4 12a8 8 0 1 1 2.3 5.7', 'M4 18v-6h6'],
  present: ['M3 5h18v11H3z', 'M8 20h8', 'M12 16v4'],
}

/** An address that copies itself when clicked and shows the full value on hover. */
function Address({ value, head = 10, tail = 8, className = '' }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard?.writeText(value).then(
      () => { setCopied(true); setTimeout(() => setCopied(false), 1100) },
      () => {},
    )
  }
  return (
    <button type="button" className={`addr ${copied ? 'copied' : ''} ${className}`} title={`${value} — click to copy`} onClick={copy}>
      {copied ? 'copied' : middle(value, head, tail)}
    </button>
  )
}

export default function TraceView() {
  // One component serves both routes. /trace/:address runs a fresh traversal;
  // /case/:caseId opens what was stored, without touching the chain.
  const { address: routeAddress, caseId } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation()
  const stored = Boolean(caseId)
  // A trace that has just finished arrives here by redirect with its result
  // in the navigation state, so the case view does not fetch what it already
  // holds. Distinguished from an archived case only in the header pill.
  const justTraced = stored && location.state?.result?.case_id === caseId

  const chain = params.get('chain') || 'ethereum'
  const asset = params.get('asset') || 'ETH'
  const depth = Number(params.get('depth') || 4)
  const requestedDirection = params.get('direction') || 'outgoing'
  // Optional wall-clock cap, in seconds; absent means the trace runs its course.
  const budget = Number(params.get('budget')) || null

  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [elapsed, setElapsed] = useState(0)
  const [revealed, setRevealed] = useState(0)
  const [showAll, setShowAll] = useState(false)
  const [view, setView] = useState('flow') // 'flow' | 'bubbles'
  // Present mode: the case as four big screens. P opens it, Esc closes it.
  const [presenting, setPresenting] = useState(false)
  const timers = useRef([])

  // Stored cases that share an intermediary with this one. Loaded after the
  // trace, from the case store only; a failure here must not disturb the trace.
  const [related, setRelated] = useState([])
  useEffect(() => {
    if (!result?.case_id) { setRelated([]); return undefined }
    let cancelled = false
    fetchRelatedCases(result.case_id)
      .then((r) => { if (!cancelled) setRelated(r.related_cases || []) })
      .catch(() => { if (!cancelled) setRelated([]) })
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
    const request = stored
      ? fetchCase(caseId)
      : traceAddress(routeAddress, depth, chain, asset, requestedDirection, budget)
    request
      .then((data) => {
        if (cancelled) return
        if (stored) { setResult(data); setLoading(false); return }
        // The trace is stored the moment it completes, so the URL becomes the
        // case's own. A refresh or the back button then reopens the stored
        // case instead of running the traversal again -- another wait on the
        // provider and a duplicate row in the case store.
        navigate(`/case/${data.case_id}`, { replace: true, state: { result: data } })
      })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false) } })
      .finally(() => clearInterval(tick))
    return () => {
      cancelled = true
      clearInterval(tick)
      timers.current.forEach(clearTimeout)
      timers.current = []
    }
  }, [stored, caseId, routeAddress, chain, asset, depth, requestedDirection, budget]) // eslint-disable-line react-hooks/exhaustive-deps

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
          toLabel: to.label,
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
  const reverse = (result?.direction ?? requestedDirection) === 'incoming'
  const unit = result?.asset ?? result?.native_symbol ?? asset
  const tracedAt = result?.created_at ? result.created_at.replace('T', ' ').slice(0, 16) : null
  const findings = result?.findings ?? []
  const riskMatches = result?.risk_matches ?? []
  const funders = result?.direct_senders ?? []
  const swaps = result?.swaps ?? []
  const followOns = (result?.follow_ons ?? []).filter((f) => f.result)
  const followed = result?.followed_attribution
  const inferred = result?.inferred_deposits ?? []
  const components = result?.confidence_detail?.components ?? []
  const serviceContracts = result?.graph.nodes.filter((n) => n.is_service_contract) ?? []
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
  const grouped = groupReasons(result?.truncation_reasons)
  const scopeLine = result ? [
    result.transfers_excluded_by_time ? `${result.transfers_excluded_by_time} pre-arrival transfers left out` : null,
    serviceContracts.length ? `${serviceContracts.length} service contract${serviceContracts.length === 1 ? '' : 's'}` : null,
    swaps.length ? `${swaps.length} swap${swaps.length === 1 ? '' : 's'}` : null,
    result.evidence?.count ? `${result.evidence.count} responses hashed` : null,
  ].filter(Boolean).join(' · ') : ''

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'p' && e.key !== 'P') return
      if (e.target && /input|textarea|select/i.test(e.target.tagName)) return
      if (result && !presenting) { e.preventDefault(); setPresenting(true) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [result, presenting])

  const retrace = useCallback(() => {
    if (!result) return
    const q = new URLSearchParams({
      chain: result.chain, asset: result.asset,
      depth: String(result.max_depth ?? result.depth_reached ?? 3), direction: result.direction ?? 'outgoing',
    })
    if (result.time_budget_seconds) q.set('budget', String(result.time_budget_seconds))
    navigate(`/trace/${result.address}?${q}`)
  }, [navigate, result])


  return (
    <div className="results">
      {presenting && result && <Present result={result} related={related} unit={unit} onClose={() => setPresenting(false)} />}
      <header className="topbar">
        <Link to="/" className="brand"><Mark size={18} />Exchequer<small>Case view</small></Link>
        <div className="subject">
          <span className="micro">{reverse ? 'Reported address (funded by)' : 'Reported address'}</span>
          <Address value={address} head={12} tail={10} />
        </div>
        <div className="pills">
          <span className="pill">{result?.chain_name ?? chain}</span>
          <span className="pill mono">{unit}</span>
          {(!stored || result?.max_depth) && <span className="pill mono">{stored ? result.max_depth : depth} hops</span>}
          {reverse && <span className="pill navy" title="Incoming transfers walked backwards to the addresses that funded this one">Reverse trace</span>}
          {(result ? result.time_budget_seconds : budget) && <span className="pill mono" title="The walk stopped expanding once this much time was spent">{mmss(result ? result.time_budget_seconds : budget)} cap</span>}
          {stored && !justTraced && <span className="pill amber" title="Loaded from the case store — the evidence as it stood, not re-traced">Archived{tracedAt ? ` · ${tracedAt}` : ''}</span>}
          {justTraced && <span className="pill green" title="Stored the moment it completed; this URL reopens it without re-tracing">Saved{tracedAt ? ` · ${tracedAt}` : ''}</span>}
        </div>
        <span className="grow" />
        <div className="actions">
          {result && <button onClick={() => setPresenting(true)} title="The case as four big screens (P)"><Icon d={ICONS.present} />Present</button>}
          {result && <ExportButton caseId={result.case_id} address={address} />}
          {stored && result && (
            <button onClick={retrace} title="Run the traversal again against current chain data"><Icon d={ICONS.redo} />Re-trace</button>
          )}
          <button className="quiet" onClick={() => navigate('/')}><Icon d={ICONS.back} />New trace</button>
          <ThemeToggle />
        </div>
      </header>

      <div className="results-body">
        {error && <div className="banner error">{error}</div>}

        {loading && (
          <div className="card">
            <div className="body loading">
              <span className="micro">{stored ? 'Opening stored case' : reverse ? 'Walking incoming transfers backwards' : 'Following outgoing transfers'}</span>
              <span className="elapsed">{elapsed.toFixed(1)} s{!stored && budget ? <small> · stops expanding at {mmss(budget)}{elapsed > budget ? ' — finishing what it has' : ''}</small> : null}</span>
              <div className="bar"><span /></div>
              <p className="note">
                {stored
                  ? 'Read from the case store; the chain is not consulted.'
                  : 'One request per address, about two a second on a free key. Instant when the addresses have been seen before.'}
              </p>
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
                {riskMatches.some((m) => m.category === 'mixer') ? ' — the trace stops at a mixer' : ''}
              </div>
              {riskMatches.map((m) => (
                <div className="line" key={m.address}>
                  <strong>{RISK_NAME[m.category] ?? m.category}:</strong> {m.entity} — <Address value={m.address} />
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
              {result.exchange ? (
                <>
                  <h2 className="green">{result.exchange}</h2>
                  <div className="basis">
                    {result.attribution_inferred
                      ? <><strong>Inferred, not labelled</strong> — probable deposit address</>
                      : <><strong>Exact match</strong> · label <span className="mono">{result.exchange_label}</span></>}
                    {' · '}{result.hop_count} hop{result.hop_count === 1 ? '' : 's'}{reverse ? ' upstream' : ''}
                    {' · '}{reverse
                      ? <><span className="num">{num(result.value_received_native ?? 0)} {unit}</span> sent</>
                      : result.prorata?.status === 'estimated'
                        ? <><span className="num">≈ {num(result.prorata.estimated)} of {num(result.prorata.sent)} {unit}</span> of the reported funds likely arrived <span className="note">(pro-rata{result.prorata.arrived_total > result.prorata.estimated * 1.05 ? `; ${num(result.prorata.arrived_total)} ${unit} arrived in total, the rest from other sources` : ''})</span></>
                        : <><span className="num">{num(result.value_received_native ?? 0)} {unit}</span> reached it along this path, including any funds from other sources</>}
                  </div>
                  <div className="cite">
                    <span className="micro">{result.attribution_inferred ? 'Address to ask the exchange about' : 'Address to cite in the request'}</span>
                    <Address value={result.exchange_address} head={22} tail={20} />
                  </div>
                </>
              ) : followed ? (
                <>
                  <h2 className="green">{followed.exchange}</h2>
                  <div className="basis">
                    <strong>After a swap to {followed.asset}</strong> · {followed.attribution_inferred ? 'probable deposit address' : <>label <span className="mono">{followed.exchange_label}</span></>}
                    {' · '}{followed.hop_count} hop{followed.hop_count === 1 ? '' : 's'} in the {followed.asset} trace
                    {' · '}confidence <span className="num">{followed.confidence?.toFixed(2)}</span> within that trace
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
                    <span className={`big ${result.confidence_detail?.band ?? ''}`}>{result.confidence.toFixed(2)}</span>
                    <span className="band">{String(result.confidence_detail?.band ?? '').replace(/^./, (c) => c.toUpperCase())}</span>
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
                      <p className="note">The score is the weighted sum of these three inputs and nothing else. A pattern never moves it. An exchange match identifies where funds arrived, not who controls the account; only the exchange can link an address to a customer, on a lawful request (PMLA s.12, s.50).</p>
                      {primaryInference && <p className="confirm">{primaryInference.evidence?.confirmation}</p>}
                    </div>
                  </details>
                </>
              )}
            </div>
          </section>
        )}

        {result && (
          <section className="split">
            <div className="left">
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

              {followOns.map((f) => (
                <div className="card graph-card" key={`${f.address}-${f.asset}`}>
                  <div className="head">
                    <span className="micro">
                      Continued in {f.asset} after the swap · {f.result.graph.nodes.length} addresses · {f.result.exchange ? `reached ${f.result.exchange_label} · ${f.result.confidence?.toFixed(2)}` : 'no exchange reached'}
                    </span>
                    <span className="note">from <Address value={f.address} head={8} tail={6} /> · swap tx <Address value={f.swap?.tx} head={8} tail={6} /></span>
                  </div>
                  <FlowView data={f.result.graph} tracePath={f.result.trace_path} unit={f.asset} direction="outgoing" />
                  {(f.result.risk_notes ?? []).map((note) => <p className="note risk-note" key={note}>{note}</p>)}
                </div>
              ))}

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
                          {h.onPath && <span className="pill red">traced funds</span>}
                          {h.swap && <span className="pill amber">swap at {h.swap.router_label}</span>}
                          {h.flags?.map((f) => <span className="pill amber" key={f}>{PATTERN_NAME[f] ?? f}</span>)}
                        </div>
                      </div>
                      <div className="amount">{num(h.value_native)}<span className="unit">{unit}</span></div>
                    </div>
                  ))}
                </div>
              </div>

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
                        <p className="note" style={{ padding: '10px 12px 4px' }}><strong>{title}</strong>{(result.statement[key] ?? []).length === 0 ? ' — none found' : ''}{key === 'poisoning' ? ` — ${result.statement.lookalikes} in all; never copy an address from wallet history` : ''}</p>
                        {(result.statement[key] ?? []).map((r) => (
                          <div className="row" key={r.tx + key}>
                            <div className="hop">{sign}</div>
                            <div>
                              <div className="pair"><span className="note">{dir}</span> <Address value={r.counterparty} head={8} tail={6} /></div>
                              <div className="sub">
                                <span>{when(r.time)}</span>
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
            </div>

            <aside className="rail">
              {inferred.length > 0 && (
                <details className="card sec" open={Boolean(result.attribution_inferred)}>
                  <summary><span className="micro">Inferred deposit addresses · {inferred.length}</span><span className="pill amber">inference</span></summary>
                  <div className="body">
                    {inferred.map((m) => {
                      const e = m.evidence ?? {}
                      return (
                        <div className="rule-block" key={m.address}>
                          <div className="top"><span className="nm amber">Probable {m.exchange} deposit address</span><span className="st">{m.depth} hop{m.depth === 1 ? '' : 's'}</span></div>
                          <Address value={m.address} head={12} tail={10} />
                          <div className="thresholds">
                            <span className="tk">outgoing transfers</span><span className="tv">{e.sweep_count}{e.outgoing_history_capped ? ' (newest only)' : ''}</span>
                            <span className="tk">all to</span><span className="tv">{e.sweep_destination_label}</span>
                            <span className="tk">total swept</span><span className="tv">{num(e.total_swept_native ?? 0)} {unit}</span>
                            {e.current_balance_native != null && <><span className="tk">current balance</span><span className="tv">{num(e.current_balance_native)} {unit}</span></>}
                            {e.first_sweep && <><span className="tk">sweeps between</span><span className="tv">{when(e.first_sweep).slice(0, 10)} – {when(e.last_sweep).slice(0, 10)}</span></>}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </details>
              )}

              {findings.length > 0 ? (
                <details className="card sec" open>
                  <summary><span className="micro">Patterns · {findings.length}</span><span className="pill amber">reason to look closer</span></summary>
                  <div className="body">
                    {findings.map((f) => (
                      <div className="rule-block" key={f.pattern}>
                        <div className="top"><span className="nm amber">{PATTERN_NAME[f.pattern] ?? f.pattern}</span><span className="st">strength {f.strength}</span></div>
                        <div className="desc">{f.description}</div>
                        {f.evidence?.thresholds_applied && (
                          <div className="thresholds">
                            {Object.entries(f.evidence.thresholds_applied).map(([k, v]) => (
                              <span key={k} style={{ display: 'contents' }}><span className="tk">{k}</span><span className="tv">{String(v)}</span></span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                    <p className="note">A pattern is a shape, not a verdict, and never moves the score.</p>
                  </div>
                </details>
              ) : (
                <div className="card sec flat"><span className="micro">Patterns · none</span><span className="note">no peel chain or amount split</span></div>
              )}

              {swaps.length > 0 && (
                <details className="card sec" open={!result.exchange}>
                  <summary><span className="micro">Swaps · {swaps.length}</span><span className="note">the trace changes asset here</span></summary>
                  <div className="body">
                    {swaps.map((s) => (
                      <div className="swap" key={s.tx}>
                        <Address value={s.sender} head={8} tail={6} /> sent <span className="num">{num(s.amount_in)} {s.asset_in}</span> to <strong>{s.router_label}</strong>
                        {s.output_read
                          ? <> and got <span className="num">{s.amount_out != null ? num(s.amount_out) : s.amount_out_units} {s.asset_out}</span> back. {followOns.some((f) => f.address === s.sender && f.asset === s.asset_out)
                            ? <>The {s.asset_out} is followed from here — see <em>Continued in {s.asset_out}</em>.</>
                            : <>Re-run on {s.asset_out} from the sender to follow it further.</>}</>
                          : <>. Nothing came back to the sender in the receipt — a swap into the native coin looks like this — so the output is unread, not guessed.</>}
                        <div className="grid">
                          <span className="k">tx</span><Address value={s.tx} head={12} tail={10} />
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              )}

              {related.length > 0 ? (
                <details className="card sec" open>
                  <summary><span className="micro">Related cases · {related.length}</span><span className="note">same wallets, other complaints</span></summary>
                  <div className="body">
                    {related.slice(0, 8).map((c) => (
                      <div className="related-case" key={c.case_id}>
                        <div className="top">
                          <a href={`/case/${c.case_id}`} className="mono" title={c.reported_address}>{middle(c.reported_address, 10, 8)}</a>
                          <span className="st">{c.shared_count} shared wallet{c.shared_count === 1 ? '' : 's'}</span>
                        </div>
                        <div className="ent">{c.exchange ? `reached ${c.exchange}` : 'no exchange matched'} · traced {String(c.traced_at).slice(0, 10)}</div>
                        {c.shared.slice(0, 3).map((s) => (
                          <div className="row" key={s.address}>
                            <Address value={s.address} head={10} tail={8} />
                            <span className="via">{s.inferred_exchange ? `probable ${s.inferred_exchange} deposit · ` : ''}{s.risk_category ? `${RISK_NAME[s.risk_category] ?? s.risk_category} · ` : ''}{num(s.value_in_native)} {s.after_swap_to ?? c.asset}{s.after_swap_to ? ' after a swap' : ''}</span>
                          </div>
                        ))}
                        {c.shared_count > 3 && <div className="ent">…and {c.shared_count - 3} more</div>}
                      </div>
                    ))}
                    {related.length > 8 && <p className="note">…and {related.length - 8} more related cases.</p>}
                    <p className="note">Only wallets no list names count — unlabelled, probable deposit addresses, or flagged but unnamed (a Tether freeze, a warning tag). A shared exchange is a shared bank, not a shared offender.</p>
                  </div>
                </details>
              ) : (
                <div className="card sec flat"><span className="micro">Related cases · none</span><span className="note">no other stored complaint shares a wallet</span></div>
              )}

              {reverse && funders.length > 0 && (
                <details className="card sec" open>
                  <summary><span className="micro">Funded this address · {funders.length}</span><span className="note">{funders.filter((f) => f.exchange).length} are exchange withdrawals</span></summary>
                  <div className="body">
                    {funders.map((f) => (
                      <div className="funder" key={f.address}>
                        <Address value={f.address} head={12} tail={10} />
                        <span className="amt">{num(f.value_native)} {unit}</span>
                        <span className="sub">
                          {f.tx_count} transfer{f.tx_count === 1 ? '' : 's'}{f.last_seen ? ` · ${when(f.last_seen)}` : ''}
                          {f.exchange && <span className="pill green">{f.exchange} withdrawal, not a victim</span>}
                          {f.risk_category && <span className="pill red">{RISK_NAME[f.risk_category] ?? f.risk_category}</span>}
                        </span>
                      </div>
                    ))}
                    <p className="note">Candidate victims where the reported address is an offender's — but a sender may equally be the offender's own wallet; the exchanges are marked.</p>
                  </div>
                </details>
              )}

              <details className="card sec">
                <summary><span className="micro">Scope and evidence</span><span className="note">{result.truncated ? 'truncated' : 'complete within limits'}</span></summary>
                <div className="body">
                  <p className="note">{scopeLine || 'Nothing was left out.'}</p>
                  <div className="exclusion">
                    <span className={`n ${result.transfers_excluded_by_time ? '' : 'zero'}`}>{result.transfers_excluded_by_time ?? 0}</span>
                    <span className="t">transfers before the traced funds arrived<small>Money cannot be forwarded before it is received; these were left out.</small></span>
                  </div>
                  <div className="exclusion">
                    <span className={`n ${serviceContracts.length ? '' : 'zero'}`}>{serviceContracts.length}</span>
                    <span className="t">service contracts not expanded<small>WETH, pools, routers: their payouts are other people's money.</small></span>
                  </div>
                  {result.addresses_unexpanded_by_time > 0 && (
                    <div className="exclusion">
                      <span className="n">{result.addresses_unexpanded_by_time}</span>
                      <span className="t">addresses reached but not expanded<small>The {mmss(result.time_budget_seconds)} time cap ran out first; the graph beyond them is missing.</small></span>
                    </div>
                  )}
                  <div className="exclusion">
                    <span className="n">{result.api_calls}</span>
                    <span className="t">provider requests<small>{result.transfers?.length ?? 0} individual transactions; depth {result.depth_reached} reached of {result.max_depth ?? depth}{result.seconds_elapsed ? `; ${result.seconds_elapsed} s` : ''}.</small></span>
                  </div>
                  {result.evidence?.count > 0 && (
                    <div className="exclusion">
                      <span className="n">{result.evidence.count}</span>
                      <span className="t">responses hashed as evidence<small>
                        SHA-256 at arrival{result.evidence.from_cache > 0 ? ` (${result.evidence.from_cache} from cache, with their original time)` : ''}. Manifest{' '}
                        <span className="mono" title={result.evidence.manifest_sha256}>{result.evidence.manifest_sha256.slice(0, 16)}…</span>; full list in the report, which carries its own content hash.
                      </small></span>
                    </div>
                  )}
                  {grouped.length > 0 && (
                    <ul className="reasons">{grouped.map((r) => <li key={r}>{r}</li>)}</ul>
                  )}
                  {result.warnings?.length > 0 && result.warnings.map((w) => <p className="note" key={w}>! {w}</p>)}
                </div>
              </details>
            </aside>
          </section>
        )}
      </div>
    </div>
  )
}
