import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchRecheck, runRecheck } from '../../api'
import { useCaseFiles } from '../ExportButton'
import { plain } from '../../text'
import { ist, middle, mmss, num, txUrl } from './format'

/** Truncation reasons come back one sentence per address. Grouped by kind
 * they read as a summary rather than a wall. */
function groupReasons(reasons) {
  const counts = { depth: 0, nodes: 0, fanout: 0, service: 0, fetch: 0, history: 0, other: [] }
  ;(reasons ?? []).forEach((r) => {
    if (r.startsWith('time budget')) counts.other.push(r)
    else if (r.startsWith('depth limit')) counts.depth += 1
    else if (r.startsWith('node limit')) counts.nodes += 1
    else if (r.startsWith('fan-out limit')) counts.fanout += 1
    else if (r.includes('pays out to many addresses')) counts.service += 1
    else if (r.includes('could not be fetched')) counts.fetch += 1
    else if (r.startsWith('history read limit')) counts.history += 1
    else counts.other.push(r)
  })
  const out = []
  if (counts.depth) out.push('the hop limit was reached')
  if (counts.nodes) out.push('the address limit was reached')
  if (counts.fanout) out.push(`only the 10 largest counterparties were followed at ${counts.fanout} address${counts.fanout === 1 ? '' : 'es'}`)
  if (counts.service) out.push(`${counts.service} service contract${counts.service === 1 ? '' : 's'} not expanded`)
  if (counts.fetch) out.push(`${counts.fetch} address${counts.fetch === 1 ? '' : 'es'} could not be fetched`)
  // A read that stopped at its record limit: spam can fill one, so the case may miss transfers there.
  if (counts.history) out.push(`history not read in full at ${counts.history} address${counts.history === 1 ? '' : 'es'} (each read stopped at its record limit)`)
  return out.concat(counts.other)
}

const FIRST_ROWS = 12
const PROVIDER = { trongrid: 'TronGrid', tronscan: 'TronScan', etherscan: 'Etherscan', nodereal: 'NodeReal' }
// A second provider's word on a transfer, worst first: a hash that carried
// several transfers shows the worst of them.
const CHECKS = [['differs', 'differs', 'risk'], ['not_found', 'not found', 'risk'], ['error', 'could not be read', 'wait'], ['matches', 'matches', 'go']]
const rank = (status) => { const i = CHECKS.findIndex(([key]) => key === status); return i < 0 ? 2 : i }
// What a freeze's text says, for a case stored before frozen_on and event_tx.
const FREEZE_DAY = / on (\d{4}-\d{2}-\d{2})\b/
const FREEZE_EVENT = /\bAddedBlackList event, tx ((?:0x)?[0-9a-fA-F]{64})\b/
const day = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

const Glyph = ({ d }) => (
  <svg aria-hidden="true" width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d={d} /></svg>
)

/** The trace that reached the exchange, as request_letters._attribution
 * finds it: the case's own, else a follow-on's after a swap. */
const attributed = (result) => (result.exchange ? { trace: result } : (() => {
  const follow = (result.follow_ons ?? []).find((f) => f.result?.exchange)
  return follow && { trace: follow.result, follow }
})())

/** Each transfer between neighbouring steps of a path, numbered from `first`.
 * A path always runs the way the money moved, a reverse trace's included. */
function onRoute(steps, transfers, first, asset) {
  const path = (steps ?? []).map((step) => step.address)
  const hopOf = new Map()
  path.slice(1).forEach((to, i) => { if (!hopOf.has(`${path[i]}>${to}`)) hopOf.set(`${path[i]}>${to}`, first + i) })
  return (transfers ?? []).flatMap((t, i) => {
    const hop = hopOf.get(`${t.from}>${t.to}`)
    return hop ? [{ key: `${asset ?? ''}${t.hash}-${i}`, hop, step: `Hop ${hop}`, hash: t.hash, from: t.from, to: t.to, amount: t.value_native, time: t.timestamp, asset }] : []
  })
}

