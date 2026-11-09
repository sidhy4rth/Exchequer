import { useEffect, useId, useMemo, useState } from 'react'
import { fetchRelatedCases } from '../../api'
import GraphView from '../GraphView'
import FlowView from '../FlowView'
import { PATTERN_VALIDATION, validationLine } from '../confidence'
import { plain } from '../../text'
import { entityGroups, groupLayout } from './entityGroups'
import { Address, PATTERN_NAME, RISK_NAME, middle, num, when } from './format'
import './EntitiesTab.css'

const count = (n, noun) => `${n} ${noun}${n === 1 ? '' : 's'}`
// A line toward the exchange is green, one into a frozen wallet red.
const tone = (to) => (['exchange', 'deposit', 'route'].includes(to) ? 'go' : to === 'frozen' ? 'risk' : 'plain')

/** The groups as a map: a bubble per group, as big as its wallet count, and a
 * line per pair, as wide as the gross amount between them. Each bubble is a
 * button that opens its group's card. */
function GroupMap({ groups, links, at, chosen, onChoose, labelledBy }) {
  const perColumn = groups.reduce((by, g) => ({ ...by, [g.depth]: (by[g.depth] ?? 0) + 1 }), {})
  const rows = Math.max(1, ...Object.values(perColumn))
  const height = Math.max(360, rows * 110)
  const most = Math.max(...links.map((l) => l.gross), 1)
  const curve = ({ x: x1, y: y1 }, { x: x2, y: y2 }) => {
    const [ax, ay, bx, by] = [x1 * 1000, y1 * height, x2 * 1000, y2 * height]
    const [c1, c2] = Math.abs(ax - bx) < 1 ? [ax + 90, bx + 90] : [(ax + bx) / 2, (ax + bx) / 2]
    return `M${ax} ${ay}C${c1} ${ay} ${c2} ${by} ${bx} ${by}`
  }
  return (
    <>
      <div className="ent-map" role="group" aria-labelledby={labelledBy} style={{ height }}>
        <svg className="ent-lines" aria-hidden="true" viewBox={`0 0 1000 ${height}`} preserveAspectRatio="none">
          {links.map((l) => (
            <path key={`${l.from}>${l.to}`} data-link={`${l.from}>${l.to}`} className={tone(l.to)} d={curve(at[l.from], at[l.to])} fill="none"
              strokeWidth={(1.5 + 8 * Math.sqrt(l.gross / most)).toFixed(2)} strokeDasharray={l.style === 'dashed' ? '6 5' : undefined} vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
        {groups.map((g) => (
          <button key={g.key} type="button" className={`ent-node${g.key === chosen ? ' on' : ''}`} aria-pressed={g.key === chosen}
            style={{ left: `${at[g.key].x * 100}%`, top: `${at[g.key].y * 100}%`, '--d': `${Math.round(Math.min(72, 24 + 10 * Math.sqrt(g.addresses.length - 1)))}px` }}
            onClick={() => onChoose(g.key)}>
            <span aria-hidden="true" className={`ent-bubble ${g.kind}${g.inferred ? ' inferred' : ''}${g.key === 'reported' ? ' reported' : ''}`} />
            <span className="ent-label">{g.name}<span className="ent-count">{` · ${count(g.addresses.length, 'wallet')}`}</span></span>
          </button>
        ))}
      </div>
      <p className="ent-legend">
        <span>bubble = wallets in the group</span>
        <span>line width = gross amount between groups; the victim's share is on Flow</span>
        <span>dashed = inferred</span>
      </p>
    </>
  )
}

/** How often a shape fired on real wallets (README, "Validation against real wallets"). */
function Measured({ pattern }) {
  const v = PATTERN_VALIDATION[pattern]
  if (!v) return null
  const dots = (n, of) => <span className="ent-dots">{Array.from({ length: of }, (_, i) => <span key={i} className={i < n ? 'on' : ''} />)}</span>
  return (
    <div className="ent-measured" role="img" aria-label={`${PATTERN_NAME[pattern]} seen in ${v.fraud} of ${v.fraudOf} documented fraud wallets and ${v.ordinary} of ${v.ordinaryOf} ordinary ones`}>
      {dots(v.fraud, v.fraudOf)}<span>{v.fraud} / {v.fraudOf} fraud wallets</span>
      {dots(v.ordinary, v.ordinaryOf)}<span>{v.ordinary} / {v.ordinaryOf} ordinary wallets</span>
    </div>
  )
}

/** The card for the group chosen: for a split, what came in and how it was
 * divided; for any group, the gross in and out of it and its wallets. */
function GroupCard({ group, groups, links, result, unit }) {
  const [open, setOpen] = useState(false)
  const listId = useId()
  const nodes = new Map(result.graph.nodes.map((n) => [n.address, n]))
  const edges = result.graph.edges
  const nameOf = Object.fromEntries(groups.map((g) => [g.key, g.name]))
  const splits = group.key === 'split' ? (result.findings ?? []).filter((f) => f.pattern === 'amount_split') : []
  // Each recipient's amount from the graph: the finding sorts its amounts but not its recipients.
  const paid = splits.flatMap((f) => edges.filter((e) => e.source === f.evidence.address && f.evidence.recipients.includes(e.target)))
    .sort((a, b) => b.value_native - a.value_native)
  const into = (a) => edges.filter((e) => e.target === a).reduce((sum, e) => sum + (e.value_native || 0), 0)
  const out = (a) => edges.filter((e) => e.source === a).reduce((sum, e) => sum + (e.value_native || 0), 0)
  const wallets = splits.length ? paid.map((e) => ({ address: e.target, amount: e.value_native, dir: 'in' }))
    : group.addresses.map((a) => (into(a) > 0 ? { address: a, amount: into(a), dir: 'in' } : { address: a, amount: out(a), dir: 'out' }))
  const risky = (a) => Boolean(nodes.get(a)?.risk_category)
  const tag = (n) => plain(n?.label) || RISK_NAME[n?.risk_category] || n?.risk_category || (n?.inferred_exchange ? `Probable ${plain(n.inferred_exchange)} deposit` : null)
  const flows = [...links.filter((l) => l.to === group.key).map((l) => ['In from', l.from, l]), ...links.filter((l) => l.from === group.key).map((l) => ['Out to', l.to, l])]
  return (
    <section className="card ent-card" aria-label={`Selected group: ${group.name}`}>
      <div className="ent-card-head">
        <h2>{group.name}</h2>
        {splits.length > 0 && <span className="pill amber">hint · a shape, not evidence</span>}
      </div>
      {splits.map((f) => {
        const amounts = paid.filter((e) => e.source === f.evidence.address).map((e) => e.value_native)
        return (
          <div className="ent-split" key={f.evidence.address}>
            <Address value={f.evidence.address} head={12} tail={10} />
            <p className="ent-split-sum">
              <span className="ent-split-in"><b>{num(f.evidence.total_in_native)}</b> in</span>
              <svg aria-hidden="true" width="40" height="12" viewBox="0 0 40 12" fill="none" strokeWidth="1.3"><path d="M1 6h36M33 2l4 4-4 4" /></svg>
              <span className="ent-split-out"><b>{f.evidence.branch_count}</b> recipients</span>
            </p>
            <div className="ent-bars" aria-hidden="true">
              {paid.filter((e) => e.source === f.evidence.address).map((e) => (
                <span key={e.target} title={`${num(e.value_native)} ${unit}`} className={risky(e.target) ? 'risk' : ''} style={{ height: `${Math.max(6, (100 * e.value_native) / amounts[0])}%` }} />
              ))}
            </div>
            <p className="note ent-range">
              <span>{`${num(Math.min(...amounts))} to ${num(amounts[0])} ${unit} each`}</span>
              <span>{` · the largest is ${Math.round(100 * f.evidence.largest_branch_share)}% of the total`}</span>
            </p>
            <Measured pattern="amount_split" />
          </div>
        )
      })}
      {flows.length > 0 && (
        <ul className="ent-flows">
          {flows.map(([dir, other, l]) => <li key={`${l.from}>${l.to}`}><span>{dir} {nameOf[other]}</span><span className="num">{num(l.gross)} {unit} gross</span></li>)}
        </ul>
      )}
      <button type="button" className="ent-open" aria-expanded={open} aria-controls={listId} onClick={() => setOpen((v) => !v)}>
        {`${open ? 'Hide' : 'Open'} the ${count(wallets.length, 'wallet')}`}
      </button>
      <ul className="ent-wallets" id={listId} hidden={!open}>
        {wallets.map((w) => (
          <li key={w.address}>
            <Address value={w.address} />
            {tag(nodes.get(w.address)) && <span className={`note${risky(w.address) ? ' risk' : ''}`}>{tag(nodes.get(w.address))}</span>}
            <span className="num">{num(w.amount)} {unit} {w.dir}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Other complaints that reached this case's wallets, from the case book
 * (GET /cases/correlate). A stored case's answer comes from the page; a
 * recorded or unsaved one is not in the book, so it asks which wallets two
 * or more stored complaints share and keeps the ones in this case, on this
 * case's chain (the book matches a wallet by chain and address). */
function OtherComplaints({ caseId, correlation, groups, own, chain }) {
  const [asked, setAsked] = useState(null)
  const headId = useId()
  useEffect(() => {
    if (caseId) return undefined
    let cancelled = false
    fetchRelatedCases(null)
      .then((r) => { if (!cancelled) setAsked(r) })
      .catch(() => { if (!cancelled) setAsked({ failed: true }) })
    return () => { cancelled = true }
  }, [caseId])
  const data = caseId ? correlation : asked
  const groupOf = new Map(groups.flatMap((g) => g.addresses.map((a) => [a.toLowerCase(), g.name])))
  const me = String(own ?? '').toLowerCase()
  const onChain = String(chain || 'ethereum')
  const shared = (data?.clusters ?? [])
    .filter((c) => String(c.chain || 'ethereum') === onChain && groupOf.has(String(c.address).toLowerCase()))
    .map((c) => ({
      address: c.address,
      group: groupOf.get(String(c.address).toLowerCase()),
      others: (c.reported_addresses ?? []).filter((a) => String(a).toLowerCase() !== me).length + (c.other_complaints ?? 0),
    }))
    .filter((s) => s.others > 0)
  return (
    <section className="card ent-other" aria-labelledby={headId}>
      <h2 id={headId}>Other complaints</h2>
      <svg className="ent-other-mark" aria-hidden="true" viewBox="0 0 300 30" fill="none">
        <circle cx="15" cy="15" r="12" /><path className="them" d="M33 15h96M171 15h96" /><circle className="them" cx="150" cy="15" r="9" /><circle className="them" cx="285" cy="15" r="12" />
      </svg>
      {data == null && <p className="note">Checking the case book…</p>}
      {data?.failed && <p className="note">The case book could not be checked just now.</p>}
      {data && !data.failed && (shared.length > 0 ? (
        <ul className="ent-shared">
          {shared.map((s) => (
            <li key={s.address}><Address value={s.address} /><span className="note">{s.group}</span><span>{count(s.others, 'other complaint')}</span></li>
          ))}
        </ul>
      ) : (
        <p className="note">{caseId
          ? 'No other stored complaint shares a wallet with this case yet. When one does, it appears here with the wallet they share.'
          : "This case is not in the case book, so only wallets that two or more stored complaints already share can show here. None of this case's wallets is one yet."}</p>
      ))}
    </section>
  )
}

/** The Entities view: who the wallets are, by the role each plays, then the
 * hints, inferred deposits, swaps, related cases and funders of the case. */
export default function EntitiesTab({ result, unit, correlation }) {
  const headId = useId()
  const reverse = result.direction === 'incoming'
  const { groups, links } = useMemo(() => entityGroups(result), [result])
  const at = useMemo(() => groupLayout(groups, { reverse }), [groups, reverse])
  const [view, setView] = useState('grouped')
  const [chosen, setChosen] = useState(() => (groups.find((g) => g.key === 'split') ?? groups.find((g) => g.key === 'exchange') ?? groups[0])?.key)
  const group = groups.find((g) => g.key === chosen)
  const inferred = result.inferred_deposits ?? []
  const findings = result.findings ?? []
  const swaps = result.swaps ?? []
  const followOns = (result.follow_ons ?? []).filter((f) => f.result)
  const related = correlation?.related_cases ?? []
  const funders = result.direct_senders ?? []
  return (
    <>
      <div className={`ent-layout${view === 'every' ? ' every' : ''}`}>
        <section className="card ent-groups" aria-labelledby={headId}>
          <div className="ent-head">
            <h2 id={headId}>{count(result.graph.nodes.length, 'wallet')} in {count(groups.length, 'group')}</h2>
            <span className="ent-toggle">
              <button type="button" aria-pressed={view === 'grouped'} onClick={() => setView('grouped')}>Grouped</button>
              <button type="button" aria-pressed={view === 'every'} onClick={() => setView('every')}>Every wallet</button>
            </span>
          </div>
          {view === 'grouped'
            ? <GroupMap groups={groups} links={links} at={at} chosen={chosen} onChoose={setChosen} labelledBy={headId} />
            : (
              <div className="ent-every">
                <div className="stage"><GraphView data={result.graph} tracePath={result.trace_path} unit={unit} /></div>
                <FlowView data={result.graph} tracePath={result.trace_path} unit={unit} direction={result.direction} />
              </div>
            )}
        </section>
        <div className="ent-side">
          {group && <GroupCard key={group.key} group={group} groups={groups} links={links} result={result} unit={unit} />}
          <OtherComplaints caseId={result.case_id} correlation={correlation} groups={groups} own={result.address} chain={result.chain} />
        </div>
      </div>

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
                    {e.current_balance_native != null && <><span className="tk">current balance</span><span className="tv">{num(e.current_balance_native)} {e.current_balance_symbol ?? result?.chain_native_symbol ?? unit}</span></>}
                    {e.first_sweep && <><span className="tk">sweeps between</span><span className="tv">{when(e.first_sweep).slice(0, 10)} – {when(e.last_sweep).slice(0, 10)}</span></>}
                  </div>
                </div>
              )
            })}
          </div>
        </details>
      )}

      {findings.length > 0 ? (
        <details className="card sec">
          <summary><span className="micro">Hints · {findings.length}</span><span className="pill amber">a shape, not evidence</span></summary>
          <div className="body">
            {findings.map((f) => (
              <div className="rule-block" key={f.pattern}>
                <div className="top"><span className="nm amber">{PATTERN_NAME[f.pattern] ?? f.pattern}</span></div>
                <div className="desc">{f.description}</div>
                {validationLine(f.pattern) && <p className="hint-rate">{validationLine(f.pattern)}</p>}
                {f.evidence?.thresholds_applied && (
                  <div className="thresholds">
                    {Object.entries(f.evidence.thresholds_applied).map(([k, v]) => (
                      <span key={k} style={{ display: 'contents' }}><span className="tk">{k}</span><span className="tv">{String(v)}</span></span>
                    ))}
                  </div>
                )}
              </div>
            ))}
            <p className="note">A hint is a reason to look closer, not a finding: it never moves the score and should not appear in a request as evidence.</p>
          </div>
        </details>
      ) : (
        <div className="card sec flat"><span className="micro">Hints · none</span><span className="note">no peel chain or amount split</span></div>
      )}

      {swaps.length > 0 && (
        <details className="card sec" open={!result.exchange}>
          <summary><span className="micro">Swaps · {swaps.length}</span><span className="note">the trace changes asset here</span></summary>
          <div className="body">
            {swaps.map((s) => (
              <div className="swap" key={s.tx}>
                <Address value={s.sender} head={8} tail={6} /> sent <span className="num">{num(s.amount_in)} {s.asset_in}</span> to <strong>{s.router_label}</strong>
                {s.output_read
                  ? s.amount_out != null
                    ? <> and got <span className="num">{num(s.amount_out)} {s.asset_out}</span> back. {followOns.some((f) => f.address === s.sender && f.asset === s.asset_out)
                      ? <>The {s.asset_out} is followed from here — see <em>Continued in {s.asset_out}</em>.</>
                      : <>Re-run on {s.asset_out} from the sender to follow it further.</>}</>
                    : <> and got <span className="num">{s.amount_out_units}</span> raw units of an unlisted token{s.asset_out_contract ? <> (<Address value={s.asset_out_contract} head={8} tail={6} />)</> : null} back. Its decimals are not known, so the amount is not converted, and Exchequer does not trace that token — the trail stops here.</>
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
              <div className="related-case" key={c.case_id ?? c.ref}>
                <div className="top">
                  {c.hidden
                    ? <span className="mono" title="Traced by someone else; only the wallets it shares with this case are shown">{c.ref}</span>
                    : <a href={`/case/${c.case_id}`} className="mono" title={c.reported_address}>{middle(c.reported_address, 10, 8)}</a>}
                  <span className="st">{c.shared_count} shared wallet{c.shared_count === 1 ? '' : 's'}</span>
                </div>
                <div className="ent">{c.exchange ? `reached ${c.exchange}` : 'no exchange matched'}{c.traced_at ? ` · traced ${String(c.traced_at).slice(0, 10)}` : ''}</div>
                {c.shared.slice(0, 3).map((s) => (
                  <div className="row" key={s.address}>
                    <Address value={s.address} head={10} tail={8} />
                    <span className="via">{s.inferred_exchange ? `probable ${s.inferred_exchange} deposit · ` : ''}{s.risk_category ? `${RISK_NAME[s.risk_category] ?? s.risk_category} · ` : ''}{s.value_in_native == null ? (s.after_swap_to ? `after a swap to ${s.after_swap_to}` : c.asset) : `${num(s.value_in_native)} ${s.after_swap_to ?? c.asset}${s.after_swap_to ? ' after a swap' : ''}`}</span>
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
    </>
  )
}
