import { useEffect, useState } from 'react'
import { deleteRequest, fetchCaseRequests, fetchLetters, logRequest, updateRequest } from '../api'

// Where this case's freeze requests stand. The letter is drafted from the
// Export menu; this is the log of what was sent and what came back.

export const STATUS = {
  drafted: { label: 'Drafted', pill: '' },
  sent: { label: 'Sent · awaiting reply', pill: 'navy' },
  acknowledged: { label: 'Acknowledged', pill: 'amber' },
  frozen: { label: 'Frozen', pill: 'green' },
  declined: { label: 'Declined', pill: 'red' },
  closed: { label: 'Closed', pill: '' },
}

export default function RequestsPanel({ result }) {
  const [items, setItems] = useState([])
  const [letters, setLetters] = useState([])
  const [other, setOther] = useState('')
  const [error, setError] = useState(null)
  const caseId = result?.case_id

  const load = () => caseId && fetchCaseRequests(caseId).then((d) => setItems(d.requests ?? [])).catch(() => {})
  useEffect(() => {
    load()
    if (caseId) fetchLetters(caseId).then((d) => setLetters(d.letters ?? [])).catch(() => {})
  }, [caseId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!caseId) return null

  async function run(fn) {
    setError(null)
    try { await fn(); await load() } catch (e) { setError(e.message) }
  }
  const log = (recipient, kind) => run(() => logRequest({
    case_id: caseId, recipient, kind,
    address: kind === 'exchange' ? (result.exchange_address ?? '') : '',
    asset: result.asset ?? '',
  }))
  const suggestions = letters.map((l) => ({
    recipient: l.to === 'tether' ? 'Tether' : (result.exchange ?? 'the exchange'),
    kind: l.to,
  })).filter((s) => !items.some((i) => i.recipient === s.recipient && i.status !== 'closed'))

  return (
    <details className="card sec" open={items.length > 0 || suggestions.length > 0}>
      <summary><span className="micro">Freeze requests · {items.length}</span><span className="note">what was sent, what came back</span></summary>
      <div className="body requests-panel">
        {items.map((r) => (
          <div className="request-row" key={r.request_id}>
            <div className="top">
              <span className="nm">{r.recipient}</span>
              <span className={`pill ${STATUS[r.status]?.pill ?? ''}`}>{STATUS[r.status]?.label ?? r.status}</span>
            </div>
            {r.follow_up && <div className="follow-up">No reply for {r.days_waiting} days: follow up.</div>}
            <div className="fields">
              <label>Status
                <select value={r.status} onChange={(e) => run(() => updateRequest(r.request_id, { status: e.target.value }))}>
                  {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </select>
              </label>
              <label>Their reference
                <input defaultValue={r.reference} placeholder="ticket / case no." onBlur={(e) => e.target.value !== r.reference && run(() => updateRequest(r.request_id, { reference: e.target.value }))} />
              </label>
              {r.status === 'frozen' && (
                <label>Amount frozen ({r.asset || 'units'})
                  <input type="number" min="0" step="any" defaultValue={r.amount_frozen ?? ''} onBlur={(e) => run(() => updateRequest(r.request_id, { amount_frozen: e.target.value === '' ? null : Number(e.target.value) }))} />
                </label>
              )}
              <label className="wide">Notes
                <textarea rows={2} defaultValue={r.notes} onBlur={(e) => e.target.value !== r.notes && run(() => updateRequest(r.request_id, { notes: e.target.value }))} />
              </label>
            </div>
            <div className="history">
              {r.history.map((h, i) => <span key={i}>{String(h.at).slice(0, 10)} {STATUS[h.status]?.label.split(' ·')[0] ?? h.status}{h.note ? ` (${h.note})` : ''}</span>)}
              <button className="quiet" onClick={() => run(() => deleteRequest(r.request_id))}>Remove</button>
            </div>
          </div>
        ))}
        <div className="request-add">
          {suggestions.map((s) => <button key={s.recipient} onClick={() => log(s.recipient, s.kind)}>Log a request to {s.recipient}</button>)}
          <span className="other">
            <input placeholder="Another recipient" value={other} onChange={(e) => setOther(e.target.value)} />
            <button disabled={!other.trim()} onClick={() => { log(other.trim(), 'other'); setOther('') }}>Log</button>
          </span>
        </div>
        {error && <p className="error-line">{error}</p>}
        <p className="note">Draft the letter from Export, send it, then log it here. Kept in this browser&apos;s records, like its cases.</p>
      </div>
    </details>
  )
}
