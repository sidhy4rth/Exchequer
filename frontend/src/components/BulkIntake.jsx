import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchBatches, startBatch } from '../api'
import { complaintsFromCsv } from '../csv'

// Home page: paste or open a CSV of complaints and trace them as one batch.
const SAMPLE = 'reference,address,chain,asset\nNCRP-2026-0001,0x…,ethereum,ETH\nNCRP-2026-0002,T…,tron,USDT'

export default function BulkIntake() {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState(null)
  const [rowErrors, setRowErrors] = useState([])
  const [busy, setBusy] = useState(false)
  const [past, setPast] = useState([])
  useEffect(() => { fetchBatches().then((d) => setPast(d.batches ?? [])).catch(() => {}) }, [])

  const rows = text.trim() ? complaintsFromCsv(text) : []

  async function onFile(file) {
    if (!file) return
    setText(await file.text())
    if (!name) setName(file.name.replace(/\.[^.]+$/, ''))
  }
  async function start() {
    setBusy(true); setError(null); setRowErrors([])
    try {
      const batch = await startBatch(name, rows)
      navigate(`/batch/${batch.batch_id}`)
    } catch (e) {
      setError(e.message); setRowErrors(e.rowErrors ?? [])
    } finally { setBusy(false) }
  }

  return (
    <details className="card sec bulk">
      <summary><span className="micro">Bulk intake</span><span className="note">trace up to 25 complaints from a CSV, then see what they share</span></summary>
      <div className="body">
        <p className="note">One row per reported address. Columns are matched by name: <span className="mono">address</span> (or wallet), <span className="mono">chain</span>, <span className="mono">asset</span>, <span className="mono">direction</span>, <span className="mono">depth</span>, <span className="mono">reference</span> (complaint or acknowledgement number). Without a header, the first column is the address.</p>
        <textarea className="mono bulk-text" rows={6} placeholder={SAMPLE} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-label="Complaints CSV" />
        <div className="verify-actions">
          <label className="button-like">Open a .csv<input type="file" accept=".csv,text/csv,text/plain" hidden onChange={(e) => onFile(e.target.files?.[0])} /></label>
          <input className="bulk-name" placeholder="Batch name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="primary" disabled={busy || rows.length === 0} onClick={start}>
            {busy ? 'Starting…' : rows.length ? `Run batch of ${rows.length}` : 'Run batch'}
          </button>
        </div>
        {error && <p className="error-line">{error}</p>}
        {rowErrors.length > 0 && (
          <ul className="row-errors">{rowErrors.map((e) => <li key={e.row}>Row {e.row}: {e.error}</li>)}</ul>
        )}
        {past.length > 0 && (
          <div className="past-batches">
            <span className="micro">Earlier batches</span>
            {past.slice(0, 5).map((b) => (
              <Link key={b.batch_id} to={`/batch/${b.batch_id}`}>{b.name || 'Untitled batch'} · {b.done}/{b.total} traced · {String(b.created_at).slice(0, 10)}</Link>
            ))}
          </div>
        )}
      </div>
    </details>
  )
}
