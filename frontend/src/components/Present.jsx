import { useCallback, useEffect, useState } from 'react'
import FlowView from './FlowView'
import ExportButton from './ExportButton'

// Present mode: the same case as four screens, one thing on each, big
// enough to read from the back of a room. Nothing is computed here that the
// console does not already show; this is the console's data at 90 px.
//
//   1  the finding        the exchange, how sure, the address to cite
//   2  the route          the flow by hop, the traced transfers beneath
//   3  what was left out  four numbers, and the one-line screening facts
//   4  the handoff        the report, the hashes
//
// Arrow keys or space step; Escape returns to the console with everything
// still there.

const COMPONENT_NAME = { hop_proximity: 'Hop proximity', amount_correlation: 'Amount correlation', match_directness: 'Match directness' }
const num = (value) =>
  value >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : Number((value || 0).toFixed(6)).toString()
const short = (a) => (a ? `${a.slice(0, 8)}…${a.slice(-6)}` : '')

export default function Present({ result, related = [], unit, onClose }) {
  const [screen, setScreen] = useState(0)
  const reverse = result.direction === 'incoming'
  const total = 4

  const step = useCallback((d) => setScreen((s) => Math.max(0, Math.min(total - 1, s + d))), [])
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose() }
      else if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === ' ' || e.key === 'PageDown') { e.preventDefault(); step(1) }
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp' || e.key === 'PageUp') { e.preventDefault(); step(-1) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, step])

  const path = result.trace_path ?? []
  const risk = result.risk_matches ?? []
  const findings = result.findings ?? []
  const inferred = result.inferred_deposits ?? []
  const swaps = result.swaps ?? []
  const serviceContracts = result.graph.nodes.filter((n) => n.is_service_contract).length
  const components = result.confidence_detail?.components ?? []
  const band = String(result.confidence_detail?.band ?? '').replace(/^./, (c) => c.toUpperCase())

  const screens = [
    // 1 — the finding
    <div className="pr-screen pr-finding" key="finding">
      {risk.length > 0 && (
        <div className="pr-alert">
          {risk.map((m) => <span key={m.address}>{m.category === 'mixer' ? 'Mixer' : 'OFAC-listed'} · {m.entity} · {m.depth === 0 ? 'the reported address' : `${m.depth} hop${m.depth === 1 ? '' : 's'} away`}</span>)}
        </div>
      )}
      <div className="pr-main">
        <span className="micro">{reverse ? 'Where the money came from' : 'Where the money went'}</span>
        {result.exchange ? (
          <>
            <span className="pr-huge green">{result.exchange}</span>
            <p className="pr-lede">
              <span className="num">{num(result.value_received_native ?? 0)} {unit}</span> {reverse ? 'reached the reported wallet from' : 'from the reported wallet reached'}{' '}
              <span className="mono">{result.exchange_label ?? short(result.exchange_address)}</span>
              {result.attribution_inferred ? `, a wallet this tool infers to be a ${result.exchange} deposit address, ` : `, a wallet ${result.exchange} publicly operates, `}
              {result.hop_count} hop{result.hop_count === 1 ? '' : 's'} {reverse ? 'upstream' : 'away'}.
            </p>
            <div className="pr-cite">
              <span className="micro">{result.attribution_inferred ? 'Address to ask the exchange about' : 'Address to cite in the request'}</span>
              <span className="mono">{result.exchange_address}</span>
            </div>
          </>
        ) : (
          <>
            <span className="pr-huge none">{reverse ? 'No source exchange matched' : 'No exchange matched'}</span>
            <p className="pr-lede">{result.message ?? 'No address in the trace is in a published exchange label file. This is a finding, not a failure, and it is not scored.'}</p>
          </>
        )}
      </div>
      <div className="pr-side">
        <span className="micro">How sure</span>
        {result.confidence == null ? (
          <>
            <span className="pr-big muted">n/a</span>
            <span className="pr-note">Nothing attributed, so nothing to score.</span>
          </>
        ) : (
          <>
            <span className="pr-big green">{result.confidence.toFixed(2)}</span>
            <span className="pr-note">{band} · three inputs, nothing else</span>
            <div className="pr-bars">
              {components.map((c) => (
                <div className="pr-bar" key={c.name}>
                  <span>{COMPONENT_NAME[c.name] ?? c.name}</span>
                  <i><b style={{ width: `${Math.round(c.raw_value * 100)}%` }} /></i>
                  <span className="mono">{c.raw_value.toFixed(2)} × {c.weight}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>,

    // 2 — the route
    <div className="pr-screen pr-route" key="route">
      <div className="pr-rowhead">
        <span className="micro">How it got there · {result.graph.nodes.length} addresses · {result.graph.edges.length} transfers</span>
        <span className="micro">{reverse ? 'money flows into the reported wallet, right' : 'the traced funds in red, left to right'}</span>
      </div>
      <div className="pr-flow"><FlowView data={result.graph} tracePath={result.trace_path} unit={unit} direction={result.direction} /></div>
      <div className="pr-hops">
        {path.slice(1).map((s, i) => (
          <div className="pr-hop" key={s.address}>
            <span className="red">Hop {i + 1}</span>
            <span className="mono">{short(path[i].address)} <span className="faint">→</span> {s.exchange ? <span className="green">{s.label ?? s.exchange}</span> : short(s.address)}</span>
            <span className="mono">{num(s.value_native ?? 0)} {unit}</span>
          </div>
        ))}
        {path.length < 2 && <span className="pr-note">No attributed path — the transfers are in the console.</span>}
      </div>
    </div>,

    // 3 — what was left out
    <div className="pr-screen pr-evidence" key="evidence">
      <span className="micro">What the tool did not look at, and what it kept</span>
      <div className="pr-figures">
        <div className="pr-figure"><span className="pr-huge">{result.transfers_excluded_by_time ?? 0}</span><span>transfers made before the traced funds arrived — left out. Money cannot be forwarded before it is received.</span></div>
        <div className="pr-figure"><span className="pr-huge">{serviceContracts}</span><span>service contracts not expanded — WETH, pools, routers. Their payouts are other people's money.</span></div>
        {result.evidence?.count
          ? <div className="pr-figure"><span className="pr-huge">{result.evidence.count}</span><span>provider responses hashed at arrival, SHA-256. The report seals itself with one hash over them.</span></div>
          : <div className="pr-figure"><span className="pr-huge">{result.api_calls ?? 0}</span><span>provider requests made. This case was stored before responses were hashed; a re-trace would seal it.</span></div>}
        <div className="pr-figure"><span className="pr-huge amber">{related.length}</span><span>other stored complaints whose money passed through the same wallet as this one.</span></div>
      </div>
      <div className="pr-facts">
        <span><b>Sanctions</b> · {risk.length ? `${risk.length} listed address${risk.length === 1 ? '' : 'es'}` : 'no listed address'} · OFAC SDN</span>
        <span><b>Patterns</b> · {findings.length ? findings.map((f) => f.pattern.replace('_', ' ')).join(', ') : 'none matched'}</span>
        <span><b>Inferred deposits</b> · {inferred.length ? `${inferred.length} · probable ${inferred[0].exchange}, ${inferred[0].depth} hop${inferred[0].depth === 1 ? '' : 's'}` : 'none'}{swaps.length ? ` · ${swaps.length} swap${swaps.length === 1 ? '' : 's'}` : ''}</span>
        <span><b>Scope</b> · {result.api_calls} requests · depth {result.depth_reached} of {result.max_depth ?? '—'}{result.seconds_elapsed ? ` · ${result.seconds_elapsed} s` : ''}{result.time_budget_seconds ? ' · time cap' : ''}</span>
      </div>
    </div>,

    // 4 — the handoff
    <div className="pr-screen pr-handoff" key="handoff">
      <div className="pr-main">
        <span className="micro">Hand it over</span>
        <span className="pr-title">{result.exchange ? `Send the request to ${result.exchange}.` : 'Nothing to send yet.'}</span>
        <p className="pr-lede muted">
          {result.exchange
            ? 'The report names the address, the transaction hashes, amounts and times, and everything the tool did not look at. An exchange wallet identifies where the money went, not who received it; only the exchange can link it to a customer, on a lawful request (PMLA s.12, s.50).'
            : 'The report still lists every address and transaction in the trace, so each can be re-checked on a public explorer, and says exactly what was not looked at.'}
        </p>
        <div className="pr-actions"><ExportButton caseId={result.case_id} address={result.address} /></div>
      </div>
      <div className="pr-side">
        {result.evidence?.manifest_sha256 && <div className="pr-hash"><span className="micro">Evidence manifest</span><span className="mono">{result.evidence.manifest_sha256.slice(0, 20)}…</span></div>}
        <div className="pr-hash"><span className="micro">Traced</span><span className="mono">{String(result.created_at ?? '').replace('T', ' ').slice(0, 16)} UTC</span></div>
        <div className="pr-hash"><span className="micro">Case</span><span className="mono">{result.case_id}</span></div>
      </div>
    </div>,
  ]

  return (
    <div className="present" role="dialog" aria-label="Present the case">
      <div className="pr-top">
        <span className="pr-chrome"><span className="micro ink">Exchequer</span><span className="micro">Case {short(result.case_id ?? '')}</span><span className="micro">{short(result.address)}</span></span>
        <span className="pr-chrome"><span className="micro amber">Restricted</span><span className="micro">{screen + 1} / {total}</span><button type="button" className="quiet" onClick={onClose} title="Back to the console (Esc)">Esc · console</button></span>
      </div>
      {screens[screen]}
      <div className="pr-dots" aria-hidden="true">
        {Array.from({ length: total }, (_, i) => <span key={i} className={i === screen ? 'on' : ''} onClick={() => setScreen(i)} />)}
      </div>
      <div className="pr-foot micro">← → to step · Esc for the console</div>
    </div>
  )
}
