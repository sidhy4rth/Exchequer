import { useEffect, useState } from 'react'
import { fetchSopSteps, fetchSopStepsOffered } from '../../api'
import './SopSteps.css'

// The CFCFRMS SOP's steps beside what this case's records show (backend
// sop_steps.py, flag EXCHEQUER_SOP_STEPS). Shown only when the server offers
// it, on a stored case; the steps are fetched (and audited) only when opened.
// Every line quotes the SOP with its section and page: quoted, never applied.

export default function SopSteps({ result }) {
  const caseId = result?.case_id
  const [offered, setOffered] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!caseId) return undefined
    let live = true
    fetchSopStepsOffered().then((d) => live && setOffered(Boolean(d?.enabled))).catch(() => {})
    return () => { live = false }
  }, [caseId])
  if (!caseId || !offered) return null

  function opened(e) {
    if (!e.currentTarget.open || data) return
    setError('')
    fetchSopSteps(caseId).then(setData).catch((err) => setError(`The steps could not be loaded: ${err.message}`))
  }

  return (
    <details className="card sec sop-steps" onToggle={opened}>
      <summary>
        <span className="micro">CFCFRMS SOP steps</span>
        <span className="note">what the SOP says at each step, beside this case's records</span>
      </summary>
      <div className="body ss-body">
        {error && <p className="note" role="alert">{error}</p>}
        {!data && !error && <p className="note" aria-live="polite">Loading…</p>}
        {data && <>
          <p className="note">{data.note}</p>
          <ol className="ss-list">
            {data.steps.map((s) => (
              <li key={s.id}>
                <strong>{s.title}</strong>
                {s.cites.map((c) => (
                  <blockquote key={c.section}>“{c.quote}”<cite>SOP {c.section}, PDF page {c.page}</cite></blockquote>
                ))}
                <p className="ss-case"><span className="micro">This case</span> {s.case}</p>
              </li>
            ))}
          </ol>
          <p className="note">Source: {data.source}</p>
        </>}
      </div>
    </details>
  )
}
