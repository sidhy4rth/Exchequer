import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { checkDemoCode, fetchRecordedDemos } from '../api'
import { rememberDemoCode } from '../demoCode'
import './Showroom.css'

const middle = (a, head = 10, tail = 8) => (a && a.length > head + tail + 1 ? `${a.slice(0, head)}…${a.slice(-tail)}` : a)

/** The public console before a demo code is entered (backend/app/access.py):
 * the recorded demos, which open exactly as recorded and never trace, and a
 * box for the code that unlocks live tracing. `onUnlock` runs once the
 * backend has accepted the code. */
export default function Showroom({ onUnlock }) {
  const [demos, setDemos] = useState(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    fetchRecordedDemos().then((d) => setDemos(d.demos ?? [])).catch(() => setDemos([]))
  }, [])

  async function submit(event) {
    event.preventDefault()
    const typed = code.trim()
    if (!typed) return
    setChecking(true)
    setError('')
    try {
      await checkDemoCode(typed)
      rememberDemoCode(typed)
      onUnlock()
    } catch (err) {
      setError(err.message)
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="card showroom">
      <div className="body">
        <p className="lede">Follow a reported wallet's money to the exchange it left through.</p>
        <p className="note">
          This public site shows recorded traces. Each opens exactly as it was recorded; nothing is traced again.
          Live tracing needs a demo code.
        </p>
        <ul className="showroom-demos" aria-label="Recorded demos">
          {demos === null && <li className="note">Loading the recorded demos…</li>}
          {demos?.length === 0 && <li className="note">No recorded demos on this site.</li>}
          {demos?.map((d) => (
            <li key={d.demo}>
              <Link to={`/demo/${d.demo}`}>
                <span className="mono">{String(d.demo).padStart(2, '0')}</span>
                <span className="mono">{middle(d.address)}</span>
                <span>{d.exchange ? `reached ${d.exchange}` : 'no exchange matched'}</span>
                <span className="note">recorded {String(d.recorded_at).slice(0, 10)}</span>
              </Link>
            </li>
          ))}
        </ul>
        <form className="showroom-code" onSubmit={submit}>
          <label htmlFor="demo-code">Demo code</label>
          <input
            id="demo-code" type="password" value={code} onChange={(e) => setCode(e.target.value)}
            autoComplete="off" spellCheck={false}
          />
          <button type="submit" className="primary" disabled={!code.trim() || checking}>
            {checking ? 'Checking…' : 'Unlock live tracing'}
          </button>
        </form>
        {error && <div className="banner warn" role="alert">{error}</div>}
      </div>
    </div>
  )
}
