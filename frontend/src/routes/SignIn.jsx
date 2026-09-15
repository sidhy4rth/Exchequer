import { useEffect, useRef, useState } from 'react'
import { fetchHealth, login } from '../api'
import { useAuth } from '../auth'
import ThemeToggle from '../components/ThemeToggle'

const REMEMBER_KEY = 'exchequer-officer'

/**
 * Officer sign-in. The point is the record, not the wall: whoever runs a
 * trace is written into the case and the report header, which is the first
 * line of the chain of custody. The access code is shared and lives on the
 * server; nothing typed here is verified against a directory, it is stated.
 *
 * The page shows the officer exactly what will be recorded, as they type it,
 * and remembers who they are (never the code) so a repeat sign-in is one
 * field.
 */
export default function SignIn() {
  const { refresh } = useAuth()
  const remembered = (() => { try { return JSON.parse(localStorage.getItem(REMEMBER_KEY) || 'null') } catch { return null } })()
  const [name, setName] = useState(remembered?.name ?? '')
  const [officerId, setOfficerId] = useState(remembered?.officerId ?? '')
  const [unit, setUnit] = useState(remembered?.unit ?? '')
  const [code, setCode] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [shake, setShake] = useState(false)
  const [health, setHealth] = useState(null)
  const [clock, setClock] = useState(new Date())
  const codeRef = useRef(null)

  // The status strip: providers and coverage, from the one route that is
  // never gated. It tells the officer what they are signing in to.
  useEffect(() => {
    let cancelled = false
    fetchHealth().then((h) => { if (!cancelled) setHealth(h) }).catch(() => { if (!cancelled) setHealth({ status: 'down' }) })
    const t = setInterval(() => setClock(new Date()), 1000)
    return () => { cancelled = true; clearInterval(t) }
  }, [])

  useEffect(() => { if (remembered && codeRef.current) codeRef.current.focus() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const who = [name.trim() && (officerId.trim() ? `${name.trim()} (ID ${officerId.trim()})` : name.trim()), unit.trim()]
    .filter(Boolean).join(' · ')
  const chains = health?.chains ? Object.values(health.chains) : []
  const labels = chains.reduce((n, c) => n + (c.exchange_labels || 0), 0)
  const down = health?.status === 'down'

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      await login(name.trim(), officerId.trim(), unit.trim(), code)
      try { localStorage.setItem(REMEMBER_KEY, JSON.stringify({ name: name.trim(), officerId: officerId.trim(), unit: unit.trim() })) } catch { /* private mode */ }
      await refresh()
    } catch (err) {
      setError(err.message)
      setShake(true); setTimeout(() => setShake(false), 500)
      setCode('')
      codeRef.current?.focus()
    } finally {
      setBusy(false)
    }
  }

  function forget() {
    try { localStorage.removeItem(REMEMBER_KEY) } catch { /* private mode */ }
    setName(''); setOfficerId(''); setUnit('')
  }

  return (
    <div className="signin">
      <header className="topbar">
        <span className="brand">Exchequer<small>Cryptocurrency fraud tracing</small></span>
        <span className="sysline mono">
          {down ? <><span className="dot down" />BACKEND UNREACHABLE</>
            : health ? <><span className="dot live" />SYSTEM OPERATIONAL · SIGN-IN REQUIRED</>
            : <><span className="dot" />CONNECTING</>}
        </span>
        <span className="grow" />
        <span className="mono clock">{clock.toISOString().slice(0, 19).replace('T', ' ')} UTC</span>
        <ThemeToggle />
      </header>

      <main className="signin-body">
        <div className="signin-grid">
          <form className={`card signin-card ${shake ? 'shake' : ''}`} onSubmit={submit}>
            <div className="body">
              <span className="micro">Officer sign-in</span>
              <h1 className="lede">State who is running this trace. It is written into every case and every report.</h1>
              <p className="note">
                Only the exchange can link an address to a person; only you can say who asked. Nothing here is
                verified against a directory — it is recorded as stated, beside the time and the content hash.
              </p>

              <label className="field">
                <span className="micro">Name and rank</span>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Inspector R. Sharma" required autoComplete="name" autoFocus={!remembered} />
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

              <div className="preview">
                <span className="micro">As it will appear on the report header</span>
                <pre className="mono">{`Traced at        : ${clock.toISOString().slice(0, 19)}+00:00\nTraced by        : ${who || '…'}`}</pre>
              </div>

              <label className="field">
                <span className="micro">Access code</span>
                <input ref={codeRef} type="password" value={code} onChange={(e) => setCode(e.target.value)} required autoComplete="current-password" aria-invalid={!!error} />
              </label>
              {error && <div className="banner error" role="alert">{error}</div>}

              <div className="buttons">
                <button type="submit" className="primary" disabled={busy || !name.trim() || !code || down}>
                  {busy ? 'Signing in…' : 'Sign in'}
                </button>
                {remembered && <button type="button" className="quiet" onClick={forget}>Not {remembered.name}?</button>}
              </div>
              <p className="note small">The access code is set by whoever runs this instance (<span className="mono">EXCHEQUER_ACCESS_CODE</span>). Sessions last 12 hours. Your name is remembered on this browser; the code never is.</p>
            </div>
          </form>

          <aside className="card signin-status">
            <div className="head"><span className="micro">This instance</span><span className="note">{health ? `${labels} exchange labels` : ''}</span></div>
            <div className="body status">
              {!health && <span className="note">Connecting…</span>}
              {down && <div className="line"><span className="dot down" /><span>Backend unreachable</span><span /></div>}
              {chains.map((c) => (
                <div className="line" key={c.key}>
                  <span className={`dot ${c.ready ? 'live' : 'down'}`} />
                  <span>{c.name} <span className="note">via {c.provider}</span></span>
                  <span className="n">{c.exchange_labels} labels · {(c.risk_labels?.sanctioned ?? 0) + (c.risk_labels?.mixer ?? 0)} screened</span>
                </div>
              ))}
              {health && !down && (
                <p className="note small" style={{ marginTop: 8 }}>
                  Every trace you run will be stored under your name, hash every provider response it reads, and produce a report that carries its own content hash.
                </p>
              )}
            </div>
          </aside>
        </div>
      </main>
    </div>
  )
}
