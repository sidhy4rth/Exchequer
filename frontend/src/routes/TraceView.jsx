import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { fetchCase, fetchRelatedCases, traceAddress } from '../api'
import GraphView from '../components/GraphView'
import ExportButton from '../components/ExportButton'

const PATTERN_NAME = { peel_chain: 'Peel chain', amount_split: 'Amount split' }
const RISK_NAME = { sanctioned: 'Sanctioned entity', mixer: 'Mixer' }
const COMPONENT_NAME = {
  hop_proximity: 'Hop proximity',
  amount_correlation: 'Amount correlation',
  match_directness: 'Match directness',
}
// Rough request counts by depth, measured on the demo traces (README, "Why a
// trace takes the time it does"). Shown while loading so a wait has a size.
const EXPECTED_REQUESTS = { 1: 2, 2: 12, 3: 35, 4: 75, 5: 150, 6: 300 }

/** Middle-truncated address: both ends carry identity, the middle does not. */
function middle(address, head = 10, tail = 8) {
  if (!address || address.length <= head + tail + 1) return address
  return `${address.slice(0, head)}…${address.slice(-tail)}`
}
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
  const stored = Boolean(caseId)

  const chain = params.get('chain') || 'ethereum'
  const asset = params.get('asset') || 'ETH'
  const depth = Number(params.get('depth') || 4)
  const requestedDirection = params.get('direction') || 'outgoing'

  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [elapsed, setElapsed] = useState(0)
  const [revealed, setRevealed] = useState(0)
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
    setLoading(true); setError(null); setResult(null); setRevealed(0); setElapsed(0)
    const started = Date.now()
    const tick = setInterval(() => setElapsed((Date.now() - started) / 1000), 200)
    const request = stored
      ? fetchCase(caseId)
      : traceAddress(routeAddress, depth, chain, asset, requestedDirection)
    request
      .then((data) => { if (!cancelled) { setResult(data); setLoading(false) } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false) } })
      .finally(() => clearInterval(tick))
    return () => {
      cancelled = true
      clearInterval(tick)
      timers.current.forEach(clearTimeout)
      timers.current = []
    }
  }, [stored, caseId, routeAddress, chain, asset, depth, requestedDirection])

  // Hops, ordered the way the traversal found them: nearest the seed first,
  // then by value within a hop.
  const hops = useMemo(() => {
    if (!result) return []
    const byId = new Map(result.graph.nodes.map((n) => [n.id, n]))
    const onPath = new Set()
    const path = result.trace_path ?? []
    for (let i = 0; i < path.length - 1; i += 1) onPath.add(`${path[i].address}>${path[i + 1].address}`)
    return result.graph.edges
      .map((e) => {
        const to = byId.get(e.target) ?? {}
        return {
          ...e,
          hop: to.depth ?? 1,
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
  const inferred = result?.inferred_deposits ?? []
  const components = result?.confidence_detail?.components ?? []
  const serviceContracts = result?.graph.nodes.filter((n) => n.is_service_contract) ?? []
  const path = result?.trace_path ?? []
  const pathHashes = path.reduce((n, step) => n + (step.tx_hashes?.length ?? 0), 0)
  const primaryInference = inferred.find((m) => m.address === result?.exchange_address)
  const shown = hops.slice(0, revealed)

  const retrace = useCallback(() => {
    if (!result) return
    const q = new URLSearchParams({
      chain: result.chain, asset: result.asset,
      depth: String(result.depth_reached || 3), direction: result.direction ?? 'outgoing',
    })
    navigate(`/trace/${result.address}?${q}`)
  }, [navigate, result])

  return (
    <div className="results">
      <header className="topbar">
        <Link to="/" className="brand">TraceChain<small>Case view</small></Link>
        <div className="subject">
          <span className="micro">{reverse ? 'Reported address (funded by)' : 'Reported address'}</span>
          <Address value={address} head={12} tail={10} />
        </div>
        <div className="pills">
          <span className="pill">{result?.chain_name ?? chain}</span>
          <span className="pill mono">{unit}</span>
          {!stored && <span className="pill mono">{depth} hops</span>}
          {reverse && <span className="pill navy" title="Incoming transfers walked backwards to the addresses that funded this one">Reverse trace</span>}
          {stored && <span className="pill amber" title="Loaded from the case store — the evidence as it stood, not re-traced">Archived{tracedAt ? ` · ${tracedAt}` : ''}</span>}
        </div>
        <span className="grow" />
        <div className="actions">
          {result && <ExportButton caseId={result.case_id} address={address} />}
          {stored && result && (
            <button onClick={retrace} title="Run the traversal again against current chain data"><Icon d={ICONS.redo} />Re-trace</button>
          )}
          <button className="quiet" onClick={() => navigate('/')}><Icon d={ICONS.back} />New trace</button>
        </div>
      </header>

      <div className="results-body">
        {error && <div className="banner error">{error}</div>}

        {loading && (
          <div className="card">
            <div className="body loading">
              <span className="micro">{stored ? 'Opening stored case' : reverse ? 'Walking incoming transfers backwards' : 'Following outgoing transfers'}</span>
              <span className="elapsed">{elapsed.toFixed(1)} s</span>
              <div className="bar"><span /></div>
              <p className="note">
                {stored
                  ? 'Read from the case store; the chain is not consulted.'
                  : `Expect roughly ${EXPECTED_REQUESTS[depth] ?? '—'} provider requests at ${depth} hop${depth === 1 ? '' : 's'} — about two per second on a free key. Every request is one address's transfer history.`}
              </p>
            </div>
          </div>
        )}

        {/* Sanctions and mixers: a published designation outranks anything the
            tool inferred, so it comes before the finding. */}
        {riskMatches.length > 0 && (
          <div className="alert" role="alert">
            <Icon d={ICONS.alert} />
            <div>
              <div className="title">
                {riskMatches.length === 1 ? 'Sanctions screening hit' : `${riskMatches.length} sanctions screening hits`}
                {riskMatches.some((m) => m.category === 'mixer') ? ' — the trace stops at a mixer' : ''}
              </div>
              {riskMatches.map((m) => (
                <div className="line" key={m.address}>
                  <strong>{RISK_NAME[m.category] ?? m.category}:</strong> {m.entity} — <Address value={m.address} />
                  {' · '}{m.depth === 0 ? 'the reported address itself' : `${m.depth} hop${m.depth === 1 ? '' : 's'} away, ${num(m.value_received_native)} ${unit} reached it`}
                  {' · '}<span className="mono">{m.source}</span>
                  {m.is_terminal && ' · A mixer pays out from a commingled pool, so transfers leaving it have no established link to the funds that arrived.'}
                </div>
              ))}
            </div>
          </div>
        )}

        {result && (
          <section className="finding">
            {/* 1. Where did the money go */}
            <div className="card">
              <div className="body">
                <span className="q">{reverse ? 'Where the money came from' : 'Where the money went'}</span>
                {result.exchange ? (
                  <>
                    <h2 className="green">{result.exchange}</h2>
                    <div className="basis">
                      {result.attribution_inferred
                        ? <><strong>Inferred, not labelled.</strong> Probable {result.exchange} deposit address — every outgoing transfer it made went to a labelled {result.exchange} wallet. Evidence below.</>
                        : <><strong>Exact match</strong> against the published label <span className="mono">{result.exchange_label}</span>.</>}
                    </div>
                    <Address value={result.exchange_address} head={14} tail={12} />
                    <div className="metrics">
                      <div className="metric"><div className="k">Distance</div><div className="v">{result.hop_count} hop{result.hop_count === 1 ? '' : 's'}{reverse ? ' up' : ''}</div></div>
                      <div className="metric"><div className="k">{reverse ? 'Sent' : 'Arrived'}</div><div className="v">{num(result.value_received_native ?? 0)} {unit}</div></div>
                      <div className="metric"><div className="k">Basis</div><div className="v" style={{ fontFamily: 'var(--sans)', fontSize: 12.5 }}>{result.attribution_inferred ? 'inference' : 'label file'}</div></div>
                    </div>
                  </>
                ) : (
                  <>
                    <h2 className="none">{reverse ? 'No source exchange matched' : 'No exchange matched'}</h2>
                    <p className="note">{result.message ?? 'No address in the trace is in a published exchange label file. This is a finding, not a failure, and it is not scored.'}</p>
                  </>
                )}
              </div>
            </div>

            {/* 2. How sure, and why */}
            <div className="card">
              <div className="body">
                <span className="q">How sure, and why</span>
                {result.confidence == null ? (
                  <>
                    <div className="score"><span className="big" style={{ color: 'var(--muted)' }}>n/a</span><span className="band">not applicable</span></div>
                    <p className="note">No exchange was attributed, so there is nothing to score. A number here would be over-read; null is the honest value.</p>
                  </>
                ) : (
                  <>
                    <div className="score">
                      <span className="big">{result.confidence.toFixed(2)}</span>
                      <span className="band">{result.confidence_detail?.band} · weighted sum of the three inputs below, nothing else</span>
                    </div>
                    {components.map((c) => (
                      <div className="component" key={c.name}>
                        <span className="k">{COMPONENT_NAME[c.name] ?? c.name}</span>
                        <span className="bar"><span style={{ width: `${Math.round(c.raw_value * 100)}%` }} /></span>
                        <span className="v">{c.raw_value.toFixed(2)} × {c.weight}</span>
                        <span className="why">{c.explanation}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
            </div>

            {/* 3. What exactly to send */}
            <div className="card send">
              <div className="body">
                <span className="q">What to send to the exchange</span>
                {result.exchange ? (
                  <>
                    <div className="cite">
                      <span className="note">Address to cite in the request{result.attribution_inferred ? ' (inferred — ask whether it is theirs)' : ''}:</span>
                      <Address value={result.exchange_address} head={22} tail={20} />
                    </div>
                    <p className="note">
                      The path below carries {pathHashes} transaction hash{pathHashes === 1 ? '' : 'es'} over {Math.max(path.length - 1, 0)} hop{path.length - 1 === 1 ? '' : 's'}; the report lists every one, with amounts and times, so the exchange can match them against its own records. Only the exchange can link an address to a customer, on a lawful request (PMLA s.12, s.50).
                    </p>
                    {primaryInference && <div className="confirm">{primaryInference.evidence?.confirmation}</div>}
                  </>
                ) : (
                  <p className="note">
                    There is no exchange to write to. The report still lists every address and transaction in the trace, so the {result.graph.nodes.length} addresses here can be re-checked on a public explorer{swaps.some((s) => s.output_read) ? ', and the swap below says which asset to re-run on' : ''}.
                  </p>
                )}
                <div className="buttons">
                  <ExportButton caseId={result.case_id} address={address} />
                </div>
              </div>
            </div>
          </section>
        )}

        {result && (
          <section className="split">
            <div className="left">
              <div className="card graph-card">
                <div className="head">
                  <span className="micro">Money flow · {result.graph.nodes.length} addresses · {result.graph.edges.length} transfers</span>
                  <span className="note">bubble area = value moved · arrows point the way the money went</span>
                </div>
                <div className="stage">
                  <GraphView data={result.graph} tracePath={result.trace_path} unit={unit} />
                </div>
              </div>

              <div className="card">
                <div className="head">
                  <span className="micro">Transfer feed · in the order the traversal found them</span>
                  <span className="note">{shown.length < hops.length ? `${shown.length} / ${hops.length}` : `${hops.length}`}</span>
                </div>
                <div className="feed">
                  {hops.length === 0 && (
                    <p className="note" style={{ padding: 12 }}>
                      {result.message ?? (reverse ? 'No incoming transfers found for this address.' : 'No outgoing transfers found for this address.')}
                    </p>
                  )}
                  {shown.map((h) => (
                    <div key={`${h.source}>${h.target}`} className={`row${h.onPath ? ' on-path' : ''}`}>
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
                          {h.onPath && <span className="pill green">on the attributed path</span>}
                          {h.swap && <span className="pill amber">swap at {h.swap.router_label}</span>}
                          {h.flags?.map((f) => <span className="pill amber" key={f}>{PATTERN_NAME[f] ?? f}</span>)}
                        </div>
                      </div>
                      <div className="amount">{num(h.value_native)}<span className="unit">{unit}</span></div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <aside className="rail">
              {/* 4. What the tool did not look at */}
              <div className="card">
                <div className="head"><span className="micro">What the tool did not look at</span><span className="note">{result.truncated ? 'truncated' : 'complete within limits'}</span></div>
                <div className="body">
                  <div className="exclusion">
                    <span className={`n ${result.transfers_excluded_by_time ? '' : 'zero'}`}>{result.transfers_excluded_by_time ?? 0}</span>
                    <span className="t">transfers made before the traced funds arrived<small>Money cannot be forwarded before it is received; these were left out.</small></span>
                  </div>
                  <div className="exclusion">
                    <span className={`n ${serviceContracts.length ? '' : 'zero'}`}>{serviceContracts.length}</span>
                    <span className="t">service contracts not expanded<small>Contracts paying out to many addresses (WETH, pools, routers): their payouts are other people's money.{serviceContracts.length ? ' ' : ''}{serviceContracts.map((n) => <Address key={n.id} value={n.id} head={8} tail={6} />).reduce((acc, el, i) => (i ? [...acc, ' ', el] : [el]), [])}</small></span>
                  </div>
                  <div className="exclusion">
                    <span className={`n ${swaps.length ? '' : 'zero'}`}>{swaps.length}</span>
                    <span className="t">swaps detected, not followed<small>The trace follows one asset; a swap is recorded and the output asset named, never crossed.</small></span>
                  </div>
                  <div className="exclusion">
                    <span className="n">{result.api_calls}</span>
                    <span className="t">provider requests<small>{result.graph.nodes.length} addresses, {result.graph.edges.length} aggregated transfers, {result.transfers?.length ?? 0} individual transactions, depth {result.depth_reached} reached of {stored ? (result.max_depth ?? '—') : depth}.</small></span>
                  </div>
                  {result.truncation_reasons?.length > 0 && (
                    <ul className="reasons">
                      {result.truncation_reasons.map((r) => <li key={r}>{r}</li>)}
                    </ul>
                  )}
                  {result.warnings?.length > 0 && result.warnings.map((w) => <p className="note" key={w}>! {w}</p>)}
                </div>
              </div>

              {inferred.length > 0 && (
                <div className="card">
                  <div className="head"><span className="micro">Inferred deposit addresses · {inferred.length}</span><span className="pill amber">inference</span></div>
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
                            <span className="tk">share to that wallet</span><span className="tv">100%</span>
                            <span className="tk">total swept</span><span className="tv">{num(e.total_swept_native ?? 0)} {unit}</span>
                            {e.current_balance_native != null && <><span className="tk">current balance</span><span className="tv">{num(e.current_balance_native)} {unit}</span></>}
                            {e.first_sweep && <><span className="tk">sweeps between</span><span className="tv">{when(e.first_sweep).slice(0, 10)} – {when(e.last_sweep).slice(0, 10)}</span></>}
                          </div>
                          <div className="desc">{e.confirmation}</div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              <div className="card">
                <div className="head"><span className="micro">Patterns · {findings.length}</span>{findings.length > 0 && <span className="pill amber">reason to look closer</span>}</div>
                <div className="body">
                  {findings.length === 0
                    ? <p className="note">No rule matched. The traced transfers did not meet the peel-chain or amount-split thresholds.</p>
                    : findings.map((f) => (
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
                  {findings.length > 0 && <p className="note">Measured on real wallets, the amount-split shape appears within three hops of about one in nine ordinary high-volume wallets. A pattern never moves the score.</p>}
                </div>
              </div>

              {swaps.length > 0 && (
                <div className="card">
                  <div className="head"><span className="micro">Swaps · {swaps.length}</span><span className="note">the trace changes asset here</span></div>
                  <div className="body">
                    {swaps.map((s) => (
                      <div className="swap" key={s.tx}>
                        <Address value={s.sender} head={8} tail={6} /> sent <span className="num">{num(s.amount_in)} {s.asset_in}</span> to <strong>{s.router_label}</strong>
                        {s.output_read
                          ? <> and received <span className="num">{s.amount_out != null ? num(s.amount_out) : s.amount_out_units} {s.asset_out}</span> back in the same transaction. Re-run on that asset from the sender to follow the money further.</>
                          : <>. No token came back to the sender in the receipt — what a swap into the native coin looks like — so the output is reported as unread, not guessed.</>}
                        <div className="grid">
                          <span className="k">router</span><Address value={s.router_address} head={10} tail={8} />
                          <span className="k">tx</span><Address value={s.tx} head={12} tail={10} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 5. One complaint, or a campaign */}
              <div className="card">
                <div className="head"><span className="micro">Related cases · {related.length}</span><span className="note">from the case store, no re-tracing</span></div>
                <div className="body">
                  {related.length === 0
                    ? <p className="note">No stored trace of another reported address passed through the same wallets as this one. Exchange wallets, routers and service contracts are never counted.</p>
                    : (
                      <>
                        {related.slice(0, 8).map((c) => (
                          <div className="related-case" key={c.case_id}>
                            <div className="top">
                              <a href={`/case/${c.case_id}`} className="mono" title={c.reported_address}>{middle(c.reported_address, 10, 8)}</a>
                              <span className="st">{c.shared_count} shared wallet{c.shared_count === 1 ? '' : 's'}</span>
                            </div>
                            <div className="ent">{c.exchange ? `reached ${c.exchange}` : 'no exchange matched'} · traced {String(c.traced_at).slice(0, 10)}</div>
                            {c.shared.slice(0, 4).map((s) => (
                              <div className="row" key={s.address}>
                                <Address value={s.address} head={10} tail={8} />
                                <span className="via">{s.inferred_exchange ? `probable ${s.inferred_exchange} deposit · ` : ''}{num(s.value_in_native)} {c.asset} · {s.depth} hop{s.depth === 1 ? '' : 's'}</span>
                              </div>
                            ))}
                            {c.shared_count > 4 && <div className="ent">…and {c.shared_count - 4} more shared wallets</div>}
                          </div>
                        ))}
                        {related.length > 8 && <p className="note">…and {related.length - 8} more related cases. Full list: <code>GET /cases/correlate?case_id={result.case_id}</code>.</p>}
                        <p className="note">Two victims who cashed out at the same exchange share a bank, not an offender; only unlabelled wallets and probable deposit addresses count.</p>
                      </>
                    )}
                </div>
              </div>

              {reverse && funders.length > 0 && (
                <div className="card">
                  <div className="head"><span className="micro">Funded this address · {funders.length}</span><span className="note">{funders.filter((f) => f.exchange).length} are exchange withdrawals</span></div>
                  <div className="body">
                    <p className="note">Each address paid the reported one directly. Where that address belongs to an offender, these are candidate victims of the same operation — but a sender may equally be the offender's own wallet or an exchange withdrawal, and the exchanges are marked.</p>
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
                  </div>
                </div>
              )}
            </aside>
          </section>
        )}
      </div>
    </div>
  )
}