/** The transfers the case cites from the payment to the exchange: the
 * victim's payments as given, then every transfer on the route's hops in
 * time order; after a swap, the route to it, the swap and the follow-on's
 * route in its own asset. From `transfers`, which always keeps the route
 * whole; trace_path keeps only 20 hashes a hop. */
export function chainRows(result) {
  const found = attributed(result)
  const paid = result.intake?.mode === 'payment' ? result.intake.payments ?? [] : []
  const legs = [paid.map((p, i) => ({ key: `pay-${i}`, hop: 0, step: 'Payment', hash: p.tx_hash ?? null, from: p.from ?? null, to: p.to ?? result.address, amount: p.amount, time: p.timestamp }))]
  if (found?.follow) {
    const { follow } = found, swap = follow.swap ?? {}, before = follow.route?.length ?? 0
    legs.push(onRoute(follow.route, result.transfers, 1, null))
    legs.push((result.transfers ?? []).filter((t) => swap.tx && t.hash === swap.tx && t.from === swap.sender)
      .map((t, i) => ({ key: `swap-${i}`, hop: before, step: 'Swap', hash: t.hash, from: t.from, to: t.to, amount: t.value_native, time: t.timestamp })))
    legs.push(onRoute(found.trace.trace_path, found.trace.transfers, Math.max(1, before), plain(follow.asset)))
  } else if (found) legs.push(onRoute(result.trace_path, result.transfers, 1, null))
  // In time order, a leg's rows before the next leg's at the same moment.
  return legs.flatMap((rows, leg) => rows.map((r) => ({ ...r, leg })))
    .sort((a, b) => (a.leg && b.leg ? (a.time ?? 0) - (b.time ?? 0) : 0) || a.leg - b.leg || a.hop - b.hop)
    .map(({ leg, ...r }) => r)
}

/** A full hash, in mono, that copies itself when pressed. Drawn as two even
 * lines, which read more easily than a wrap and fit every column. */
function Hash({ value }) {
  const [copied, setCopied] = useState(false)
  // The mark clears itself, and its timer goes with the button: a timer left
  // running would set state on a page that is no longer there.
  useEffect(() => {
    if (!copied) return undefined
    const timer = setTimeout(() => setCopied(false), 1100)
    return () => clearTimeout(timer)
  }, [copied])
  const copy = () => navigator.clipboard?.writeText(value).then(() => setCopied(true), () => {})
  const half = Math.ceil(value.length / 2)
  return (
    <button type="button" className="ev-hash mono" title="Copy the hash" onClick={copy}>
      <span>{value.slice(0, half)}</span><span>{value.slice(half)}{copied && <span className="ev-copied"> copied</span>}</span>
    </button>
  )
}

/** The case's last second-provider recheck, and a way to run one. null hides
 * it: none yet asked for, or this server has no recheck (404, 405). */
function useRecheck(id) {
  const [recheck, setRecheck] = useState(null)
  const [running, setRunning] = useState(false)
  const [refused, setRefused] = useState(null)
  useEffect(() => {
    setRecheck(null)
    setRefused(null)
    if (!id) return undefined
    let live = true
    fetchRecheck(id).then((r) => { if (live) setRecheck(r) }, () => {})
    return () => { live = false }
  }, [id])
  async function run() {
    setRunning(true)
    setRefused(null)
    try {
      setRecheck(await runRecheck(id))
    } catch (err) {
      setRefused(err.message)
    } finally {
      setRunning(false)
    }
  }
  return { recheck, running, refused, run }
}

function Check({ found, after }) {
  if (!found) return <span className="ev-check wait">{after ? 'not checked' : 'not checked yet'}</span>
  const [, word, tone] = CHECKS[rank(found.status)]
  return <>
    <span className={`ev-check ${tone}`}>{word}</span>
    {found.status !== 'matches' && found.detail && <small className="ev-check-detail">{plain(found.detail)}</small>}
  </>
}

/** The case's Evidence tab (pack 2-glass-07): the route transfer by transfer,
 * the freeze records, what the trace read, the signed report, and its scope. */
