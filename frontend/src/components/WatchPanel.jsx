import { useEffect, useState } from 'react'
import { addWatch, fetchWatches, removeWatch } from '../api'
import { plain } from '../text'
import CaseRefField, { refOk, tidyRef, useSignedIn } from './CaseRefField'

// "Tell me when it moves", on the case itself. Offers the reported wallet and,
// when the trace inferred one, the probable deposit address -- never a
// labelled hot wallet, which moves all day and would only make noise.

const short = (a) => { const p = plain(a); return p && p.length > 20 ? `${p.slice(0, 10)}…${p.slice(-8)}` : p }

export default function WatchPanel({ result, extra = null }) {
  const [watches, setWatches] = useState([])
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [hook, setHook] = useState('')
  const [showHook, setShowHook] = useState(false)
  // A signed-in officer watches under the case's reference, or one they give (case_refs.py).
  const asks = useSignedIn() === true && !result?.intake?.case_ref
  const [caseRef, setCaseRef] = useState('')
  const blocked = asks && !refOk(caseRef)

  // undefined while loading, null if the watch service could not be reached:
  // the panel must not promise a schedule it has not seen.
  const [watcher, setWatcher] = useState(undefined)
  const load = () => fetchWatches()
    .then((d) => { setWatches(d.watches ?? []); setWatcher(d.watcher ?? { enabled: d.running !== false }) })
    .catch(() => setWatcher(null))
  useEffect(() => { load() }, [result?.case_id])

  if (!result?.address) return null
  const candidates = [{ address: result.address, what: result.direction === 'incoming' ? 'the reported address' : 'the reported wallet' }]
  if (result.attribution_inferred && result.exchange_address && result.exchange_address !== result.address) {
    candidates.push({ address: result.exchange_address, what: `the probable ${result.exchange} deposit address` })
  }
  // A wallet a Flow card asked to watch: where the case's flow leaves some of
  // the money (TraceView offers it only then).
  if (extra && !candidates.some((c) => c.address === extra)) candidates.push({ address: extra, what: "a wallet where some of the victim's money is left" })
  const watching = (address) => watches.find((w) => w.address.toLowerCase() === address.toLowerCase() && w.chain === result.chain && w.asset === result.asset)

  async function watch(c) {
    setBusy(c.address); setError(null)
    try {
      await addWatch({ address: c.address, chain: result.chain, asset: result.asset, note: c.what, caseId: result.case_id, webhookUrl: hook.trim() || null, caseRef: asks ? tidyRef(caseRef) : null })
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
        {watcher === null && <p className="note">Could not reach the watch service; press Check now on the home page before relying on a watch.</p>}
        {watcher?.enabled === false && <p className="note">Automatic checks are off on this site: a watch is checked only when someone presses Check now in the watchlist.</p>}
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
                : <button disabled={busy !== null || blocked} onClick={() => watch(c)}>{busy === c.address ? 'Adding…' : 'Watch'}</button>}
            </div>
          )
        })}
        {asks && <CaseRefField id="watch-case-ref" value={caseRef} onChange={setCaseRef} />}
        {showHook
          ? <label className="watch-hook">Also post alerts to a Slack, Discord or Google Chat webhook (optional)
              <input type="url" className="mono" placeholder="https://hooks.slack.com/services/…" value={hook} onChange={(e) => setHook(e.target.value)} />
            </label>
          : <button className="quiet link-like" onClick={() => setShowHook(true)}>+ post alerts to Slack, Discord or Google Chat</button>}
        {error && <p className="error-line">{error}</p>}
        <p className="note">
          {watcher?.enabled === true ? `Checked automatically about every ${Math.round((watcher.interval_seconds ?? 600) / 60)} min. ` : ''}
          Alerts appear on the home page, in this browser only. An alert into an exchange wallet is the moment to send the freeze request.
        </p>
      </div>
    </details>
  )
}
