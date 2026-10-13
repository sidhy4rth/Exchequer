import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { checkWatchNow, fetchAlerts, fetchWatches, logRequest, markAlertsRead, removeWatch } from '../api'

// The home page's watchlist: what this browser watches and what moved.
// Refreshes every minute while open; the server checks on its own schedule.

const KIND = {
  exchange: { pill: 'green', text: 'into an exchange' },
  risk: { pill: 'red', text: 'into a flagged address' },
  moved: { pill: 'amber', text: 'moved' },
}
const amount = (v) => Number(v).toLocaleString('en-US', { maximumFractionDigits: 6 })
const short = (a) => (a && a.length > 20 ? `${a.slice(0, 10)}…${a.slice(-8)}` : a)
const ago = (iso) => {
  if (!iso) return 'not yet'
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000)
  if (s < 90) return 'just now'
  if (s < 5400) return `${Math.round(s / 60)} min ago`
  if (s < 129600) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

export default function Watchlist() {
  const [watches, setWatches] = useState([])
  const [alerts, setAlerts] = useState([])
  const [running, setRunning] = useState(true)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [logged, setLogged] = useState({})

  const load = useCallback(() => {
    fetchWatches().then((d) => { setWatches(d.watches ?? []); setRunning(d.running !== false) }).catch(() => {})
    fetchAlerts().then((d) => setAlerts(d.alerts ?? [])).catch(() => {})
  }, [])
  useEffect(() => {
    load()
    const t = setInterval(load, 60_000)
    return () => clearInterval(t)
  }, [load])

  if (watches.length === 0 && alerts.length === 0) return null
  const unread = alerts.filter((a) => !a.read).length

  async function act(id, fn) {
    setBusy(id); setError(null)
    try { await fn() } catch (e) { setError(e.message) } finally { setBusy(null); load() }
  }

  return (
    <section>
      <div className="card watchlist">
        <div className="head">
          <span className="micro">Watchlist · {watches.length}{unread ? <span className="pill red" style={{ marginLeft: 8 }}>{unread} new</span> : null}</span>
          <span className="note">{running ? 'checked about every ten minutes · this browser only' : 'the server is not checking watches right now'}</span>
        </div>
        <div className="body">
          {watches.map((w) => (
            <div className="watch-row" key={w.watch_id}>
              <div>
                <span className="mono">{short(w.address)}</span>
                <small>{w.chain} · {w.asset}{w.note ? ` · ${w.note}` : ''} · checked {ago(w.last_checked_at)}{w.webhook ? ` · posts to ${w.webhook.replace('https://', '').replace('/…', '')}` : ''}{w.last_error ? ` · ${w.last_error}` : ''}</small>
              </div>
              <span className="watch-actions">
                {w.case_id && <Link to={`/case/${w.case_id}`} className="quiet-link">case</Link>}
                <button className="quiet" disabled={busy !== null} onClick={() => act(w.watch_id, () => checkWatchNow(w.watch_id))}>{busy === w.watch_id ? 'Checking…' : 'Check now'}</button>
                <button className="quiet" disabled={busy !== null} onClick={() => act(w.watch_id, () => removeWatch(w.watch_id))}>Stop</button>
              </span>
            </div>
          ))}
          {error && <p className="error-line">{error}</p>}
          {alerts.length > 0 && (
            <div className="alerts">
              <div className="alerts-head">
                <span className="micro">Alerts</span>
                {unread > 0 && <button className="quiet" onClick={() => act('read', () => markAlertsRead())}>Mark all read</button>}
              </div>
              {alerts.slice(0, 30).map((a) => (
                <div className={`alert-row${a.read ? '' : ' unread'}`} key={a.alert_id}>
                  <span className={`pill ${KIND[a.kind]?.pill ?? ''}`}>{KIND[a.kind]?.text ?? a.kind}</span>
                  <span className="msg">
                    {amount(a.value)} {a.asset} to <span className="mono">{a.counterparty_label || short(a.counterparty)}</span>
                    <small> · {new Date(a.tx_time * 1000).toISOString().slice(0, 16).replace('T', ' ')} UTC · {a.tx_url ? <a href={a.tx_url} target="_blank" rel="noopener noreferrer">transaction</a> : short(a.tx_hash)}</small>
                  </span>
                  {a.kind === 'exchange' && a.exchange && a.case_id && (
                    logged[a.alert_id]
                      ? <Link to={`/case/${a.case_id}`} className="quiet-link">request logged</Link>
                      : <button className="quiet" disabled={busy !== null} title={`Log a freeze request to ${a.exchange} against the case, with this deposit address`}
                          onClick={() => act(a.alert_id, async () => {
                            await logRequest({ case_id: a.case_id, recipient: a.exchange, kind: 'exchange', address: a.counterparty, asset: a.asset })
                            setLogged((m) => ({ ...m, [a.alert_id]: true }))
                          })}>Log freeze request</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
