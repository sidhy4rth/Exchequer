import { useEffect, useState } from 'react'
import { fetchSopSummary, fetchSopSummaryOffered } from '../../api'
import { ncrpNote } from '../../ncrp'
import './CryptoSummary.css'

// A copy-ready crypto summary of the case in the CFCFRMS SOP's 9.4 terms
// (backend sop_summary.py, flag EXCHEQUER_SOP_SUMMARY): for the officer to
// enter on CFCFRMS or attach. Shown only when the server offers it, and only
// on a stored case. The CFCFRMS answer goes to the server as one of three
// words; the NCRP number never does: it is filled in here, in the copied text.

export const NCRP_BLANK = 'NCRP acknowledgement no.: [officer to enter]' // as the server writes it
const ANSWERS = [['yes', 'Yes'], ['no', 'No'], ['unknown', 'Not known']]

/** The server's text with the NCRP line filled in, when the officer typed a number. */
export function withNcrp(text, ncrp) {
  const typed = ncrp.trim()
  // A function, so a "$&" or "$'" typed is put in as it is, not read as a replacement pattern.
  return typed ? text.replace(NCRP_BLANK, () => `NCRP acknowledgement no.: ${typed}`) : text
}

export default function CryptoSummary({ result }) {
  const caseId = result?.case_id
  const [offered, setOffered] = useState(false)
  const [answer, setAnswer] = useState('unknown')
  const [ncrp, setNcrp] = useState('')
  const [text, setText] = useState('')
  const [said, setSaid] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!caseId) return undefined
    let live = true
    fetchSopSummaryOffered().then((d) => live && setOffered(Boolean(d?.enabled))).catch(() => {})
    return () => { live = false }
  }, [caseId])
  if (!caseId || !offered) return null

  async function copy() {
    setBusy(true)
    setSaid('')
    try {
      const full = withNcrp(await fetchSopSummary(caseId, answer), ncrp)
      setText(full)
      try {
        await navigator.clipboard.writeText(full)
        setSaid('Copied. Paste it into CFCFRMS or attach it; check every line first.')
      } catch { setSaid('This browser could not copy it: select the text below and copy it.') }
    } catch (e) { setSaid(`The summary could not be made: ${e.message}`) } finally { setBusy(false) }
  }
  const note = ncrpNote(ncrp)

  return (
    <details className="card sec crypto-summary">
      <summary>
        <span className="micro">Crypto summary for CFCFRMS</span>
        <span className="note">SOP 9.4, for the officer to enter or attach</span>
      </summary>
      <div className="body cs-body">
        <p className="note">The exchange this trace reached, its address and how it was attributed, and the amounts and hashes, in the words of the CFCFRMS SOP's para 9.4. It is not a CFCFRMS export and gives no legal advice.</p>
        <fieldset className="cs-answer">
          <legend>Is this exchange on CFCFRMS?</legend>
          {ANSWERS.map(([value, label]) => (
            <label key={value}><input type="radio" name="cs-on-cfcfrms" value={value} checked={answer === value} onChange={() => setAnswer(value)} />{label}</label>
          ))}
          <span className="note">Your answer, from the portal: Exchequer holds no list of onboarded exchanges. Not stored.</span>
        </fieldset>
        <label className="cs-ncrp">NCRP acknowledgement number (optional)
          <input className="mono" value={ncrp} onChange={(e) => setNcrp(e.target.value)} maxLength={64} autoComplete="off" spellCheck={false}
            aria-describedby="cs-ncrp-hint" />
          <span className="note" id="cs-ncrp-hint">Only in the copied text: never sent to the server or kept.{note && ` ${note}`}</span>
        </label>
        <button type="button" onClick={copy} disabled={busy}>{busy ? 'Making the summary…' : 'Copy the summary'}</button>
        <p className="note" role="status">{said}</p>
        {text && <textarea className="cs-text mono" readOnly rows={12} value={text} aria-label="The crypto summary's text" />}
      </div>
    </details>
  )
}
