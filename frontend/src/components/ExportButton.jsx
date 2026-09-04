import { useState } from 'react'
import { fetchReport } from '../api'

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

  async function download(format) {
    setBusy(format)
    setError(null)
    try {
      const body = await fetchReport(caseId, format)
      const text = format === 'json' ? JSON.stringify(body, null, 2) : body
      const type = format === 'json' ? 'application/json' : 'text/plain'
      const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }))

      const link = document.createElement('a')
      link.href = url
      link.download = `tracechain-${address.slice(0, 10)}-${caseId.slice(0, 8)}.${format === 'json' ? 'json' : 'txt'}`
      document.body.appendChild(link)
      link.click()
      link.remove()
      // Give the browser a moment to start the download before revoking.
      setTimeout(() => URL.revokeObjectURL(url), 1000)
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
      {error && <span className="export-error" title={error}>export failed</span>}
    </div>
  )
}
