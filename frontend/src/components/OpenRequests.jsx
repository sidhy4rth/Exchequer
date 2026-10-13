import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchOpenRequests } from '../api'
import { STATUS } from './RequestsPanel'

// Home page: requests still waiting on someone, oldest silence first.
export default function OpenRequests() {
  const [items, setItems] = useState([])
  useEffect(() => { fetchOpenRequests().then((d) => setItems(d.requests ?? [])).catch(() => {}) }, [])
  if (items.length === 0) return null
  const sorted = [...items].sort((a, b) => (b.days_waiting ?? -1) - (a.days_waiting ?? -1))
  const overdue = items.filter((r) => r.follow_up).length
  return (
    <section>
      <div className="card">
        <div className="head">
          <span className="micro">Open requests · {items.length}{overdue ? <span className="pill red" style={{ marginLeft: 8 }}>{overdue} to follow up</span> : null}</span>
          <span className="note">drafted, sent or acknowledged · this browser only</span>
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
