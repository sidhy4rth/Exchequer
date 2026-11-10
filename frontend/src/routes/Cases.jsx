import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchCases, fetchLinkedComplaints } from '../api'
import { SHORT_CHAIN } from '../components/TraceForm'
import { bandLabel, bandOf } from '../components/confidence'
import { useMedia } from '../phone'
import { plain } from '../text'

// The Cases page (/cases): every stored case this browser may see, its own
// and the recorded demos, with what each reached and how sure (the band
// word, never the score). Filters and the search read the cases already
// loaded. Below them, the complaints that meet at one wallet
// (GET /cases/correlate). Every figure is the backend's.

// The backend's most: a browser keeps up to 200 cases (MAX_CASES_PER_OWNER)
// and sees the recorded demos too, so the search reaches its oldest case.
const LIMIT = 500
// Above the phone break the sidebar keeps 248 px, and the seven columns need
// about 700 px beside it to fit with each wallet on two lines at most; below
// this a tablet (744 to 834 px) shows the cases as cards, as a phone does.
const CARDS = '(max-width: 959px)'
const CHAINS = Object.keys(SHORT_CHAIN)
const rank = (key) => (CHAINS.includes(key) ? CHAINS.indexOf(key) : CHAINS.length)
const nameOf = (key) => SHORT_CHAIN[key] ?? key
const RISK_WORD = { frozen: 'frozen by issuer', stolen: 'stolen funds', reported: 'TronScan warning', gambling: 'gambling platform', poisoning: 'address poisoning', scam: 'reported scam', laundering: 'laundering', mixer: 'mixer' }
const middle = (a) => (a && a.length > 23 ? `${a.slice(0, 12)}…${a.slice(-10)}` : a)
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

// The store keeps UTC; an officer reads the day in India.
const IST = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' })
function tracedOn(at) {
  const text = String(at ?? '')
  const when = new Date(/(Z|[+-]\d\d:?\d\d)$/i.test(text) ? text : `${text}Z`)
  return Number.isNaN(when.getTime()) ? '—' : IST.format(when)
}

/** The filter pills: everything, by what was reached, then one per chain
 * present, in the order the trace form lists them. */
function filtersFor(cases) {
  const chains = [...new Set(cases.map((c) => c.chain))].sort((a, b) => rank(a) - rank(b) || String(a).localeCompare(String(b)))
  return [
    { key: 'all', label: 'All', keeps: () => true },
    { key: 'reached', label: 'Reached an exchange', keeps: (c) => Boolean(c.exchange) },
    { key: 'none', label: 'No exchange', keeps: (c) => !c.exchange },
    ...chains.map((chain) => ({ key: `chain:${chain}`, label: nameOf(chain), keeps: (c) => c.chain === chain })),
  ]
}

const matches = (c, q) => !q || [c.address, plain(c.exchange), c.case_id].some((v) => v && String(v).toLowerCase().includes(q))

const Marks = ({ c }) => <>{c.direction === 'incoming' && <span className="pill">reverse</span>}{c.demo && <span className="pill">demo</span>}</>

