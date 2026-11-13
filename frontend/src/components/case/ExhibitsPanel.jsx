import { useEffect, useRef, useState } from 'react'
import { addExhibit, checkExhibit, fetchCaseExhibits, updateExhibit } from '../../api'
import { plain } from '../../text'
import { middle } from './format'
import { hashFile } from './sha256'
import { todayInIndia } from './AssetsPanel'
import './ExhibitsPanel.css'

// The exhibit register on the Evidence tab (backend exhibits.py, suite feature
// 3): each file an outside forensic tool made for the case, by its hashes, with
// who made it, where it is kept and who holds it. The file never leaves this
// computer: its SHA-256 is computed here (sha256.js) and only the hash is sent.

export const KINDS = {
  phone_extraction: 'Phone extraction',
  disk_image: 'Disk image',
  memory_capture: 'Memory capture',
  tool_report: 'Tool report',
  video: 'Video recording',
  document: 'Document',
  other: 'Other',
}
const ENDS = { released: 'Released', destroyed: 'Destroyed' }

/** A size in bytes as a person reads it: 64.0 GB, 812 KB. */
export function size(bytes) {
  if (bytes == null) return ''
  const units = ['bytes', 'KB', 'MB', 'GB', 'TB', 'PB']
  let n = bytes
  let u = 0
  while (n >= 1000 && u < units.length - 1) { n /= 1000; u += 1 }
  return u === 0 ? `${bytes} bytes` : `${n.toFixed(1)} ${units[u]}`
}

/** The last check of a file against this exhibit, if any: { tone, text }. */
export function lastCheck(e) {
  const c = [...(e.history ?? [])].reverse().find((h) => h.action === 'checked')
  if (!c) return null
  const day = String(c.at).slice(0, 10)
  return c.result === 'match' ? { tone: 'green', text: `File checked ${day}: matches` }
    : { tone: 'red', text: `File checked ${day}: does NOT match` }
}

const EMPTY = { kind: 'phone_extraction', label: '', tool: '', file_name: '', size_bytes: '', sha256: '', sha1: '', md5: '', made_by: '', made_on: '', stored_at: '', holder: '', notes: '' }

/** Hash a file here and report progress; `run` gives back the hash or null if stopped. */
function useHasher() {
  const [busy, setBusy] = useState(null) // { name, done }
  const stop = useRef(null)
  async function run(file) {
    stop.current = new AbortController()
    setBusy({ name: file.name, done: 0 })
    try {
      return await hashFile(file, { signal: stop.current.signal, onProgress: (done) => setBusy({ name: file.name, done }) })
    } catch (e) {
      if (e.name === 'AbortError') return null
      throw e
    } finally { setBusy(null) }
  }
  return { busy, run, cancel: () => stop.current?.abort() }
}

function Progress({ busy, cancel }) {
  if (!busy) return null
  return (
    <div className="ex-progress" role="status">
      <span>Hashing {busy.name} on this computer… {Math.round(busy.done * 100)}%</span>
      <progress max="1" value={busy.done} aria-label="Hashing progress" />
      <button type="button" className="quiet" onClick={cancel}>Stop</button>
    </div>
  )
}