export default function EvidenceTab({ result, unit, depth, recorded, recheckId }) {
  const [showAll, setShowAll] = useState(false)
  const rows = useMemo(() => chainRows(result), [result])
  const labels = useMemo(() => new Map(result.graph.nodes.filter((n) => n.label).map((n) => [n.id, plain(n.label)])), [result])
  const { recheck, running, refused, run } = useRecheck(recheckId)
  const checks = useMemo(() => {
    const byHash = new Map()
    for (const t of recheck?.transfers ?? []) {
      if (!byHash.has(t.hash) || rank(t.status) < rank(byHash.get(t.hash).status)) byHash.set(t.hash, t)
    }
    return byHash
  }, [recheck])
  const files = useCaseFiles(result.case_id, result.address ?? '')

  const who = (address) => (address ? labels.get(address) ?? middle(address, 4, 4) : 'hidden')
  const explorer = result.explorer_url?.replace(/^https?:\/\//, '')
  const frozen = (result.risk_matches ?? []).filter((m) => m.category === 'frozen')
  const issuers = [...new Set(frozen.map((m) => plain(m.issuer) || 'the issuer'))]
  const freezeSays = [...new Set(frozen.map((m) => plain(m.source)?.replace(/,?\s*(sample )?tx (0x)?[0-9a-fA-F]{64}.*$/, '')).filter(Boolean))]
  const evidence = result.evidence
  const readFrom = ist(evidence?.first_retrieved_at)
  const readTo = ist(evidence?.last_retrieved_at)
  const caveats = result.confidence_detail?.caveats ?? []
  const serviceContracts = result.graph.nodes.filter((n) => n.is_service_contract)
  const swaps = result.swaps ?? []
  const grouped = groupReasons(result.truncation_reasons)
  const scopeLine = [
    result.transfers_excluded_by_time ? `${result.transfers_excluded_by_time} pre-arrival transfers left out` : null,
    serviceContracts.length ? `${serviceContracts.length} service contract${serviceContracts.length === 1 ? '' : 's'}` : null,
    swaps.length ? `${swaps.length} swap${swaps.length === 1 ? '' : 's'}` : null,
    evidence?.count ? `${evidence.count} responses hashed` : null,
  ].filter(Boolean).join(' · ')

  return <>
    <section className="card ev-chain" aria-labelledby="ev-chain-title">
      <div className="ev-chain-head">
        <div>
          <h2 id="ev-chain-title">The chain, transfer by transfer</h2>
          <p className="note">{result.direction === 'incoming' ? 'From the exchange to the reported address.' : 'From the payment to the exchange.'} Every row can be re-read on the chain.</p>
        </div>
        {recheck && (
          <button type="button" className="ev-go" onClick={run} disabled={running}>
            <Glyph d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3" />{running ? 'Re-reading…' : 'Re-read from a second provider'}
          </button>
        )}
      </div>
      {recheck && (
        // Mounted empty before the first reread, so a screen reader hears it fill.
        <p className={recheck.checked_at ? 'note ev-chain-line' : 'visually-hidden'} role="status">{recheck.checked_at && <>
          Re-read from {plain(recheck.provider)} · {ist(recheck.checked_at)} IST · {recheck.checked} of {recheck.cited} cited transfers
          {recheck.skipped ? ` · ${recheck.skipped} cannot be re-read yet (native TRX, or moved by a contract call)` : ''}
          {recheck.recorded_demo ? " · a recorded example's recheck is shown, not kept" : ''}
        </>}</p>
      )}
      {refused && <p className="error-line ev-chain-line" role="alert">The recheck did not run: {refused}</p>}
      {rows.length === 0 ? <p className="note ev-chain-line">{attributed(result) ? 'The case holds no transfers on the route.' : 'The trace reached no exchange, so the case cites no transfers.'}</p> : (
        // Where the columns are wider than the card it scrolls, never cuts them off.
        <div className="ev-scroll" role="region" aria-label="Route transfers" tabIndex={0}><table className="ev-table" aria-labelledby="ev-chain-title">
          <thead>
            <tr>
              <th scope="col">Step</th><th scope="col">IST</th><th scope="col">From → to</th><th scope="col" className="ev-amt">Amount</th>
              <th scope="col">Transaction</th><th scope="col">Explorer</th>{recheck && <th scope="col">Second provider</th>}
            </tr>
          </thead>
          <tbody>
            {(showAll ? rows : rows.slice(0, FIRST_ROWS)).map((r) => {
              const link = txUrl(result.explorer_url, result.chain, r.hash)
              return (
                <tr key={r.key}>
                  <td className="ev-step"><span className={`ev-dot${r.hop ? ' go' : ''}`} aria-hidden="true" />{r.step}</td>
                  <td className="ev-when">{ist(r.time)}</td>
                  <td className="ev-pair mono">
                    <span title={r.from ?? undefined}>{who(r.from)}</span><span aria-hidden="true"> → </span><span className="visually-hidden"> to </span><span title={r.to}>{who(r.to)}</span>
                  </td>
                  <td className="ev-amt"><span className="num">{num(r.amount)}</span> <span className="ev-unit">{r.asset ?? unit}</span></td>
                  <td className="ev-tx">{r.hash ? <Hash value={r.hash} /> : <span className="note">hash withheld</span>}</td>
                  <td className="ev-link">{link && <a href={link} target="_blank" rel="noreferrer">{explorer}</a>}</td>
                  {recheck && <td className="ev-second"><Check found={r.hash && checks.get(r.hash)} after={Boolean(recheck.checked_at)} /></td>}
                </tr>
              )
            })}
          </tbody>
        </table></div>
      )}
      {rows.length > FIRST_ROWS && (
        <button type="button" className="quiet ev-more" onClick={() => setShowAll((v) => !v)}>{showAll ? 'Show fewer' : `Show all ${rows.length} transfers`}</button>
      )}
    </section>

    <div className="ev-cards">
      {frozen.length > 0 && (
        <article className="ev-card risk">
          <h2><Glyph d="M8 1.5v13M2.4 4.8l11.2 6.4M13.6 4.8 2.4 11.2" />Freeze records · {issuers.join(', ')}</h2>
          {freezeSays.map((s) => <p className="ev-says" key={s}>{s}</p>)}
          {frozen.map((m) => {
            const on = 'frozen_on' in m ? m.frozen_on : FREEZE_DAY.exec(m.label ?? '')?.[1]
            const tx = 'event_tx' in m ? m.event_tx : FREEZE_EVENT.exec(m.source ?? '')?.[1]
            return (
              <div className="ev-item" key={m.address}>
                <span className="ev-k">{m.depth === 0 ? 'Reported wallet' : `Hop ${m.depth} wallet`} {middle(m.address, 4, 4)}{on ? ` · frozen ${day(on)}` : ''}</span>
                {tx ? <Hash value={tx} /> : <span className="note">no event transaction on file</span>}
              </div>
            )
          })}
        </article>
      )}

      {evidence?.count > 0 && (
        <article className="ev-card">
          <h2><Glyph d="M3 2h10v12H3zM5.5 5.5h5M5.5 8h5M5.5 10.5h3" />What the trace read</h2>
          <div className="ev-stats">
            <p><span className="ev-big">{evidence.count}</span> responses hashed</p>
            <p><span className="ev-big">{evidence.providers?.length ?? 0}</span> provider{evidence.providers?.length === 1 ? '' : 's'}</p>
            {result.api_calls != null && <p><span className="ev-big">{result.api_calls}</span> request{result.api_calls === 1 ? '' : 's'}</p>}
          </div>
          <p className="ev-says">
            {(evidence.providers ?? []).map((p) => PROVIDER[p] ?? plain(p)).join(', ')}
            {readFrom && readTo ? ` · read ${readFrom} to ${readFrom.slice(0, -6) === readTo.slice(0, -6) ? readTo.slice(-5) : readTo} IST` : ''}
          </p>
          {evidence.from_cache > 0 && <p className="note">{evidence.from_cache} came from the cache, each with the time it was first read.</p>}
          <div className="ev-item">
            <span className="ev-k">Manifest SHA-256 · every response is listed in the report, which carries its own content hash</span>
            <Hash value={evidence.manifest_sha256} />
          </div>
        </article>
      )}

      <article className="ev-card">
        <h2><Glyph d="M8 1.8l5 2v4.1c0 3-2.2 5.2-5 6.3-2.8-1.1-5-3.3-5-6.3V3.8zM5.6 8.1l1.7 1.7 3.2-3.3" />Signed report</h2>
        <p className="ev-says">Text and PDF, signed by the server. Anyone can check a copy on the <Link to="/verify">Verify page</Link>.</p>
        {caveats.length > 0 && (
          <details className="ev-limits">
            <summary>Limits stated in the report · {caveats.length}</summary>
            <ul>{caveats.map((c) => <li key={c}>{c}</li>)}</ul>
          </details>
        )}
        {result.case_id ? (
          <div className="ev-files">
            <button type="button" className="ev-file solid" onClick={() => files.report('pdf')} disabled={files.busy !== null}>
              <Glyph d="M8 2v8M4.5 6.5 8 10l3.5-3.5M2.5 13h11" />PDF<span className="visually-hidden"> of the signed report</span>
            </button>
            <button type="button" className="ev-file" onClick={() => files.report('text')} disabled={files.busy !== null}>Text<span className="visually-hidden"> of the signed report</span></button>
            <button type="button" className="ev-file" onClick={() => files.graph('graphml')} disabled={files.busy !== null}>Graph file<span className="visually-hidden"> (GraphML)</span></button>
          </div>
        ) : (
          <p className="note">{recorded
            ? 'A recorded example has no report of its own: Trace live runs it again now and stores it as a case, with a signed report.'
            : 'This trace was not saved, so it has no report.'}</p>
        )}
        {files.error && <p className="error-line" role="alert">The file could not be prepared: {files.error}</p>}
      </article>
    </div>

    <details className="card sec" open>
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
        {result.untraced?.length > 0 && (
          <div className="exclusion untraced">
            <span className="n num">{num(result.untraced.reduce((sum, u) => sum + u.value_native, 0))}</span>
            <span className="t">{unit} sent on but not followed<small>{result.untraced.reduce((sum, u) => sum + u.counterparties, 0)} smaller destinations of {result.untraced.length} address{result.untraced.length === 1 ? '' : 'es'}: {result.untraced.some((u) => u.rule === 'top_n') ? 'the walk follows the ten largest of each' : 'each carried less than the share the walk follows'}. Where these went is not in this case.</small></span>
          </div>
        )}
        {result.addresses_unexpanded_by_time > 0 && (
          <div className="exclusion">
            <span className="n">{result.addresses_unexpanded_by_time}</span>
            <span className="t">addresses reached but not expanded<small>The {mmss(result.time_budget_seconds)} time cap ran out first; the graph beyond them is missing.</small></span>
          </div>
        )}
        {result.addresses_unexpanded_by_budget > 0 && (
          <div className="exclusion">
            <span className="n">{result.addresses_unexpanded_by_budget}</span>
            <span className="t">addresses reached but not expanded<small>The case's provider request budget ran out first; the graph beyond them is missing.</small></span>
          </div>
        )}
        <div className="exclusion">
          <span className="n">{result.api_calls}</span>
          <span className="t">provider requests<small>{result.transfers_total ?? result.transfers?.length ?? 0} individual transactions{result.transfers_omitted ? ` (${result.transfers?.length ?? 0} listed)` : ''}; depth {result.depth_reached} reached of {result.max_depth ?? depth}{result.seconds_elapsed ? `; ${result.seconds_elapsed} s` : ''}.</small></span>
        </div>
        {grouped.length > 0 && <ul className="reasons">{grouped.map((r) => <li key={r}>{r}</li>)}</ul>}
        {result.warnings?.length > 0 && result.warnings.map((w) => <p className="note" key={w}>! {w}</p>)}
      </div>
    </details>
  </>
}
