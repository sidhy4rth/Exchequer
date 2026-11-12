import { useEffect, useState } from 'react'
import { addAsset, fetchCaseAssets, fetchCaseRequests, updateAsset } from '../../api'
import { plain } from '../../text'
import { middle } from './format'
import './AssetsPanel.css'

// The asset register (backend assets.py, suite feature 9): every amount frozen
// or seized in this case, where it is held, who holds the keys (names only),
// and the court's deadline. A freeze request marked Frozen in the log above
// can be added in one click. Nothing is deleted: a row ends in an outcome.

export const HOLDERS = {
  custody: "The unit's custody wallet",
  exchange: 'Held at an exchange',
  bank: 'Held at a bank',
  issuer: "Frozen by the token's issuer",
}
export const OUTCOMES = {
  released_to_victim: 'Released to the victim',
  returned_to_owner: 'Returned to its owner',
  confiscated: 'Confiscated',
  sold: 'Sold',
}

/** Where a freeze request's frozen money is held, by the kind of letter that froze it. */
export function holderOf(kind) {
  if (kind?.startsWith('tether')) return 'issuer'
  if (kind?.startsWith('bank')) return 'bank'
  return 'exchange'
}

/** India's date today, as the seizure date's default. */
export const todayInIndia = (now = new Date()) => new Date(now.getTime() + 330 * 60_000).toISOString().slice(0, 10)

const day = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

/** What the deadline means now: { tone, text } for a pill. */
export function deadline(a) {
  if (a.status !== 'held') return { tone: '', text: OUTCOMES[a.status] ?? a.status }
  if (a.order_ref) return { tone: 'green', text: "Court's order recorded" }
  if (a.days_left < 0) return { tone: 'red', text: `Court order overdue by ${-a.days_left} day${a.days_left === -1 ? '' : 's'}` }
  if (a.days_left <= 7) return { tone: 'red', text: a.days_left === 0 ? 'Court order due today' : `Court order due in ${a.days_left} day${a.days_left === 1 ? '' : 's'}` }
  return { tone: '', text: `Court order due ${day(a.deadline)} · ${a.days_left} days` }
}

const EMPTY = { holder: 'custody', asset: '', amount: '', chain: '', held_at: '', tx_hash: '', key_holders: '', seized_on: '', order_ref: '', notes: '' }

