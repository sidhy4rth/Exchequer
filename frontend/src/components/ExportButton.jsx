import { useEffect, useRef, useState } from 'react'
import { fetchGraph, fetchLetter, fetchLetters, fetchReport } from '../api'

function save(content, type, filename) {
  const blob = content instanceof Blob ? content : new Blob([content], { type: `${type};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Give the browser a moment to start the download before revoking.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** The request letters this case supports, each a draft to download: to the
 * exchange it reached, and to Tether when USDT or a Tether freeze is
 * involved. A card on the case's Letters tab; `bare`, just the buttons, for
 * Present's handoff screen. */
export function DraftLetters({ caseId, bare = false }) {
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [letters, setLetters] = useState([])

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

  if (!letters.length) return null
  const drafts = <>
    {letters.map((l) => (
      <button key={l.to} type="button" className="draft-letter" onClick={() => draftLetter(l.to)} disabled={busy !== null}
        title="A draft for the officer to complete and sign: the case facts filled in, the legal provision and signature left blank">
        {l.title}<small>case facts filled in; provision and signature left blank</small>
      </button>
    ))}
    {error && <p className="error-line">The letter could not be drafted: {error}</p>}
  </>
  if (bare) return drafts
  return (
    <section className="card draft-letters" aria-labelledby="draft-letters">
      <div className="head"><h2 id="draft-letters" className="micro">Draft letters · {letters.length}</h2></div>
      <div className="body">{drafts}</div>
    </section>
  )
}

/**
 * The case's files: the signed report (`report('pdf' | 'text' | 'json')`) and
 * the transfer graph (`graph('graphml' | 'csv')`), for the Export menu and
 * the Evidence tab. Each resolves once the download has started or failed.
 *
 * The file is built in the browser from the backend's response rather than
 * pointed at with a plain link, so a failed request surfaces as a visible
 * error instead of navigating the user to an error page.
 */
export function useCaseFiles(caseId, address) {
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const name = `exchequer-${address.slice(0, 10)}-${caseId?.slice(0, 8)}`

  async function fetchAndSave(key, get) {
    setBusy(key)
    setError(null)
    try {
      save(...await get())
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  const report = (format) => fetchAndSave(format, async () => {
    const body = await fetchReport(caseId, format)
    const content = format === 'json' ? JSON.stringify(body, null, 2) : body
    const type = { json: 'application/json', pdf: 'application/pdf' }[format] ?? 'text/plain'
    return [content, type, `${name}.${{ json: 'json', pdf: 'pdf' }[format] ?? 'txt'}`]
  })
  const graph = (format) => fetchAndSave(`graph-${format}`, async () => [
    await fetchGraph(caseId, format), format === 'csv' ? 'text/csv' : 'application/graphml+xml', `${name}-graph.${format}`,
  ])
  return { busy, error, report, graph }
}

/** Downloads the case report, from the case header's Export menu. */
export default function ExportButton({ caseId, address, icon = false }) {
  const { busy, error, report: download, graph } = useCaseFiles(caseId, address)
  // Deliberately an inline group, not a titled block: this sits inside the
  // console bar. It previously wrapped itself in `.section`, a landing-page
  // class carrying max-width and 72px of bottom padding, which made it an
  // invisible 739x173 box overhanging the bar and swallowing clicks meant for
  // the controls beneath it.
  const downloadGraph = (format) => graph(format).finally(() => { if (menu.current) menu.current.open = false })

  const menu = useRef(null)
  const pick = (fn) => () => { fn(); if (menu.current) menu.current.open = false }
  return (
    <div className="export-row">
      {/* One menu for the files: a round icon button in the case header
          (`icon`), a labelled one on Present's big screens. */}
      <details className="export-menu" ref={menu}>
        <summary role="button" aria-haspopup="menu" className={icon ? 'icon-btn' : undefined} title={busy ? 'Preparing…' : 'Export the signed report, the data or the graph'}>
          {icon
            ? <><svg aria-hidden="true" width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M9 2v9M5 7l4 4 4-4M3 14h12" /></svg>
              <span className="visually-hidden">{busy ? 'Preparing…' : 'Export'}</span></>
            : busy ? 'Preparing…' : 'Export'}
        </summary>
        <div className="export-list" role="menu">
          <button role="menuitem" onClick={pick(() => download('pdf'))} disabled={busy !== null}>
            Report (.pdf)<small>summary page, then the signed text, attached</small>
          </button>
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
          <a role="menuitem" href="/verify" target="_blank" rel="noopener">Verify a report…</a>
        </div>
      </details>
      {error && <span className="export-error" title={error}>export failed</span>}
    </div>
  )
}
