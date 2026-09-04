import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { fetchCase, traceAddress } from '../api'
import GraphView from '../components/GraphView'
import ExportButton from '../components/ExportButton'

const PATTERN_NAME = { peel_chain: 'Peel chain', amount_split: 'Amount split' }

/** Middle-truncated address: both ends carry identity, the middle does not. */
function middle(address, head = 10, tail = 8) {
  if (!address || address.length <= head + tail + 1) return address
  return `${address.slice(0, head)}…${address.slice(-tail)}`
}

const when = (seconds) =>
  seconds ? new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ') : ''

const num = (value) =>
  value >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : Number(value.toFixed(6)).toString()

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

  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState('feed')
  const [copied, setCopied] = useState(false)
  // How many hops have been revealed. The backend answers a trace in one
  // response rather than streaming, so the feed reveals what arrived in
  // sequence — the honest presentation of "this is what the traversal found,
  // in the order it found it", without pretending to a live socket.
  const [revealed, setRevealed] = useState(0)
  const timers = useRef([])

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(null); setResult(null); setRevealed(0)

    const request = stored
      ? fetchCase(caseId)
      : traceAddress(routeAddress, depth, chain, asset)

    request
      .then((data) => { if (!cancelled) { setResult(data); setLoading(false) } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false) } })

    return () => {
      cancelled = true
      timers.current.forEach(clearTimeout)
      timers.current = []
    }
  }, [stored, caseId, routeAddress, chain, asset, depth])

  // Hops, ordered the way the traversal found them: nearest the victim first,
  // then by value within a hop.
  const hops = useMemo(() => {
    if (!result) return []
    const depthOf = new Map(result.graph.nodes.map((n) => [n.id, n.depth]))
    const labelOf = new Map(result.graph.nodes.map((n) => [n.id, n.label]))
    const terminal = new Set(result.graph.nodes.filter((n) => n.is_terminal).map((n) => n.id))
    const onPath = new Set()
    const path = result.trace_path ?? []
    for (let i = 0; i < path.length - 1; i += 1) {
      onPath.add(`${path[i].address}>${path[i + 1].address}`)
    }
    return result.graph.edges
      .map((e) => ({
        ...e,
        hop: depthOf.get(e.target) ?? 1,
        toLabel: labelOf.get(e.target),
        isTerminal: terminal.has(e.target),
        onPath: onPath.has(`${e.source}>${e.target}`),
      }))
      .sort((a, b) => a.hop - b.hop || b.value_native - a.value_native)
  }, [result])

  // Reveal in sequence once the data lands.
  useEffect(() => {
    timers.current.forEach(clearTimeout)
    timers.current = []
    if (!hops.length) return
    const step = hops.length > 60 ? 8 : 26
    for (let i = 1; i <= hops.length; i += 1) {
      timers.current.push(setTimeout(() => setRevealed(i), i * step))
    }
    return () => timers.current.forEach(clearTimeout)
  }, [hops])

  const address = routeAddress ?? result?.address ?? ''

  const copy = useCallback(() => {
    if (!address) return
    navigator.clipboard?.writeText(address).then(
      () => { setCopied(true); setTimeout(() => setCopied(false), 1200) },
      () => {},
    )
  }, [address])

  const status = loading ? 'running' : error ? 'failed' : result?.exchange ? 'resolved' : 'complete'
  const tracedAt = result?.created_at ? result.created_at.replace('T', ' ').slice(0, 16) : null
  // Cases stored before assets were a dimension carry no `asset`; fall back to
  // the chain's native symbol so amounts are never rendered unlabelled.
  const unit = result?.asset ?? result?.native_symbol ?? asset
  const findings = result?.findings ?? []
  const shown = hops.slice(0, revealed)

  return (
    <div className="console">
      <div className="console-bar">
        <Link to="/" className="brand" style={{ color: 'var(--text)', textDecoration: 'none' }}>
          TraceChain
        </Link>

        <div className="subject">
          <span className="addr" title={address}>{middle(address)}</span>
          <button className="icon-btn" onClick={copy} aria-label="Copy address">
            {copied ? 'copied' : 'copy'}
          </button>
        </div>

        <div className="badges">
          <span className="badge">
            {result?.chain_name ?? chain.charAt(0).toUpperCase() + chain.slice(1)}
          </span>
          <span className="badge mono">{unit}</span>
          {!stored && <span className="badge mono">{depth} hops</span>}
          {stored && (
            <span className="badge archived" title="Loaded from the case store — not re-traced">
              Archived{tracedAt ? ` · ${tracedAt}` : ''}
            </span>
          )}
        </div>

        <span style={{ flex: 1 }} />

        {result && <ExportButton caseId={result.case_id} address={address} />}
        {stored && result && (
          <button
            onClick={() => {
              const q = new URLSearchParams({
                chain: result.chain, asset: result.asset, depth: String(result.depth_reached || 3),
              })
              navigate(`/trace/${result.address}?${q}`)
            }}
            title="Run the traversal again against current chain data"
          >
            Re-trace
          </button>
        )}
        <button onClick={() => navigate('/')}>New trace</button>
      </div>

      <div className="console-body">
        <main className="feed-pane">
          <div className="feed-head">
            <span className="micro">
              Transfer feed{result ? ` · ${hops.length} transfers` : ''}
            </span>
            {result && (
              <div className="toggle" role="tablist">
                <button className={view === 'feed' ? 'on' : ''} onClick={() => setView('feed')}>Feed</button>
                <button className={view === 'graph' ? 'on' : ''} onClick={() => setView('graph')}>Graph</button>
              </div>
            )}
          </div>

          {loading && (
            <>
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div className="skeleton" key={i} style={{ animationDelay: `${i * 90}ms` }}>
                  <div className="sk-bar" style={{ width: 20 }} />
                  <div>
                    <div className="sk-bar" style={{ width: `${58 - i * 4}%` }} />
                    <div className="sk-bar" style={{ width: '30%' }} />
                  </div>
                  <div className="sk-bar" style={{ width: 66 }} />
                </div>
              ))}
            </>
          )}

          {error && <div className="banner warn" style={{ marginTop: 8 }}>{error}</div>}

          {!loading && !error && view === 'feed' && (
            hops.length === 0 ? (
              <p className="empty">
                {result?.message ?? 'No outgoing transfers found for this address.'}
              </p>
            ) : (
              shown.map((h) => (
                <div
                  key={`${h.source}>${h.target}`}
                  className={`hop${h.onPath ? ' on-path' : ''}${h.isTerminal ? ' terminal' : ''}`}
                >
                  <div className="idx">HOP {h.hop}</div>
                  <div className="route">
                    <div className="pair">
                      <span className="from">{middle(h.source, 8, 6)}</span>
                      <span className="arrow">→</span>
                      <span className="to">{h.toLabel || middle(h.target, 8, 6)}</span>
                    </div>
                    <div className="sub">
                      {h.tx_count} transfer{h.tx_count === 1 ? '' : 's'}
                      {h.last_seen ? ` · ${when(h.last_seen)}` : ''}
                      {h.isTerminal ? ' · cash-out point' : ''}
                    </div>
                    {h.flags?.map((f) => (
                      <span className="flag" key={f}>{PATTERN_NAME[f] ?? f}</span>
                    ))}
                  </div>
                  <div className="amount">
                    {num(h.value_native)}<span className="unit">{unit}</span>
                  </div>
                </div>
              ))
            )
          )}

          {!loading && !error && view === 'graph' && (
            <div className="graph-pane" style={{ height: 'calc(100vh - 150px)' }}>
              <GraphView data={result.graph} tracePath={result.trace_path} />
            </div>
          )}
        </main>

        <aside className="rail">
          <div className="rail-block">
            <span className="micro">Status</span>
            <div className="status-line">
              <span className={`dot ${status === 'running' ? 'live pulse'
                : status === 'resolved' ? 'live' : status === 'failed' ? 'down' : ''}`} />
              {status === 'running' && (stored ? 'Loading stored case…' : 'Traversing outgoing transfers…')}
              {status === 'resolved' && (stored ? 'Archived — cash-out point identified' : 'Cash-out point identified')}
              {status === 'complete' && (stored ? 'Archived — no exchange matched' : 'Trace complete — no exchange matched')}
              {status === 'failed' && 'Trace failed'}
            </div>
          </div>

          <div className="rail-block">
            <span className="micro">Attribution</span>
            <div className={`verdict ${result?.exchange ? 'resolved' : ''}`}>
              {result?.exchange ? (
                <>
                  <div className="name">{result.exchange}</div>
                  <div className="wallet">{result.exchange_label}</div>
                  <div className="wallet">{result.exchange_address}</div>
                  <div style={{ marginTop: 14 }}>
                    <div className="kv">
                      <span className="k">Distance</span>
                      <span className="v">{result.hop_count} hop{result.hop_count === 1 ? '' : 's'}</span>
                    </div>
                    <div className="kv">
                      <span className="k">Value received</span>
                      <span className="v">{num(result.value_received_native ?? 0)} {unit}</span>
                    </div>
                    <div className="kv">
                      <span className="k">Confidence</span>
                      <span className="v">
                        {result.confidence == null ? 'n/a' : result.confidence.toFixed(2)}
                      </span>
                    </div>
                  </div>
                </>
              ) : (
                <div className="name none">
                  {loading ? 'Awaiting result…' : 'No exchange matched'}
                </div>
              )}
            </div>
            {!loading && result && !result.exchange && result.message && (
              <p className="empty" style={{ marginTop: 10 }}>{result.message}</p>
            )}
          </div>

          <div className="rail-block">
            <span className="micro">Patterns fired</span>
            {findings.length === 0 ? (
              <p className="empty">
                {loading ? '—' : 'No rule matched. The traced transfers did not meet the peel-chain or amount-split thresholds.'}
              </p>
            ) : (
              findings.map((f) => (
                <div className="rule" key={f.pattern}>
                  <div className="top">
                    <span className="nm">{PATTERN_NAME[f.pattern] ?? f.pattern}</span>
                    <span className="st">strength {f.strength}</span>
                  </div>
                  <div className="desc">{f.description}</div>
                  {f.evidence?.thresholds_applied && (
                    <div className="thresholds">
                      {Object.entries(f.evidence.thresholds_applied).map(([k, v]) => (
                        <div className="th" key={k}>
                          <span className="tk">{k}</span>
                          <span className="tv">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {result && (
            <div className="rail-block">
              <span className="micro">Scope</span>
              <div className="kv"><span className="k">Addresses</span><span className="v">{result.graph.nodes.length}</span></div>
              <div className="kv"><span className="k">Transfers</span><span className="v">{result.graph.edges.length}</span></div>
              <div className="kv"><span className="k">Depth reached</span><span className="v">{result.depth_reached}</span></div>
              <div className="kv"><span className="k">API calls</span><span className="v">{result.api_calls}</span></div>
              <div className="kv"><span className="k">Truncated</span><span className="v">{result.truncated ? 'yes' : 'no'}</span></div>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