export default function AssetsPanel({ result }) {
  const caseId = result?.case_id
  const [rows, setRows] = useState([])
  const [frozen, setFrozen] = useState([]) // freeze requests marked Frozen, not yet in the register
  const [form, setForm] = useState(null) // the add form's values while it is open
  const [error, setError] = useState(null)
  const [outcome, setOutcome] = useState({}) // asset_id → { status, ref }

  const load = () => caseId && Promise.all([fetchCaseAssets(caseId), fetchCaseRequests(caseId)]).then(([a, r]) => {
    const kept = a.assets ?? []
    setRows(kept)
    setFrozen((r.requests ?? []).filter((q) => q.status === 'frozen' && !kept.some((k) => k.request_id === q.request_id)))
  }).catch(() => {})
  useEffect(() => { load() }, [caseId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!caseId) return null

  async function run(fn) {
    setError(null)
    try { await fn(); await load(); return true } catch (e) { setError(e.message); return false }
  }
  const open = (values = {}) => setForm({ ...EMPTY, seized_on: todayInIndia(), ...values })
  const fromRequest = (q) => open({
    holder: holderOf(q.kind), asset: q.asset || (q.kind?.startsWith('bank') ? 'INR' : ''),
    amount: q.amount_frozen != null ? String(q.amount_frozen) : '', held_at: q.recipient, request_id: q.request_id,
  })
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
  async function save(e) {
    e.preventDefault()
    if (await run(() => addAsset(caseId, form))) setForm(null)
  }
  const due = rows.filter((a) => a.due && a.days_left <= 7).length

  return (
    <details className="card sec assets-panel" open={rows.length > 0 || frozen.length > 0}>
      <summary>
        <span className="micro">Frozen and seized · {rows.length}</span>
        <span className="note">{due ? `${due} court deadline${due === 1 ? '' : 's'} this week` : 'held for the court, and what came of it'}</span>
      </summary>
      <div className="body requests-panel">
        {rows.map((a) => {
          const d = deadline(a)
          const pick = outcome[a.asset_id] ?? { status: '', ref: '' }
          return (
            <div className="request-row" key={a.asset_id}>
              <div className="top">
                <span className="nm"><span className="mono">{a.amount}</span> {plain(a.asset)} <span className="note">· {HOLDERS[a.holder] ?? a.holder}</span></span>
                <span className={`pill ${d.tone}`}>{d.text}</span>
              </div>
              <dl className="as-facts">
                {a.held_at && <><dt>Where</dt><dd className={a.holder === 'custody' ? 'mono' : undefined}>{a.holder === 'custody' ? middle(a.held_at) : plain(a.held_at)}</dd></>}
                {a.tx_hash && <><dt>Moved in</dt><dd className="mono" title={a.tx_hash}>{middle(a.tx_hash)}</dd></>}
                {a.key_holders && <><dt>Keys held by</dt><dd>{plain(a.key_holders)}</dd></>}
                <dt>Seized</dt><dd>{day(a.seized_on)}</dd>
                {a.order_ref && <><dt>Court's order</dt><dd>{plain(a.order_ref)}</dd></>}
                {a.status !== 'held' && <><dt>Outcome</dt><dd>{OUTCOMES[a.status]}{a.outcome_tx ? ` · tx ${middle(a.outcome_tx)}` : ''}{a.outcome_ref ? ` · ${plain(a.outcome_ref)}` : ''}</dd></>}
              </dl>
              {a.status === 'held' && (
                <div className="fields">
                  <label>Court&apos;s order on custody
                    <input defaultValue={a.order_ref} placeholder="number, date and court"
                      onBlur={(e) => e.target.value !== a.order_ref && run(() => updateAsset(a.asset_id, { order_ref: e.target.value }))} />
                  </label>
                  <label>Keys held by
                    <input defaultValue={a.key_holders} placeholder="names only, never a key"
                      onBlur={(e) => e.target.value !== a.key_holders && run(() => updateAsset(a.asset_id, { key_holders: e.target.value }))} />
                  </label>
                  <label>Outcome
                    <select value={pick.status} onChange={(e) => setOutcome((o) => ({ ...o, [a.asset_id]: { ...pick, status: e.target.value } }))}>
                      <option value="">Still held</option>
                      {Object.entries(OUTCOMES).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                    </select>
                  </label>
                  {pick.status && (
                    <label>Transaction hash or order
                      <input value={pick.ref} onChange={(e) => setOutcome((o) => ({ ...o, [a.asset_id]: { ...pick, ref: e.target.value } }))} />
                    </label>
                  )}
                  {pick.status && (
                    <button type="button" disabled={!pick.ref.trim()} onClick={() => run(() => updateAsset(a.asset_id, {
                      status: pick.status, ...(/^(0x)?[0-9a-fA-F]{64}$/.test(pick.ref.trim()) ? { outcome_tx: pick.ref.trim() } : { outcome_ref: pick.ref.trim() }),
                    }))}>Record the outcome</button>
                  )}
                </div>
              )}
              <div className="history">
                {a.history.map((h, i) => <span key={i}>{String(h.at).slice(0, 10)} {h.changed ? `changed ${h.changed.join(', ').replaceAll('_', ' ')}` : 'recorded'}</span>)}
              </div>
            </div>
          )
        })}

        <div className="request-add">
          {frozen.map((q) => (
            <button key={q.request_id} type="button" onClick={() => fromRequest(q)}>
              Add the {q.amount_frozen != null ? `${q.amount_frozen} ${q.asset || ''}`.trim() : 'funds'} {plain(q.recipient)} froze
            </button>
          ))}
          {!form && <button type="button" onClick={() => open()}>Record frozen or seized funds</button>}
        </div>

        {form && (
          <form className="as-form" aria-label="Record frozen or seized funds" onSubmit={save}>
            <div className="fields">
              <label>Where it is held
                <select value={form.holder} onChange={set('holder')}>
                  {Object.entries(HOLDERS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
              </label>
              <label>Asset<input value={form.asset} onChange={set('asset')} placeholder="USDT, ETH, INR" /></label>
              <label>Amount<input value={form.amount} onChange={set('amount')} inputMode="decimal" className="mono" /></label>
              <label>Date seized<input type="date" value={form.seized_on} onChange={set('seized_on')} /></label>
              <label className="wide">{form.holder === 'custody' ? "Custody wallet's address" : 'Exchange, bank or issuer'}
                <input value={form.held_at} onChange={set('held_at')} className={form.holder === 'custody' ? 'mono' : undefined} />
              </label>
              {form.holder === 'custody' && <>
                <label>Chain<input value={form.chain} onChange={set('chain')} placeholder="tron, ethereum…" /></label>
                <label className="wide">Transaction into custody<input value={form.tx_hash} onChange={set('tx_hash')} className="mono" placeholder="the transfer's hash" /></label>
              </>}
              <label className="wide">Keys held by<input value={form.key_holders} onChange={set('key_holders')} placeholder="e.g. 2 of 3: Insp. Rao, SI Iyer, SI Pal" /></label>
              <label className="wide">Court&apos;s order on custody, if made<input value={form.order_ref} onChange={set('order_ref')} placeholder="number, date and court" /></label>
              <label className="wide">Notes<textarea rows={2} value={form.notes} onChange={set('notes')} /></label>
            </div>
            <p className="note as-never">Never type a private key or seed phrase here: they stay offline with the officers who hold them.</p>
            <div className="request-add">
              <button type="submit" className="as-save">Add to the register</button>
              <button type="button" className="quiet" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
        {error && <p className="error-line" role="alert">{error}</p>}
        <p className="note">The court is to order the custody of seized property within 45 days of the seizure (BNSS s.497, as the Karnataka High Court has read it). Kept with this browser&apos;s and unit&apos;s records.</p>
      </div>
    </details>
  )
}
