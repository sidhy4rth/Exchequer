import { useEffect, useState } from 'react'
import { addWatch, fetchWatches, removeWatch } from '../api'

// "Tell me when it moves", on the case itself. Offers the reported wallet and,
// when the trace inferred one, the probable deposit address -- never a
// labelled hot wallet, which moves all day and would only make noise.

const short = (a) => (a && a.length > 20 ? `${a.slice(0, 10)}…${a.slice(-8)}` : a)

export default function WatchPanel({ result }) {
  const [watches, setWatches] = useState([])
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [hook, setHook] = useState('')
  const [showHook, setShowHook] = useState(false)

  const load = () => fetchWatches().then((d) => setWatches(d.watches ?? [])).catch(() => {})
  useEffect(() => { load() }, [result?.case_id])

  if (!result?.address) return null
  const candidates = [{ address: result.address, what: result.direction === 'incoming' ? 'the reported address' : 'the reported wallet' }]
  if (result.attribution_inferred && result.exchange_address && result.exchange_address !== result.address) {
    candidates.push({ address: result.exchange_address, what: `the probable ${result.exchange} deposit address` })
  }
  const watching = (address) => watches.find((w) => w.address.toLowerCase() === address.toLowerCase() && w.chain === result.chain && w.asset === result.asset)

  async function watch(c) {
    setBusy(c.address); setError(null)
    try {
      await addWatch({ address: c.address, chain: result.chain, asset: result.asset, note: c.what, caseId: result.case_id, webhookUrl: hook.trim() || null })
      setHook(''); setShowHook(false)
      await load()
    } catch (e) { setError(e.message) } finally { setBusy(null) }
  }
  async function unwatch(w) {
    setBusy(w.address); setError(null)
    try { await removeWatch(w.watch_id); await load() } catch (e) { setError(e.message) } finally { setBusy(null) }
  }

  return (
    <details className="card sec" open>
      <summary><span className="micro">Watch for movement</span><span className="note">alerts when funds leave</span></summary>
      <div className="body watch-panel">
        {candidates.map((c) => {
          const w = watching(c.address)
          return (
            <div className="watch-row" key={c.address}>
              <div>
                <span className="mono">{short(c.address)}</span>
                <small>{c.what}{w ? ` · watching${w.last_checked_at ? `, checked ${String(w.last_checked_at).slice(11, 16)} UTC` : ''}${w.unread_alerts ? ` · ${w.unread_alerts} new alert${w.unread_alerts === 1 ? '' : 's'}` : ''}` : ''}</small>
              </div>
              {w
                ? <button className="quiet" disabled={busy !== null} onClick={() => unwatch(w)}>Stop</button>
                : <button disabled={busy !== null} onClick={() => watch(c)}>{busy === c.address ? 'Adding…' : 'Watch'}</button>}
            </div>
          )
        })}
        {showHook
          ? <label className="watch-hook">Also post alerts to a Slack, Discord or Google Chat webhook (optional)
              <input type="url" className="mono" placeholder="https://hooks.slack.com/services/…" value={hook} onChange={(e) => setHook(e.target.value)} />
            </label>
          : <button className="quiet link-like" onClick={() => setShowHook(true)}>+ post alerts to Slack, Discord or Google Chat</button>}
        {error && <p className="error-line">{error}</p>}
        <p className="note">Checked about every ten minutes. Alerts appear on the home page, in this browser only. An alert into an exchange wallet is the moment to send the freeze request.</p>
      </div>
    </details>
  )
}
