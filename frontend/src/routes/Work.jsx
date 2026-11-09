import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { fetchAccess, fetchCases, fetchChains } from '../api'
import BulkIntake from '../components/BulkIntake'
import ChainDot from '../components/ChainDot'
import OpenRequests from '../components/OpenRequests'
import Showroom from '../components/Showroom'
import TraceForm from '../components/TraceForm'
import Watchlist from '../components/Watchlist'
import { bandLabel, bandOf } from '../components/confidence'
import { hasDemoAccess } from '../demoCode'

// The console's own pages, one per sidebar item: the trace form, the stored
// cases, the watchlist, open requests and bulk intake. Each was a tab on the
// console's home page and reuses that tab's component as it was.

const PAGES = {
  new: { title: 'New trace', lede: 'Follow a reported wallet to the exchange that can freeze the money' },
  cases: { title: 'Cases', lede: 'Your traced cases, in this browser only, and the recorded examples' },
  watchlist: { title: 'Watchlist', lede: 'Wallets this browser watches, and what moved' },
  requests: { title: 'Requests', lede: 'Letters logged from a case and still waiting on someone' },
  batch: { title: 'Bulk intake', lede: 'Trace up to 25 complaints from a CSV, then see what they share' },
}
const middle = (a, head = 12, tail = 10) => (a && a.length > head + tail + 1 ? `${a.slice(0, head)}…${a.slice(-tail)}` : a)

/** Whether this site wants the demo code and this tab has not given it
 * (backend/app/access.py). Until /access answers, or if it cannot, the page
 * is open: the backend refuses a trace without the code either way. */
function useLocked() {
  const [required, setRequired] = useState(false)
  const [unlocked, setUnlocked] = useState(() => hasDemoAccess())
  useEffect(() => { fetchAccess().then((a) => setRequired(Boolean(a?.demo_code_required))).catch(() => {}) }, [])
  return [required && !unlocked, () => setUnlocked(true)]
}

function CaseList() {
  const navigate = useNavigate()
  const [cases, setCases] = useState(null)
  useEffect(() => { fetchCases(50).then((d) => setCases(d.cases ?? [])).catch(() => setCases([])) }, [])
  if (cases === null) return null
  if (cases.length === 0) return <p className="note">No cases yet. Cases you trace show here, in this browser only.</p>
  return (
    <div className="card glass work-cases">
      <table className="cases-table" tabIndex={0} aria-label="Stored cases">
        <thead><tr><th>Reported address</th><th>Chain</th><th>Asset</th><th>Result</th><th style={{ textAlign: 'right' }}>Confidence</th><th style={{ textAlign: 'right' }}>Addresses</th><th>Flags</th><th>Traced</th></tr></thead>
        <tbody>
          {cases.map((c) => (
            <tr className="row" key={c.case_id} onClick={(e) => { if (!e.target.closest('a')) navigate(`/case/${c.case_id}`) }}>
              <td className="mono">
                <Link to={`/case/${c.case_id}`} title={`Open the stored case for ${c.address}`}>{middle(c.address)}</Link>
                {c.direction === 'incoming' && <span className="pill navy" style={{ marginLeft: 8 }}>reverse</span>}{c.demo && <span className="pill" style={{ marginLeft: 8 }}>example</span>}
              </td>
              <td><ChainDot chain={c.chain} />{c.chain}</td>
              <td className="mono">{c.asset ?? '—'}</td>
              <td className={c.exchange ? '' : 'none'}>{c.exchange ?? 'no match'}</td>
              <td>{c.confidence == null ? 'n/a' : bandLabel(bandOf(c.confidence))}</td>
              <td className="num">{c.node_count}</td>
              <td>{(c.flags ?? []).map((f) => <span className="pill amber" key={f} style={{ marginRight: 4 }}>{f.replace('_', ' ')}</span>)}</td>
              <td className="mono">{String(c.created_at).slice(0, 10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note foot-note">Only this browser sees your cases. Opening one does not re-trace.</p>
    </div>
  )
}

function NewTrace({ locked, onUnlock }) {
  const [params] = useSearchParams()
  const [health, setHealth] = useState(null)
  useEffect(() => { fetchChains().then(setHealth).catch(() => setHealth({ status: 'down' })) }, [])
  const pay = params.get('pay') ?? ''
  if (locked) return <Showroom onUnlock={onUnlock} />
  return <TraceForm key={pay} health={health} payments={pay} startChain={params.get('chain')} startAsset={params.get('asset')} />
}

/** A page that would spend the provider quota or keep running (a watch, a
 * batch), on a public site whose demo code this tab has not given. */
const Shut = ({ what }) => (
  <p className="note banner">{what} needs the demo code on this site. <Link to="/trace/new">Enter the code</Link> to use it.</p>
)

export default function Work({ page }) {
  const [locked, unlock] = useLocked()
  const [count, setCount] = useState(null)
  const { title, lede } = PAGES[page]
  return (
    <div className={`work console work-${page}`}>
      <header className="work-head">
        <p className="note">{lede}</p>
        <h1>{title}</h1>
      </header>
      {page === 'new' && <NewTrace locked={locked} onUnlock={unlock} />}
      {page === 'cases' && <CaseList />}
      {page === 'watchlist' && (locked ? <Shut what="Watching a wallet" /> : (
        <>
          <Watchlist onCount={setCount} />
          {count === 0 && <p className="note">Nothing watched yet. Open a case and choose Watch to be told when the money moves.</p>}
        </>
      ))}
      {page === 'requests' && (
        <>
          <OpenRequests onCount={setCount} />
          {count === 0 && <p className="note">No open requests. Letters you log from a case are tracked here.</p>}
        </>
      )}
      {page === 'batch' && (locked ? <Shut what="Bulk intake" /> : <BulkIntake defaultOpen />)}
    </div>
  )
}
