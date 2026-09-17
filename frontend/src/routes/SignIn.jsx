import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import Ledger from '../components/Ledger'
import Mark from '../components/Mark'
import ThemeToggle from '../components/ThemeToggle'
import { signIn } from '../session'

// The first screen. Behind the card is the ledger the tool knows, real
// addresses coloured by what it knows about them; the cursor reads it and a
// click traces an address across it. The card is a demonstration front door
// -- see session.js -- not access control.

export default function SignIn() {
  const navigate = useNavigate()
  const location = useLocation()
  const [user, setUser] = useState('')
  const [pass, setPass] = useState('')
  const [error, setError] = useState(false)

  function submit(event) {
    event.preventDefault()
    if (signIn(user, pass)) {
      navigate(location.state?.from ?? '/', { replace: true })
    } else {
      setError(true)
    }
  }

  return (
    <div className="signin">
      <Ledger />
      <div className="signin-top">
        <span className="micro">Restricted · cyber crime cell</span>
        <ThemeToggle />
      </div>
      <form className="signin-card" onSubmit={submit} autoComplete="off">
        <div className="card-head">
          <Mark size={34} />
          <div className="card-title">
            <span className="name">Exchequer</span>
            <span className="micro">Cryptocurrency fraud tracing</span>
          </div>
          <span className="status"><i /><span className="micro">Restricted</span></span>
        </div>
        <div className="rule" />
        <label className="field">
          <span className="micro">Officer</span>
          <input value={user} onChange={(e) => { setUser(e.target.value); setError(false) }} placeholder="name or service ID" spellCheck={false} autoFocus aria-invalid={error} />
        </label>
        <label className="field">
          <span className="micro">Access code</span>
          <input type="password" value={pass} onChange={(e) => { setPass(e.target.value); setError(false) }} placeholder="••••••••" aria-invalid={error} />
        </label>
        {error && <span className="signin-error">Not recognised.</span>}
        <button type="submit" className="primary enter" disabled={!user || !pass}>
          Enter the ledger
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M2 7h10M8 3l4 4-4 4" /></svg>
        </button>
        <span className="note">Move the cursor to read the ledger · click an address to trace it</span>
      </form>
      <div className="signin-foot micro">Smart India Hackathon 2026 · SIH26183 · Ministry of Home Affairs</div>
    </div>
  )
}
