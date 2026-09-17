import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import Lattice from '../components/Lattice'
import ThemeToggle from '../components/ThemeToggle'
import { signIn } from '../session'

// The first screen. The lattice behind it is the tool's own metaphor: an
// unlit ledger that the cursor scans, and a click traces outward hop by hop.

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
      <Lattice />
      <div className="signin-top">
        <span className="micro">Restricted · cyber crime cell</span>
        <ThemeToggle />
      </div>
      <form className="signin-card" onSubmit={submit} onClick={(e) => e.stopPropagation()}>
        <div className="brand-block">
          <svg width="30" height="30" viewBox="0 0 26 26" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true"><circle cx="13" cy="13" r="11.5" /><circle cx="13" cy="13" r="8" /><path d="M13 5v16M5 13h16" /><circle cx="13" cy="13" r="2.4" fill="currentColor" stroke="none" /></svg>
          <span className="name">Exchequer</span>
          <span className="micro">Cryptocurrency fraud tracing</span>
        </div>
        <label>
          <span className="micro">Officer</span>
          <input value={user} onChange={(e) => { setUser(e.target.value); setError(false) }} autoComplete="username" spellCheck={false} autoFocus aria-invalid={error} />
        </label>
        <label>
          <span className="micro">Access code</span>
          <input type="password" value={pass} onChange={(e) => { setPass(e.target.value); setError(false) }} autoComplete="current-password" aria-invalid={error} />
        </label>
        {error && <span className="signin-error">Not recognised.</span>}
        <button type="submit" className="primary" disabled={!user || !pass}>Enter</button>
        <span className="note">Move the cursor to scan the ledger · click to trace</span>
      </form>
      <div className="signin-foot micro">Smart India Hackathon 2026 · SIH26183 · Ministry of Home Affairs</div>
    </div>
  )
}
