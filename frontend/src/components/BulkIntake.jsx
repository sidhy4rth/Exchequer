import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchBatches, startBatch } from '../api'
import { readComplaints } from '../csv'

// Home page: paste or open a CSV of complaints and trace them as one batch.
const SAMPLE = 'reference,address,chain,asset\nNCRP-2026-0001,0x…,ethereum,ETH\nNCRP-2026-0002,T…,tron,USDT'

export default function BulkIntake({ defaultOpen = false } = {}) {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState(null)
  const [rowErrors, setRowErrors] = useState([])
  const [busy, setBusy] = useState(false)
  const [past, setPast] = useState([])
  useEffect(() => { fetchBatches().then((d) => setPast(d.batches ?? [])).catch(() => {}) }, [])

  const read = text.trim() ? readComplaints(text) : null
  // A file with any bad line sends nothing: one shifted column can put the
  // victim's wallet where the suspect's address should be.
  const rows = read && read.errors.length === 0 ? read.rows : []

  async function onFile(file) {
    if (!file) return
    setText(await file.text())
    if (!name) setName(file.name.replace(/\.[^.]+$/, ''))
  }
  async function start() {
    setBusy(true); setError(null); setRowErrors([])
    try {
      const batch = await startBatch(name, rows.map(({ line, ...row }) => row))
      navigate(`/batch/${batch.batch_id}`)
    } catch (e) {
      // The server numbers the rows it was sent; name the file line instead.
      setError(e.message); setRowErrors((e.rowErrors ?? []).map((r) => ({ ...r, line: rows[r.row - 1]?.line ?? r.row })))
    } finally { setBusy(false) }
  }

  return (
    <details className="card sec bulk" open={defaultOpen || undefined}>
      <summary><span className="micro">Bulk intake</span><span className="note">trace up to 25 complaints from a CSV, then see what they share</span></summary>
      <div className="body">
        <p className="note">One row per reported address. Columns are matched by name: <span className="mono">suspect address</span> (or address, wallet), <span className="mono">chain</span>, <span className="mono">asset</span>, <span className="mono">direction</span>, <span className="mono">depth</span>, <span className="mono">reference</span> (complaint or acknowledgement number). A column naming the victim is never read as the address. Without a header, the first column is the address. Check the rows below before you run the batch.</p>
        <textarea className="mono bulk-text" rows={6} placeholder={SAMPLE} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-label="Complaints CSV" />
        {read && read.errors.length > 0 && (
          <div role="alert">
            <p className="error-line">Nothing will be sent until {read.errors.length === 1 ? 'this line is' : 'these lines are'} fixed in the file:</p>
            <ul className="row-errors">{read.errors.map((e) => <li key={e.line}>Line {e.line}: {e.error}</li>)}</ul>
          </div>
        )}
        {rows.length > 0 && <Preview rows={rows} columns={read.columns} />}
        <div className="verify-actions">
          <label className="button-like">Open a .csv<input type="file" accept=".csv,text/csv,text/plain" hidden onChange={(e) => onFile(e.target.files?.[0])} /></label>
          <input className="bulk-name" placeholder="Batch name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="primary" disabled={busy || rows.length === 0} onClick={start}>
            {busy ? 'Starting…' : rows.length ? `Run batch of ${rows.length}` : 'Run batch'}
          </button>
        </div>
        {error && <p className="error-line">{error}</p>}
        {rowErrors.length > 0 && (
          <ul className="row-errors">{rowErrors.map((e) => <li key={e.row}>Line {e.line}: {e.error}</li>)}</ul>
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

const FIELD_NAMES = { address: 'address', chain: 'chain', asset: 'asset', direction: 'direction', depth: 'depth', reference: 'reference' }

// Which column became which field, and every row as it will be sent.
function Preview({ rows, columns }) {
  const mapping = columns.mapped.map((m) => `${FIELD_NAMES[m.field]} ← ${m.header == null ? '' : `'${m.header}' `}(column ${m.column})`)
  return (
    <div className="bulk-preview">
      <p className="note" data-testid="bulk-mapping">
        {mapping.join(' · ')}
        {columns.unused.length > 0 && ` · not used: ${columns.unused.map((u) => `'${u.header}'`).join(', ')}`}
      </p>
      <table className="cases-table" tabIndex={0} aria-label="Rows to trace">
        <thead><tr><th>Line</th><th>Reference</th><th>Reported address</th><th>Chain</th><th>Asset</th><th>Direction</th><th>Depth</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.line}>
              <td className="num">{r.line}</td>
              <td>{r.reference || '—'}</td>
              <td className="mono bulk-address">{r.address}</td>
              <td>{r.chain || 'default'}</td>
              <td>{r.asset || 'native'}</td>
              <td>{r.direction || 'outgoing'}</td>
              <td>{r.depth || 'default'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
