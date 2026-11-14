import { useEffect, useState } from 'react'
import { fetchBundle, fetchBundleFiles } from '../../api'
import './CaseBundleButton.css'

/** One zip of the case for handing over: the signed report, the registers as
 * CSV, the audit trail and MANIFEST.txt with each file's SHA-256 (backend
 * case_bundle.py). Shown only where the server has bundles switched on. */
export default function CaseBundleButton({ caseId }) {
  const [files, setFiles] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    fetchBundleFiles().then((body) => { if (live) setFiles(body?.files ?? null) }).catch(() => {})
    return () => { live = false }
  }, [])

  async function download() {
    setBusy(true)
    setError(null)
    try {
      const url = URL.createObjectURL(await fetchBundle(caseId))
      const link = document.createElement('a')
      link.href = url
      link.download = `exchequer-${caseId.slice(0, 8)}-bundle.zip`
      document.body.appendChild(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!files || !caseId) return null
  return (
    <span className="case-bundle">
      <button type="button" className="ev-file" onClick={download} disabled={busy}
        title={`One zip: ${files.join(', ')}. MANIFEST.txt holds each file's SHA-256, so anyone can check it is unchanged since download.`}>
        {busy ? 'Preparing…' : 'Case bundle'}<span className="visually-hidden"> (zip of the report, the registers and the audit trail)</span>
      </button>
      {error && <span className="error-line case-bundle-error" role="alert">The bundle could not be prepared: {error}</span>}
    </span>
  )
}
