import { useEffect, useState } from 'react'
import { account, checkAccount, resetAccount, useAccount } from '../session'
import './TraceForm.css'

// The case a signed-in officer's live work runs under: an FIR, NCRP or GD
// number (backend/app/case_refs.py, which checks the same shape). Like the
// NCRP number it is masked here and sent in a request body only, never in a
// link, the server's logs or sessionStorage.
const CASE_REF_RE = /^(?=.*[0-9])[A-Za-z0-9][A-Za-z0-9 /.-]{2,39}$/
export const tidyRef = (value) => value.trim().replace(/\s+/g, ' ')
export const refOk = (value) => CASE_REF_RE.test(tidyRef(value))

/** Whether an officer is signed in, from the app's one account store
 * (session.js, GET /auth/me): null until it knows, so a start button waits
 * for the answer. A demo visitor, a server without accounts or no answer
 * reads as not. Signing in or out in the tab updates it at once. */
export function useSignedIn() {
  const { status } = useAccount()
  useEffect(() => { if (account().status === 'unknown') checkAccount() }, [])
  return status === 'officer' ? true : status === 'none' ? false : null
}

/** For tests: back to before the first check. */
export const forgetSignIn = resetAccount

export default function CaseRefField({ id = 'case-ref', value, onChange, hint = 'FIR, NCRP or GD number · never in links or logs' }) {
  const [show, setShow] = useState(false)
  const bad = tidyRef(value) !== '' && !refOk(value)
  return (
    <div className="nt-field case-ref">
      <label className="nt-k" htmlFor={id}>Case reference</label>
      <span className="nt-secret">
        {/* Masked by the stylesheet, not type=password, so no browser offers to save it. */}
        <input id={id} type="text" className={`fld mono${show ? '' : ' masked'}`} value={value} onChange={(e) => onChange(e.target.value)}
          required maxLength={40} spellCheck={false} autoComplete="off" placeholder="Required" aria-invalid={bad} aria-describedby={`${id}-note`} />
        <button type="button" className="nt-reveal" aria-pressed={show} aria-label="Show the case reference" onClick={() => setShow((v) => !v)}>Show</button>
      </span>
      <span id={`${id}-note`} className="nt-hint">
        {bad ? 'Letters, digits, spaces, / . or -, with at least one digit' : hint}
      </span>
    </div>
  )
}
