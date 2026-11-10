import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { fetchAccess, fetchChains } from '../api'
import BulkIntake from '../components/BulkIntake'
import OpenRequests from '../components/OpenRequests'
import Showroom from '../components/Showroom'
import TraceForm from '../components/TraceForm'
import Watchlist from '../components/Watchlist'
import { hasDemoAccess } from '../demoCode'

// The console's own pages, one per sidebar item: the trace form, the
// watchlist, open requests and bulk intake (the stored cases are Cases.jsx).
// Each was a tab on the console's home page and reuses that tab's component
// as it was, under a title and one line on what the page is for.

const PAGES = {
  new: { title: 'New trace', lede: 'Follow a reported wallet to the exchange that can freeze the money' },
  watchlist: { title: 'Watchlist', lede: 'Wallets this browser watches, and what moved' },
  requests: { title: 'Requests', lede: 'Letters logged from a case and still waiting on someone' },
  batch: { title: 'Bulk intake', lede: 'Trace up to 25 complaints from a CSV, then see what they share' },
}

/** Whether this site wants the demo code and this tab has not given it
 * (backend/app/access.py). Until /access answers, or if it cannot, the page
 * is open: the backend refuses a trace without the code either way. */
function useLocked() {
  const [required, setRequired] = useState(false)
  const [unlocked, setUnlocked] = useState(() => hasDemoAccess())
  useEffect(() => { fetchAccess().then((a) => setRequired(Boolean(a?.demo_code_required))).catch(() => {}) }, [])
  return [required && !unlocked, () => setUnlocked(true)]
}

function NewTrace({ locked, onUnlock }) {
  const [params] = useSearchParams()
  const [health, setHealth] = useState(null)
  useEffect(() => { fetchChains().then(setHealth).catch(() => setHealth({ status: 'down' })) }, [])
  const pay = params.get('pay') ?? ''
  if (locked) return <Showroom onUnlock={onUnlock} />
  return <TraceForm key={pay} health={health} payments={pay} startChain={params.get('chain')} startAsset={params.get('asset')} onUnlock={onUnlock} />
}

/** What an empty page says, on a quiet card where its list would be. */
const Empty = ({ children }) => <div className="card glass quiet-card work-empty"><p className="note">{children}</p></div>

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
      {page === 'watchlist' && (locked ? <Shut what="Watching a wallet" /> : (
        <>
          <Watchlist onCount={setCount} />
          {count === 0 && <Empty>Nothing watched yet. Open a case and choose Watch to be told when the money moves.</Empty>}
        </>
      ))}
      {page === 'requests' && (
        <>
          <OpenRequests onCount={setCount} />
          {count === 0 && <Empty>No open requests. Letters you log from a case are tracked here.</Empty>}
        </>
      )}
      {page === 'batch' && (locked ? <Shut what="Bulk intake" /> : <BulkIntake defaultOpen />)}
    </div>
  )
}
