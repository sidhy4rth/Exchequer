import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchDueAssets } from '../api'
import { deadline, HOLDERS, money } from './case/AssetsPanel'
import './AssetDeadlines.css'

/** The home page's warning: frozen or seized funds whose court order on custody
 * is due within a week or overdue (backend GET /assets/due). Shows nothing when
 * none is, or when the register cannot be reached. */
export default function AssetDeadlines() {
  const [due, setDue] = useState([])
  useEffect(() => { fetchDueAssets(7).then((d) => setDue(d.assets ?? [])).catch(() => setDue([])) }, [])
  if (!due.length) return null
  return (
    <section className="card glass console-card asset-deadlines" aria-labelledby="console-deadlines">
      <div className="console-card-head"><h2 id="console-deadlines">Court deadlines</h2><span className="console-figure">{due.length}</span></div>
      <ul className="recent-cases">
        {due.map((a) => (
          <li key={a.asset_id}>
            <Link to={`/case/${a.case_id}?tab=letters`}>
              <span className="ad-amount mono">{money(a.amount, a.asset)}</span>
              <span className="ad-where">{HOLDERS[a.holder] ?? a.holder}</span>
              <span className="pill red ad-when">{deadline(a).text}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
