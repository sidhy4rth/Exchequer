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
        <h2 className="lede">Verified examples</h2>
        <p className="note">Each opens as recorded. Live tracing needs an access code.</p>
        <ul className="showroom-demos" aria-label="Verified examples">
          {demos === null && <li className="note">Loading the verified examples…</li>}
          {demos?.length === 0 && <li className="note">No verified examples on this site.</li>}
          {demos?.map((d) => (
            <li key={d.demo}>
              <Link to={`/demo/${d.demo}`}>
                <span className="mono">{String(d.demo).padStart(2, '0')}</span>
                <span className="mono"><span className="addr-long">{middle(d.address)}</span><span className="addr-short" aria-hidden="true">{middle(d.address, 6, 4)}</span></span>
                <span>{d.exchange ? `reached ${d.exchange}` : 'no exchange matched'}</span>
                <span className="note">recorded {String(d.recorded_at).slice(0, 10)}</span>
              </Link>
            </li>
          ))}
        </ul>
        <form className="showroom-code" onSubmit={submit}>
          <label htmlFor="demo-code">Access code</label>
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
