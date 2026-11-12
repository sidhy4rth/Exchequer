// The details a bank or telecom notice needs (backend notice_letters.py),
// typed by the officer. The server checks them and drafts the notice; the
// ticks here only say a field already looks right. Nothing typed is kept:
// it lives in the Letters tab's state and goes to the server in a POST body.
import './NoticeForm.css'

const IFSC = /^[A-Z]{4}0[A-Z0-9]{6}$/
const ACCOUNT = /^[0-9]{6,20}$/
const PHONE = /^(?:\+?91|0)?[6-9][0-9]{9}$/
const squash = (v) => (v ?? '').replace(/[\s-]+/g, '')

/** Which field looks right as typed: drawn as a tick, never a block. */
export function looksRight(name, value) {
  if (name === 'ifsc') return IFSC.test((value ?? '').trim().toUpperCase())
  if (name === 'account') return ACCOUNT.test(squash(value))
  if (name === 'phone') return PHONE.test(squash(value))
  return false
}

const BANK = [
  { name: 'bank', label: 'Bank' },
  { name: 'account', label: 'Account number', mono: true, inputMode: 'numeric' },
  { name: 'ifsc', label: 'IFSC', mono: true },
  { name: 'source', label: 'Where it came from', hint: "e.g. the exchange's reply and its date" },
]
const TELECOM = [
  { name: 'operator', label: 'Phone company' },
  { name: 'phone', label: 'Mobile number', mono: true, inputMode: 'tel' },
  { name: 'source', label: 'Where it came from', hint: "e.g. the exchange's reply and its date" },
]
const PERIOD = [{ name: 'period_from', label: 'From', type: 'date' }, { name: 'period_to', label: 'To', type: 'date' }]
const HOLD = [
  { name: 'order', label: "Magistrate's order", hint: 'number, date and court', tag: 'needed for a hold' },
  { name: 'amount', label: 'Amount (₹)', mono: true, inputMode: 'decimal', tag: 'optional' },
]

/** `to` is bank-info, bank-freeze or telecom; `values` the officer's details. */
export default function NoticeForm({ to, values, onChange, onKind, onDraft }) {
  const telecom = to === 'telecom'
  const hold = to === 'bank-freeze'
  const fields = [...(telecom ? TELECOM : BANK), ...(hold ? HOLD : PERIOD)]
  const field = (f) => {
    const id = `nf-${f.name}`
    const ok = looksRight(f.name, values[f.name])
    return (
      <div className="nf-field" key={f.name}>
        <div className="nf-label">
          <label htmlFor={id}>{f.label}</label>
          {f.tag && <span className={f.tag === 'optional' ? 'nf-tag' : 'nf-tag nf-need'}>{f.tag}</span>}
        </div>
        <div className={f.tag && f.tag !== 'optional' ? 'nf-box nf-box-need' : 'nf-box'}>
          <input id={id} name={f.name} type={f.type ?? 'text'} inputMode={f.inputMode} autoComplete="off" spellCheck={false}
            className={f.mono ? 'nf-mono' : undefined} placeholder={f.hint} value={values[f.name] ?? ''}
            onChange={(e) => onChange({ ...values, [f.name]: e.target.value })} />
          {ok && <svg className="nf-ok" role="img" aria-label="looks right" width="14" height="14" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2.5 6.2l2.4 2.4 4.6-4.8" /></svg>}
        </div>
      </div>
    )
  }
  return (
    <form className="lt-card nf" aria-label={telecom ? 'Phone company details' : 'Bank details'}
      onSubmit={(e) => { e.preventDefault(); onDraft() }}>
      {!telecom && (
        <div className="nf-kind" role="group" aria-label="Kind of letter">
          <button type="button" aria-pressed={!hold} onClick={() => onKind('bank-info')}>Information</button>
          <button type="button" aria-pressed={hold} className="nf-urgent" onClick={() => onKind('bank-freeze')}>Urgent hold</button>
        </div>
      )}
      {fields.filter((f) => f.type !== 'date').map(field)}
      {!hold && <div className="nf-period">{PERIOD.map(field)}</div>}
      <p className="note nf-private">
        <svg aria-hidden="true" width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="7" width="10" height="7" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" /></svg>
        {telecom ? 'The number goes' : 'Account numbers go'} into the letter only. Never saved or logged.
      </p>
      <button type="submit" className="nf-draft">Draft the letter</button>
    </form>
  )
}
