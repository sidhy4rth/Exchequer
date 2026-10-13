import { useEffect, useRef, useState } from 'react'
import { fetchGraph, fetchLetter, fetchLetters, fetchReport } from '../api'

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
  async function downloadGraph(format) {
    setBusy(`graph-${format}`)
    setError(null)
    try {
      const type = format === 'csv' ? 'text/csv' : 'application/graphml+xml'
      save(await fetchGraph(caseId, format), type, `exchequer-${address.slice(0, 10)}-${caseId.slice(0, 8)}-graph.${format}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
      if (menu.current) menu.current.open = false
    }
  }

  const menu = useRef(null)
  const pick = (fn) => () => { fn(); if (menu.current) menu.current.open = false }
  return (
    <div className="export-row">
      {/* One menu for the files, so the console bar keeps room for the
          letters: four export buttons in a row pushed the last one off-screen. */}
      <details className="export-menu" ref={menu}>
        <summary role="button" aria-haspopup="menu">{busy ? 'Preparing…' : 'Export'}</summary>
        <div className="export-list" role="menu">
          <button role="menuitem" onClick={pick(() => download('text'))} disabled={busy !== null}>
            Report (.txt)<small>signed; check it at /verify</small>
          </button>
          <button role="menuitem" onClick={pick(() => download('json'))} disabled={busy !== null}>
            Data (.json)<small>everything the case holds</small>
          </button>
          <button role="menuitem" onClick={() => downloadGraph('graphml')} disabled={busy !== null}>
            Graph (.graphml)<small>Gephi, yEd, Maltego, Cytoscape</small>
          </button>
          <button role="menuitem" onClick={() => downloadGraph('csv')} disabled={busy !== null}>
            Graph (.csv)<small>addresses and transfers, for a spreadsheet</small>
          </button>
          {letters.length > 0 && <span className="export-group">Draft letters</span>}
          {letters.map((l) => (
            <button key={l.to} role="menuitem" onClick={pick(() => draftLetter(l.to))} disabled={busy !== null}
              title="A draft for the officer to complete and sign: the case facts filled in, the legal provision and signature left blank">
              {l.title}<small>case facts filled in; provision and signature left blank</small>
            </button>
          ))}
          <a role="menuitem" href="/verify" target="_blank" rel="noopener">Verify a report…</a>
        </div>
      </details>
      {error && <span className="export-error" title={error}>export failed</span>}
    </div>
  )
}
