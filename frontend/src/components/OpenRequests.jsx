import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchOpenRequests } from '../api'
import { STATUS } from './RequestsPanel'

// Requests still waiting on someone, oldest silence first. `onCount` hears
// how many: undefined until /requests answers, null if it could not.
export default function OpenRequests({ onCount } = {}) {
  const [items, setItems] = useState(undefined)
  useEffect(() => { fetchOpenRequests().then((d) => setItems(d.requests ?? [])).catch(() => setItems(null)) }, [])
  const known = items == null ? items : items.length
  useEffect(() => { onCount?.(known) }, [onCount, known])
  if (!items?.length) return null
  const sorted = [...items].sort((a, b) => (b.days_waiting ?? -1) - (a.days_waiting ?? -1))
  const overdue = items.filter((r) => r.follow_up).length
  return (
    <section>
      <div className="card">
        <div className="head">
          <span className="micro">Open requests · {items.length}{overdue ? <span className="pill red" style={{ marginLeft: 8 }}>{overdue} to follow up</span> : null}</span>
          <span className="note">waiting on a sign-off or a reply · this browser only</span>
        </div>
        <div className="body">
          {sorted.map((r) => (
            <div className="watch-row" key={r.request_id}>
              <div>
                <span>{r.recipient}{r.reference ? <span className="mono"> · {r.reference}</span> : null}</span>
                <small>{STATUS[r.status]?.label ?? r.status}{r.days_waiting != null ? ` · ${r.days_waiting} day${r.days_waiting === 1 ? '' : 's'} since sent` : ''}{r.follow_up ? ' · follow up' : ''}</small>
              </div>
              <Link to={`/case/${r.case_id}`} className="quiet-link">case</Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