export default function ExhibitsPanel({ result }) {
  const caseId = result?.case_id
  const [rows, setRows] = useState([])
  const [form, setForm] = useState(null)
  const [error, setError] = useState(null)
  const [said, setSaid] = useState(null)
  const [act, setAct] = useState({}) // exhibit_id → { mode: 'handover' | 'end', holder, status, note }
  const hasher = useHasher()

  const load = () => caseId && fetchCaseExhibits(caseId).then((d) => setRows(d.exhibits ?? [])).catch(() => {})
  useEffect(() => { load() }, [caseId]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!caseId) return null

  async function run(fn) {
    setError(null)
    try { const out = await fn(); await load(); return out ?? true } catch (e) { setError(e.message); return false }
  }
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
  async function fillFrom(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    try {
      const sha256 = await hasher.run(file)
      if (sha256) setForm((f) => ({ ...f, sha256, file_name: f.file_name || file.name, size_bytes: String(file.size) }))
    } catch (err) { setError(`The file could not be read: ${err.message}`) }
  }
  async function save(e) {
    e.preventDefault()
    if (await run(() => addExhibit(caseId, { ...form, size_bytes: form.size_bytes === '' ? null : form.size_bytes }))) {
      setForm(null)
      setSaid('Recorded. Only its hashes were sent; the file stayed on this computer.')
    }
  }
  async function checkFile(ex, e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setSaid(null)
    try {
      const sha256 = await hasher.run(file)
      if (!sha256) return
      const out = await run(() => checkExhibit(ex.exhibit_id, sha256))
      if (out) setSaid(out.result === 'match' ? `${file.name} matches exhibit "${plain(ex.label)}".`
        : `${file.name} does NOT match exhibit "${plain(ex.label)}": it is not the file that was recorded, or it has changed.`)
    } catch (err) { setError(`The file could not be read: ${err.message}`) }
  }
  const pick = (id) => act[id] ?? {}
  const setAct1 = (id, values) => setAct((a) => ({ ...a, [id]: { ...a[id], ...values } }))
  async function apply(ex) {
    const a = pick(ex.exhibit_id)
    const changes = a.mode === 'handover' ? { holder: a.holder ?? '', note: a.note ?? '' } : { status: a.status ?? 'released', note: a.note ?? '' }
    if (await run(() => updateExhibit(ex.exhibit_id, changes))) setAct((all) => ({ ...all, [ex.exhibit_id]: {} }))
  }

  return (
    <details className="card sec exhibits-panel" open={rows.length > 0}>
      <summary><span className="micro">Exhibits · {rows.length}</span><span className="note">forensic files, by their hashes</span></summary>
      <div className="body requests-panel">
        {rows.map((ex) => {
          const check = lastCheck(ex)
          const a = pick(ex.exhibit_id)
          return (
            <div className="request-row" key={ex.exhibit_id}>
              <div className="top">
                <span className="nm">{plain(ex.label)} <span className="note">· {KINDS[ex.kind] ?? ex.kind}</span></span>
                <span className={`pill ${ex.status === 'held' ? '' : 'amber'}`}>{ex.status === 'held' ? `Held by ${plain(ex.holder) || 'the unit'}` : ENDS[ex.status]}</span>
              </div>
              <dl className="ex-facts">
                <dt>Tool</dt><dd>{plain(ex.tool)}</dd>
                {(ex.file_name || ex.size_bytes != null) && <><dt>File</dt><dd>{plain(ex.file_name)}{ex.size_bytes != null ? `${ex.file_name ? ' · ' : ''}${size(ex.size_bytes)}` : ''}</dd></>}
                {ex.sha256 && <><dt>SHA-256</dt><dd className="mono" title={ex.sha256}>{middle(ex.sha256, 16, 12)}</dd></>}
                {ex.sha1 && <><dt>SHA-1</dt><dd className="mono" title={ex.sha1}>{middle(ex.sha1, 12, 10)}</dd></>}
                {ex.md5 && <><dt>MD5</dt><dd className="mono" title={ex.md5}>{middle(ex.md5, 12, 10)}</dd></>}
                <dt>Made</dt><dd>{ex.made_on}{ex.made_by ? ` by ${plain(ex.made_by)}` : ''}</dd>
                {ex.stored_at && <><dt>Kept at</dt><dd>{plain(ex.stored_at)}</dd></>}
              </dl>
              {check && <span className={`pill ${check.tone} ex-check`}>{check.text}</span>}
              {ex.status === 'held' && (
                <div className="request-add">
                  {ex.sha256 && (
                    <label className="ex-file">Check a file against this exhibit
                      <input type="file" disabled={Boolean(hasher.busy)} onChange={(e) => checkFile(ex, e)} />
                    </label>
                  )}
                  <button type="button" onClick={() => setAct1(ex.exhibit_id, { mode: a.mode === 'handover' ? null : 'handover' })}>Hand over</button>
                  <button type="button" onClick={() => setAct1(ex.exhibit_id, { mode: a.mode === 'end' ? null : 'end' })}>Release or destroy</button>
                </div>
              )}
              {a.mode && (
                <div className="fields ex-act">
                  {a.mode === 'handover' ? (
                    <label>To whom<input value={a.holder ?? ''} onChange={(e) => setAct1(ex.exhibit_id, { holder: e.target.value })} /></label>
                  ) : (
                    <label>What happened
                      <select value={a.status ?? 'released'} onChange={(e) => setAct1(ex.exhibit_id, { status: e.target.value })}>
                        {Object.entries(ENDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                      </select>
                    </label>
                  )}
                  <label>Why<input value={a.note ?? ''} onChange={(e) => setAct1(ex.exhibit_id, { note: e.target.value })} placeholder={a.mode === 'handover' ? 'e.g. for the s.63 certificate' : "e.g. on the court's order"} /></label>
                  <button type="button" disabled={!(a.note ?? '').trim() || (a.mode === 'handover' && !(a.holder ?? '').trim())} onClick={() => apply(ex)}>
                    {a.mode === 'handover' ? 'Record the hand-over' : 'Record it'}
                  </button>
                </div>
              )}
              <div className="history">
                {ex.history.map((h, i) => (
                  <span key={i}>{String(h.at).slice(0, 10)} {h.action === 'checked' ? `file checked: ${h.result}`
                    : h.action === 'changed' ? `${h.changed.join(', ').replaceAll('_', ' ')} changed${h.note ? ` (${h.note})` : ''}` : 'recorded'}</span>
                ))}
              </div>
            </div>
          )
        })}

        <Progress busy={hasher.busy} cancel={hasher.cancel} />
        {said && <p className="lt-said" role="status">{said}</p>}
        {!form && <div className="request-add"><button type="button" onClick={() => { setSaid(null); setForm({ ...EMPTY, made_on: todayInIndia() }) }}>Record a forensic file</button></div>}

        {form && (
          <form className="ex-form" aria-label="Record a forensic file" onSubmit={save}>
            <div className="fields">
              <label>Kind of file
                <select value={form.kind} onChange={set('kind')}>
                  {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
              <label>Date made<input type="date" value={form.made_on} onChange={set('made_on')} /></label>
              <label className="wide">What it is<input value={form.label} onChange={set('label')} placeholder="e.g. Accused's phone, Samsung A54" /></label>
              <label className="wide">Tool and version<input value={form.tool} onChange={set('tool')} placeholder="e.g. Cellebrite UFED 7.69, FTK Imager 4.7" /></label>
              <label className="wide ex-file">Fill the SHA-256 from the file (it stays on this computer)
                <input type="file" disabled={Boolean(hasher.busy)} onChange={fillFrom} />
              </label>
              <label className="wide">SHA-256<input value={form.sha256} onChange={set('sha256')} className="mono" placeholder="as the tool printed it" /></label>
              <label>SHA-1<input value={form.sha1} onChange={set('sha1')} className="mono" placeholder="if the tool gave it" /></label>
              <label>MD5<input value={form.md5} onChange={set('md5')} className="mono" placeholder="if the tool gave it" /></label>
              <label>File name<input value={form.file_name} onChange={set('file_name')} /></label>
              <label>Size in bytes<input value={form.size_bytes} onChange={set('size_bytes')} inputMode="numeric" className="mono" /></label>
              <label>Made by<input value={form.made_by} onChange={set('made_by')} /></label>
              <label>Held by<input value={form.holder} onChange={set('holder')} /></label>
              <label className="wide">Kept at<input value={form.stored_at} onChange={set('stored_at')} placeholder="e.g. evidence room, shelf 3" /></label>
              <label className="wide">Notes<textarea rows={2} value={form.notes} onChange={set('notes')} /></label>
            </div>
            <p className="note ex-never">Only the hashes are sent. Never type a private key or seed phrase here.</p>
            <div className="request-add">
              <button type="submit" className="ex-save" disabled={Boolean(hasher.busy)}>Add to the exhibits</button>
              <button type="button" className="quiet" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
        {error && <p className="error-line" role="alert">{error}</p>}
        <p className="note">A file&apos;s SHA-256 is worked out on this computer, a few gigabytes a minute; the file is never uploaded. Hand-overs and checks are kept as the chain of custody.</p>
      </div>
    </details>
  )
}