function CaseTable({ cases }) {
  const navigate = useNavigate()
  return (
    <table className="cases-list" aria-label="Stored cases">
      <thead>
        <tr><th>Reported wallet</th><th>Chain</th><th>Reached</th><th>How sure</th><th className="end">Hops</th><th className="end">Wallets</th><th>Traced (IST)</th></tr>
      </thead>
      <tbody>
        {cases.map((c) => {
          const band = bandOf(c.confidence)
          return (
            // The link is the way in by keyboard; a click anywhere on the row is a shortcut for the mouse.
            <tr key={c.case_id} className="row" onClick={(e) => { if (!e.target.closest('a')) navigate(`/case/${c.case_id}`) }}>
              <td className="cases-wallet"><Link to={`/case/${c.case_id}`} className="mono">{c.address}</Link><Marks c={c} /></td>
              <td className="soft">{[nameOf(c.chain), c.asset].filter(Boolean).join(' ')}</td>
              <td className={c.exchange ? '' : 'faint'}>{c.exchange ? plain(c.exchange) : 'no exchange reached'}</td>
              <td><span className={`case-band ${band ? band.replace(' ', '-') : 'none'}`}>{band ? bandLabel(band) : 'n/a'}</span></td>
              <td className="num">{c.exchange && c.hop_count != null ? c.hop_count : '—'}</td>
              <td className="num">{c.node_count ?? '—'}</td>
              <td className="faint">{tracedOn(c.created_at)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/** On a phone or a tablet: one card per case, as the Console lists its recent ones. */
function CaseCards({ cases }) {
  return (
    <ul className="recent-cases cases-cards" aria-label="Stored cases">
      {cases.map((c) => {
        const band = bandOf(c.confidence)
        const meta = [[nameOf(c.chain), c.asset].filter(Boolean).join(' '), c.exchange && c.hop_count != null && plural(c.hop_count, 'hop'),
          c.node_count != null && plural(c.node_count, 'wallet'), tracedOn(c.created_at)].filter(Boolean).join(' · ')
        return (
          <li key={c.case_id}>
            <Link to={`/case/${c.case_id}`}>
              <span className="mono recent-address">{c.address}</span>
              <span className="recent-meta">{meta}<Marks c={c} /></span>
              <span className={`recent-reached${c.exchange ? '' : ' none'}`}><i aria-hidden="true" />{c.exchange ? plain(c.exchange) : 'No exchange'}</span>
              {band && <span className={`recent-band ${band.replace(' ', '-')}`}><span className="visually-hidden">Confidence </span>{bandLabel(band)}</span>}
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

/** The cases this browser can open, one per reported wallet: its latest
 * trace (the members come newest first). A wallet traced twice is one
 * complaint. */
function latestPerWallet(members) {
  const seen = new Set()
  return members.filter((m) => {
    const wallet = m.reported_address?.toLowerCase()
    if (!m.case_id || seen.has(wallet)) return false
    seen.add(wallet)
    return true
  })
}

/** Wallets that two or more complaints both reach. An exchange's own wallet
 * never counts (correlation.py): two victims paid out at one exchange share
 * a bank, not an offender. */
function LinkedComplaints() {
  // undefined while asking; null when the store cannot be asked.
  const [linked, setLinked] = useState(undefined)
  const [all, setAll] = useState(false)
  useEffect(() => { fetchLinkedComplaints().then((d) => setLinked(d.clusters ?? [])).catch(() => setLinked(null)) }, [])
  const shown = all ? linked : linked?.slice(0, 5)
  return (
    <section className={`card glass cases-linked${linked?.length ? '' : ' quiet-card'}`} aria-labelledby="cases-linked">
      <span className="linked-mark" aria-hidden="true"><i /><b /><i className="dot" /><b /><i /></span>
      <div className="linked-body">
        <h2 id="cases-linked">Linked complaints</h2>
        {linked === undefined && <p className="note">Checking your cases…</p>}
        {linked === null && <p className="note">Linked complaints cannot be checked right now.</p>}
        {linked?.length === 0 && <p className="note">None of your cases shares a wallet with another yet. When two complaints meet at one wallet, they are linked here.</p>}
        {linked?.length > 0 && (
          <>
            <p className="note">{`Your complaints meet at ${linked.length === 1 ? 'one wallet' : `${linked.length} wallets`}. An exchange's own wallet never counts: two complaints that reached one exchange share a bank, not an offender.`}</p>
            <ul className="linked-list">
              {shown.map((w) => {
                const traces = latestPerWallet(w.cases)
                return (
                  <li key={`${w.chain}:${w.address}`}>
                    <span className="mono linked-wallet">{w.address}</span>
                    <span className="note">{[nameOf(w.chain), w.inferred_exchange && `probable ${plain(w.inferred_exchange)} deposit`,
                      w.risk_category && (RISK_WORD[w.risk_category] ?? w.risk_category)].filter(Boolean).join(' · ')}</span>
                    <p className="linked-by">
                      Traced from{' '}
                      {traces.map((m, i) => (
                        <span key={m.case_id}>{i > 0 && (i === traces.length - 1 && !w.other_complaints ? ' and ' : ', ')}<Link to={`/case/${m.case_id}`} className="mono" title={m.reported_address}>{middle(m.reported_address)}</Link></span>
                      ))}
                      {w.other_complaints > 0 && ` and ${plural(w.other_complaints, 'other complaint')}`}
                    </p>
                  </li>
                )
              })}
            </ul>
            {!all && linked.length > 5 && <button type="button" className="quiet link-like" onClick={() => setAll(true)}>Show all {linked.length}</button>}
          </>
        )}
      </div>
    </section>
  )
}

export default function Cases() {
  // undefined while asking; null when the cases cannot be reached.
  const [cases, setCases] = useState(undefined)
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const cards = useMedia(CARDS)
  useEffect(() => { fetchCases(LIMIT).then((d) => setCases(d.cases ?? [])).catch(() => setCases(null)) }, [])

  const filters = filtersFor(cases ?? [])
  const pressed = filters.find((f) => f.key === filter) ?? filters[0]
  const q = query.trim().toLowerCase()
  const shown = (cases ?? []).filter((c) => pressed.keeps(c) && matches(c, q))
  const narrowed = Boolean(cases?.length) && shown.length < cases.length
  const cut = cases?.length >= LIMIT
  const List = cards ? CaseCards : CaseTable

  return (
    <div className="work console work-cases">
      <header className="work-head cases-head">
        <div>
          <p className="note">Stored cases · yours and the recorded demos</p>
          <h1>Cases</h1>
        </div>
        {cases?.length > 0 && (
          <form role="search" aria-label="Search cases" className="cases-find" onSubmit={(e) => e.preventDefault()}>
            <svg aria-hidden="true" width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="7" cy="7" r="5" /><path d="M11 11l3.5 3.5" /></svg>
            <label htmlFor="cases-find" className="visually-hidden">Search cases</label>
            <input id="cases-find" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Wallet, exchange or case" spellCheck={false} autoComplete="off" />
          </form>
        )}
      </header>

      {cases === undefined && <p className="note" role="status">Loading cases…</p>}
      {cases === null && <p className="note">Stored cases cannot be reached right now.</p>}
      {cases?.length === 0 && <p className="note">No cases yet. Cases you trace show here, in this browser only.</p>}
      {cases?.length > 0 && (
        <>
          <div className="cases-filters">
            <div role="group" aria-label="Filter cases">
              {filters.map((f) => (
                <button key={f.key} type="button" aria-pressed={f === pressed} onClick={() => setFilter(f.key)}>
                  {`${f.label} · ${cases.filter(f.keeps).length}`}
                </button>
              ))}
            </div>
            <p role="status" className="note">{narrowed ? `${shown.length} of ${plural(cases.length, 'case')} shown` : ''}</p>
          </div>
          {shown.length > 0
            ? <div className="card glass cases-card"><List cases={shown} /></div>
            : <p className="note">{cut ? `No case among the newest ${LIMIT} matches.` : 'No case matches.'}</p>}
          <p className="note">{cut ? `The newest ${LIMIT} are listed, and the search covers only these. ` : ''}Only this browser sees your own cases. Opening one does not re-trace.</p>
        </>
      )}

      <LinkedComplaints />
    </div>
  )
}
