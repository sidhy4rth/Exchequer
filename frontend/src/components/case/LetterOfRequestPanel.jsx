import { useEffect, useRef, useState } from 'react'
import { draftLetterOfRequest, logRequest } from '../../api'
import { plain } from '../../text'
import './LetterOfRequestPanel.css'

// A letter of request to the country where the exchange is (backend
// letters_of_request.py, suite feature 7): when an exchange abroad will not
// answer a notice, a Court can ask that country for its records (BNSS s.112),
// through the Ministry of Home Affairs. The draft follows the MHA's format;
// what the officer leaves out is a marked blank. Each field's max is the
// server's limit (letters_of_request.FIELDS), so a long one is cut while typed
// rather than refused without saying which field. Nothing typed is kept: it
// goes to the server in a POST body and comes back as the draft. Once drafted,
// it can be logged in the case's requests log as its own kind, addressed to the
// requested country, so its progress is tracked like any other letter.

// backend letters_of_request.REQUEST_KIND (one of freeze_requests.KINDS)
export const REQUEST_KIND = 'letter-rogatory'

/** The exchange the case reached, directly or after a swap; null when none. */
export function reachedExchange(result) {
  if (result?.exchange) return result.exchange
  return result?.follow_ons?.find((f) => f.result?.exchange)?.result.exchange ?? null
}

export const BASES = { '': 'Not chosen yet', treaty: 'A treaty or convention', reciprocity: 'Assurance of reciprocity' }

const FIELDS = [
  { name: 'country', max: 80, label: 'Requested country', hint: 'where the exchange and its records are' },
  { name: 'court', max: 200, label: 'Court', hint: 'the Court that will issue it, and its place' },
  { name: 'presiding', max: 120, label: 'Presiding officer', hint: 'name' },
  { name: 'reference', max: 120, label: 'FIR / case number', hint: 'and police station' },
  { name: 'agency', max: 200, label: 'Investigating agency', hint: 'police station or unit, and address', wide: true },
  { name: 'offences', max: 1500, label: 'Offences and maximum penalties', hint: 'as in the FIR', wide: true, rows: 2 },
  { name: 'limitation', max: 500, label: 'Limitation', hint: 'not time-barred, citing the provision', wide: true },
  { name: 'facts', max: 4000, label: 'What happened', hint: 'how the victim was approached, what was promised, when they paid', wide: true, rows: 3 },
  { name: 'exchange_office', max: 300, label: "Exchange's registered office", hint: 'if known', wide: true },
  { name: 'period', max: 300, label: 'Urgency', hint: 'e.g. within 60 days, and why', wide: true },
  { name: 'liaison', max: 500, label: 'Liaison officer', hint: 'name, address, phone, e-mail', wide: true },
]

/** `offered`: the server offers this case a letter to the exchange, so the case holds what a letter of
 * request rests on (an outgoing trace that reached it). `onLogged`: called once it is in the requests log. */
export default function LetterOfRequestPanel({ result, offered, onLogged }) {
  const caseId = result?.case_id
  const exchange = reachedExchange(result)
  const [values, setValues] = useState({ basis: '' })
  const [text, setText] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [logged, setLogged] = useState('')
  const drafted = useRef(null)
  const told = useRef(null)
  // A new draft takes the keyboard's place, as the letter to the exchange does.
  useEffect(() => { if (text) drafted.current?.focus() }, [text])

  if (!caseId || !exchange || !offered) return null

  const set = (name) => (e) => { setValues((v) => ({ ...v, [name]: e.target.value })); setText(null) }
  async function draft(e) {
    e.preventDefault()
    if (busy) return
    setError(null)
    setBusy(true)
    try { setText(await draftLetterOfRequest(caseId, values)) } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  const country = (values.country ?? '').trim()
  async function logIt() {
    setError(null)
    try {
      await logRequest({ case_id: caseId, recipient: country, kind: REQUEST_KIND, asset: result.asset ?? '' })
      setLogged(country)
      told.current?.focus() // the button pressed is now disabled: keep the keyboard's place
      onLogged?.()
    } catch (err) { setError(err.message) }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: `exchequer-${caseId.slice(0, 8)}-letter-of-request.txt` })
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <details className="card sec lor-panel">
      <summary>
        <span className="micro">Letter of request abroad</span>
        <span className="note">if {plain(exchange)} will not answer: through a Court and the MHA</span>
      </summary>
      <div className="body">
        <p className="note">
          A Court can ask the country where {plain(exchange)} keeps its records to produce them (BNSS s.112, formerly
          CrPC s.166A). This drafts that letter in the Ministry of Home Affairs&apos; format, with the case&apos;s facts filled
          in. Anything you leave out stays a marked blank. The draft opens with the MHA&apos;s route: its IS-II Division
          first, then the Court.
        </p>
        <form className="lor-form" aria-label="Letter of request details" onSubmit={draft}>
          <div className="fields">
            <label>Basis
              <select value={values.basis} onChange={set('basis')}>
                {Object.entries(BASES).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </label>
            {values.basis === 'treaty' && (
              <label>Treaty or convention<input value={values.treaty ?? ''} onChange={set('treaty')} maxLength={300} placeholder="its name and the provisions relied on" /></label>
            )}
            {FIELDS.map((f) => (
              <label key={f.name} className={f.wide ? 'wide' : undefined}>{f.label}
                {f.rows
                  ? <textarea rows={f.rows} value={values[f.name] ?? ''} onChange={set(f.name)} maxLength={f.max} placeholder={f.hint} />
                  : <input value={values[f.name] ?? ''} onChange={set(f.name)} maxLength={f.max} placeholder={f.hint} autoComplete="off" />}
              </label>
            ))}
          </div>
          <p className="note">What you type goes into the draft only. Nothing is saved.</p>
          <div className="request-add">
            {/* Marked, not disabled, while it drafts: it stays focusable, so the keyboard keeps its place. */}
            <button type="submit" className="lor-draft" aria-disabled={busy || undefined}>{busy ? 'Drafting…' : 'Draft the letter of request'}</button>
          </div>
        </form>
        {error && <p className="error-line" role="alert">{error}</p>}
        {text && (
          <div className="lor-result">
            <div className="request-add">
              <button type="button" onClick={download}>Download (.txt)</button>
              <button type="button" className="quiet" onClick={() => navigator.clipboard?.writeText(text)}>Copy</button>
              <button type="button" onClick={logIt} disabled={!country || logged === country}>Log it in the requests log</button>
            </div>
            <p className="note" role="status" ref={told} tabIndex={-1}>
              {logged && logged === country
                ? `Logged as drafted, to ${plain(logged)}, in the requests log above: move it on there as it goes to the MHA, the Court and abroad.`
                : country ? `Logs it as a letter of request to ${plain(country)}, drafted.` : 'Name the requested country to log it.'}
            </p>
            <pre className="lor-text" role="region" aria-label="The draft letter of request" ref={drafted} tabIndex={0}>{text}</pre>
          </div>
        )}
      </div>
    </details>
  )
}
