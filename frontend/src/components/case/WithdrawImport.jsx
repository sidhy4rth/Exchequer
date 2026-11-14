import { useState } from 'react'
import { plain } from '../../text'
import './WithdrawImport.css'

// Withdrawing a saved statement or CDR import entered by mistake (backend
// statement_imports.withdraw). Nothing is deleted: the import stays in the case
// record with who withdrew it, when and why, and is listed only when asked for.

export const REASON_MAX = 300

/** Who withdrew it, when and why; nothing while it stands. */
export function Withdrawn({ item }) {
  const w = item.withdrawn
  if (!w) return null
  return <p className="note wd-note">Withdrawn {String(w.at).slice(0, 10)} by {plain(w.by)}: {plain(w.reason)}</p>
}

/** "Show withdrawn (n)": shown once there is one, or while they are shown. */
export function ShowWithdrawn({ count, shown, onChange }) {
  if (!count && !shown) return null
  return (
    <label className="wd-toggle"><input type="checkbox" checked={shown} onChange={(e) => onChange(e.target.checked)} />
      Show withdrawn ({count ?? 0})</label>
  )
}

/** The withdraw button, then a reason (required) and a confirm. `onWithdraw(reason)` rejects with the server's message. */
export default function WithdrawImport({ name, onWithdraw }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  if (!open) return <button type="button" className="wd-open" onClick={() => setOpen(true)}>Withdraw {name}…</button>
  async function submit(e) {
    e.preventDefault()
    if (!reason.trim()) { setError('Say why it is withdrawn: the reason stays with the record.'); return }
    setBusy(true); setError(null)
    try { await onWithdraw(reason.trim()) } catch (err) { setError(err.message); setBusy(false) }
  }
  return (
    <form className="wd-form" onSubmit={submit}>
      <label>Why is it withdrawn? (kept with the record)
        <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={REASON_MAX} required placeholder="e.g. saved against the wrong case" />
      </label>
      <button type="submit" disabled={busy}>{busy ? 'Withdrawing…' : 'Withdraw'}</button>
      <button type="button" onClick={() => { setOpen(false); setReason(''); setError(null) }} disabled={busy}>Cancel</button>
      {error && <p className="note wd-error" role="alert">{error}</p>}
    </form>
  )
}
