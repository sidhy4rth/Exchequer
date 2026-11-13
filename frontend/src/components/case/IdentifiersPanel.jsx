import { useEffect, useState } from 'react'
import { addIdentifier, fetchCaseIdentifiers, updateIdentifier } from '../../api'
import { plain } from '../../text'
import './IdentifiersPanel.css'

// What the victim reported besides the wallet (backend identifiers.py, suite
// feature 4): the scam site, the Telegram username, the phone number, the UPI ID
// they paid. Entered by hand for the case. Each is a lead, never an identity:
// only the registrar, the telecom or the bank can say whose it is.

export const KINDS = {
  domain: 'Website domain',
  telegram: 'Telegram username',
  phone: 'Phone number',
  upi: 'UPI ID',
}
const HINTS = {
  domain: 'e.g. scam-shop.in or the full link',
  telegram: 'e.g. @crypto_help or t.me/crypto_help',
  phone: 'e.g. +91 98xxx xxxxx',
  upi: 'e.g. shop.pay@okaxis',
}

/** One history entry in words. An unknown kind of entry shows its own name. */
export function historyText(h) {
  if (h.action === 'changed') return `${(h.changed ?? []).join(', ')} changed${h.note ? ` (${h.note})` : ''}`
  if (h.action === 'noted') return `note: ${h.note}`
  return String(h.action)
}

/** How a kept value reads: a username with its @, the rest as kept. */
export function shown(row) {
  return row.kind === 'telegram' ? `@${row.value}` : row.value
}

const EMPTY = { kind: 'domain', value: '', context: '', notes: '' }

export default function IdentifiersPanel({ result }) {
  const caseId = result?.case_id
  const [rows, setRows] = useState([])
  const [form, setForm] = useState(null)
  const [error, setError] = useState(null)
  const [act, setAct] = useState({}) // identifier_id → { mode: 'withdraw' | 'note', note }

  // A failed load says so: an empty list would read as "the victim reported nothing else".
  const load = () => caseId && fetchCaseIdentifiers(caseId).then((d) => setRows(d.identifiers ?? []))
    .catch(() => setError('The reported identifiers could not be loaded. Reload the page before relying on this list.'))
  useEffect(() => { load() }, [caseId]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!caseId) return null

  async function run(fn) {
    setError(null)
    try { await fn(); await load(); return true } catch (e) { setError(e.message); return false }
  }
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
  async function save(e) {
    e.preventDefault()
    if (await run(() => addIdentifier(caseId, form))) setForm(null)
  }
  const pick = (id) => act[id] ?? {}
  const setAct1 = (id, values) => setAct((a) => ({ ...a, [id]: { ...a[id], ...values } }))
  async function apply(row) {
    const a = pick(row.identifier_id)
    const changes = a.mode === 'withdraw' ? { status: 'withdrawn', note: a.note ?? '' } : { note: a.note ?? '' }
    if (await run(() => updateIdentifier(row.identifier_id, changes))) setAct((all) => ({ ...all, [row.identifier_id]: {} }))
  }
  const active = rows.filter((r) => r.status === 'active').length

  return (
    <details className="card sec identifiers-panel" open={rows.length > 0 || Boolean(error)}>
      <summary><span className="micro">Reported identifiers · {active}</span><span className="note">sites, usernames, phones, UPI IDs</span></summary>
      <div className="body requests-panel">
        {rows.map((row) => {
          const a = pick(row.identifier_id)
          return (
            <div className={`request-row ${row.status === 'withdrawn' ? 'id-withdrawn' : ''}`} key={row.identifier_id}>
              <div className="top">
                <span className="nm"><span className="mono">{plain(shown(row))}</span> <span className="note">· {KINDS[row.kind] ?? row.kind}</span></span>
                {row.status === 'withdrawn' && <span className="pill amber">Withdrawn</span>}
              </div>
              {(row.context || row.entered !== row.value) && (
                <dl className="id-facts">
                  {row.context && <><dt>Seen</dt><dd>{plain(row.context)}</dd></>}
                  {row.entered !== row.value && <><dt>As typed</dt><dd className="mono">{plain(row.entered)}</dd></>}
                </dl>
              )}
              {row.notes && <p className="note">{plain(row.notes)}</p>}
              <div className="request-add">
                {row.status === 'active' && (
                  <button type="button" onClick={() => setAct1(row.identifier_id, { mode: a.mode === 'withdraw' ? null : 'withdraw' })}>Withdraw</button>
                )}
                <button type="button" onClick={() => setAct1(row.identifier_id, { mode: a.mode === 'note' ? null : 'note' })}>Add a note</button>
              </div>
              {a.mode && (
                <div className="id-act">
                  <label>{a.mode === 'withdraw' ? 'Why' : 'Note'}
                    <input value={a.note ?? ''} onChange={(e) => setAct1(row.identifier_id, { note: e.target.value })}
                      placeholder={a.mode === 'withdraw' ? 'e.g. typed wrongly; the victim corrected it' : 'e.g. site down since 10 Nov'} />
                  </label>
                  <button type="button" disabled={!(a.note ?? '').trim()} onClick={() => apply(row)}>
                    {a.mode === 'withdraw' ? 'Withdraw it' : 'Record the note'}
                  </button>
                </div>
              )}
              <div className="history">
                {row.history.map((h, i) => <span key={i}>{String(h.at).slice(0, 10)} {historyText(h)}</span>)}
              </div>
            </div>
          )
        })}

        {!form && <div className="request-add"><button type="button" onClick={() => setForm({ ...EMPTY })}>Add a reported identifier</button></div>}
        {form && (
          <form className="id-form" aria-label="Add a reported identifier" onSubmit={save}>
            <div className="fields">
              <label>What it is
                <select value={form.kind} onChange={set('kind')}>
                  {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
              <label>{KINDS[form.kind]}<input value={form.value} onChange={set('value')} className="mono" placeholder={HINTS[form.kind]} /></label>
              <label className="wide">Where the victim saw it<input value={form.context} onChange={set('context')} placeholder="e.g. link sent on WhatsApp; the number that called" /></label>
              <label className="wide">Notes<textarea rows={2} value={form.notes} onChange={set('notes')} /></label>
            </div>
            <div className="request-add">
              <button type="submit" className="id-save" disabled={!form.value.trim()}>Add to the case</button>
              <button type="button" className="quiet" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
        {error && <p className="error-line" role="alert">{error}</p>}
        <p className="note">Each is a lead, not an identity: only the registrar, the telecom or the bank can say who is behind it. Nothing is deleted; a mistake is withdrawn and stays in the history.</p>
      </div>
    </details>
  )
}
