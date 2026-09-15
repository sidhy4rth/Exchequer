import { useState } from 'react'
import { login } from '../api'
import { useAuth } from '../auth'
import ThemeToggle from '../components/ThemeToggle'

/**
 * Officer sign-in. The point is the record, not the wall: whoever runs a
 * trace is written into the case and the report header, which is the first
 * line of the chain of custody. The access code is shared and lives on the
 * server; nothing typed here is verified against a directory, it is stated.
 */
export default function SignIn() {
  const { refresh } = useAuth()
  const [name, setName] = useState('')
  const [officerId, setOfficerId] = useState('')
  const [unit, setUnit] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      await login(name.trim(), officerId.trim(), unit.trim(), code)
      await refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="signin">
      <header className="topbar">
        <span className="brand">Exchequer<small>Cryptocurrency fraud tracing</small></span>
        <span className="grow" />
        <span className="note">Smart India Hackathon 2026 · SIH26183 · Ministry of Home Affairs</span>
        <ThemeToggle />
      </header>
      <main className="signin-body">
        <form className="card signin-card" onSubmit={submit}>
          <div className="body">
            <span className="micro">Officer sign-in</span>
            <h1 className="lede">State who is running this trace. It is written into every case and every report.</h1>
            <p className="note">
              Only the exchange can link an address to a person; only you can say who asked. The name, ID and unit
              below go on the report header beside the time and the content hash. Nothing is verified against a
              directory — it is recorded as stated.
            </p>
            <label className="field">
              <span className="micro">Name and rank</span>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Inspector R. Sharma" required autoComplete="name" autoFocus />
            </label>
            <div className="two">
              <label className="field">
                <span className="micro">Service ID</span>
                <input value={officerId} onChange={(e) => setOfficerId(e.target.value)} placeholder="4471" autoComplete="off" />
              </label>
              <label className="field">
                <span className="micro">Unit</span>
                <input value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="Cyber Cell, Bengaluru" autoComplete="organization" />
              </label>
            </div>
            <label className="field">
              <span className="micro">Access code</span>
              <input type="password" value={code} onChange={(e) => setCode(e.target.value)} required autoComplete="current-password" />
            </label>
            {error && <div className="banner error">{error}</div>}
            <button type="submit" className="primary" disabled={busy || !name.trim() || !code}>
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
            <p className="note small">The access code is set by whoever runs this instance (<span className="mono">EXCHEQUER_ACCESS_CODE</span>). Sessions last 12 hours.</p>
          </div>
        </form>
      </main>
    </div>
  )
}
