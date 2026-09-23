import { useEffect, useState } from 'react'
import { fetchLetter, fetchLetters, fetchReport } from '../api'

function save(text, type, filename) {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Give the browser a moment to start the download before revoking.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * Downloads the case report.
 *
 * The file is built in the browser from the backend's response rather than
 * pointed at with a plain link, so a failed request surfaces as a visible
 * error instead of navigating the user to an error page.
 */
export default function ExportButton({ caseId, address }) {
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [letters, setLetters] = useState([])

  // Which request letters this case supports: to the exchange it reached,
  // and to Tether when USDT or a Tether freeze is involved.
  useEffect(() => {
    if (!caseId) return undefined
    let live = true
    fetchLetters(caseId).then((body) => { if (live) setLetters(body.letters ?? []) }).catch(() => {})
    return () => { live = false }
  }, [caseId])

  async function draftLetter(to) {
    setBusy(`letter-${to}`)
    setError(null)
    try {
      save(await fetchLetter(caseId, to), 'text/plain', `exchequer-${caseId.slice(0, 8)}-request-${to}.txt`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  async function download(format) {
    setBusy(format)
    setError(null)
    try {
      const body = await fetchReport(caseId, format)
      const text = format === 'json' ? JSON.stringify(body, null, 2) : body
      const type = format === 'json' ? 'application/json' : 'text/plain'
      save(text, type, `exchequer-${address.slice(0, 10)}-${caseId.slice(0, 8)}.${format === 'json' ? 'json' : 'txt'}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  // Deliberately an inline group, not a titled block: this sits inside the
  // console bar. It previously wrapped itself in `.section`, a landing-page
  // class carrying max-width and 72px of bottom padding, which made it an
  // invisible 739x173 box overhanging the bar and swallowing clicks meant for
  // the controls beneath it.
  return (
    <div className="export-row">
      <button onClick={() => download('text')} disabled={busy !== null}>
        {busy === 'text' ? 'Preparing…' : 'Report (.txt)'}
      </button>
      <button onClick={() => download('json')} disabled={busy !== null}>
        {busy === 'json' ? 'Preparing…' : 'Data (.json)'}
      </button>
      {letters.map((l) => (
        <button key={l.to} onClick={() => draftLetter(l.to)} disabled={busy !== null}
          title="A draft for the officer to complete and sign: the case facts filled in, the legal provision and signature left blank">
          {busy === `letter-${l.to}` ? 'Preparing…' : `Draft: ${l.title}`}
        </button>
      ))}
      {error && <span className="export-error" title={error}>export failed</span>}
    </div>
  )
}
