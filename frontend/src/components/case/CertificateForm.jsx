import { useState } from 'react'
import { draftCertificate, draftReportCertificate } from '../../api'
import { plain } from '../../text'
import { middle } from './format'
import './CertificateForm.css'

// A draft of the certificate in the Bharatiya Sakshya Adhiniyam's Schedule
// (s.63(4)(c)) for some of the case's exhibits, or for Exchequer's own report of
// the case (backend certificates.py). For the report the officer picks the file
// they will produce: the server checks it is a genuine report of this case and
// states the SHA-256 of exactly that file. The officer types the source device
// for Part A; Part B is the expert's own statement and stays blank. The PDF is a
// draft to check and sign: what is typed here goes into it and is kept nowhere.

// The Schedule's own list of devices and of how the device is held, in its order.
export const DEVICES = ['Computer / Storage Media', 'DVR', 'Mobile', 'Flash Drive', 'CD/DVD', 'Server', 'Cloud', 'Other']
export const CONTROL = ['Owned', 'Maintained', 'Managed', 'Operated']
const EMPTY = { mode: 'exhibits', ids: [], file: null, device: '', device_other: '', make_model: '', color: '', serial: '', device_id: '', other_info: '', control: [] }

function save(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const REPORT_MAX = 2_000_000 // as the server: the largest real reports are about 200 KB

async function asBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let text = ''
  for (let at = 0; at < bytes.length; at += 0x8000) text += String.fromCharCode(...bytes.subarray(at, at + 0x8000))
  return btoa(text)
}

const toggle = (list, item) => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item])

export default function CertificateForm({ caseId, exhibits }) {
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [said, setSaid] = useState(null)
  const files = exhibits ?? []

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
  async function download(e) {
    e.preventDefault()
    setError(null)
    setSaid(null)
    setBusy(true)
    const { mode, ids, file, ...rest } = form
    const device = { ...rest, device_other: rest.device === 'Other' ? rest.device_other : '' }
    try {
      if (mode === 'report') {
        if (file.size > REPORT_MAX) throw new Error('That file is larger than any Exchequer report.')
        const blob = await draftReportCertificate(caseId, { report_b64: await asBase64(file), file_name: file.name, ...device })
        save(blob, `exchequer-${caseId.slice(0, 8)}-s63-certificate-report-draft.pdf`)
        setSaid(`Drafted for the report ${file.name}: produce exactly that file with it, and check every value in bold before anyone signs.`)
      } else {
        const blob = await draftCertificate(caseId, { exhibit_ids: ids, ...device })
        save(blob, `exchequer-${caseId.slice(0, 8)}-s63-certificate-draft.pdf`)
        setSaid(`Drafted for ${ids.length} exhibit${ids.length === 1 ? '' : 's'}: check every value in bold before anyone signs.`)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!form) {
    return (
      <div className="request-add cert-open">
        <button type="button" onClick={() => setForm({ ...EMPTY, mode: files.length ? 'exhibits' : 'report' })}>Draft the s.63(4) certificate</button>
      </div>
    )
  }
  return (
    <form className="cert-form" aria-label="Draft the s.63(4) certificate" onSubmit={download}>
      <fieldset>
        <legend>What the certificate covers</legend>
        <div className="cert-row">
          <label className="cert-check">
            <input type="radio" name="cert-mode" checked={form.mode === 'exhibits'} disabled={!files.length}
              onChange={() => setForm((f) => ({ ...f, mode: 'exhibits' }))} />
            Forensic files from the register
          </label>
          <label className="cert-check">
            <input type="radio" name="cert-mode" checked={form.mode === 'report'} onChange={() => setForm((f) => ({ ...f, mode: 'report' }))} />
            Exchequer&apos;s report of this case
          </label>
        </div>
      </fieldset>
      {form.mode === 'report' ? (
        <fieldset>
          <legend>The report</legend>
          <label className="cert-file">The report file you will produce (PDF or text, exactly as downloaded)
            <input type="file" accept=".pdf,.txt,application/pdf,text/plain" onChange={(e) => setForm((f) => ({ ...f, file: e.target.files?.[0] ?? null }))} />
          </label>
          <p className="note">It is checked as Verify a report checks it, and must be a genuine, unchanged report of this case. The certificate states the SHA-256 of exactly this file.</p>
        </fieldset>
      ) : (
      <fieldset>
        <legend>Exhibits on this certificate</legend>
        {files.map((ex) => (
          <label key={ex.exhibit_id} className="cert-check">
            <input type="checkbox" checked={form.ids.includes(ex.exhibit_id)}
              onChange={() => setForm((f) => ({ ...f, ids: toggle(f.ids, ex.exhibit_id) }))} />
            <span>{plain(ex.label)} <span className="note">· {ex.kind_label}{ex.sha256 ? ` · ${middle(ex.sha256)}` : ''}</span></span>
          </label>
        ))}
      </fieldset>
      )}
      <fieldset>
        <legend>The source device (Part A)</legend>
        <div className="cert-fields">
          <label>Kind of device
            <select value={form.device} onChange={set('device')}>
              <option value="">Not chosen</option>
              {DEVICES.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          {form.device === 'Other' && <label>Other kind of device<input value={form.device_other} onChange={set('device_other')} maxLength={120} /></label>}
          <label>Make and model<input value={form.make_model} onChange={set('make_model')} maxLength={120} /></label>
          <label>Colour<input value={form.color} onChange={set('color')} maxLength={40} /></label>
          <label>Serial number<input value={form.serial} onChange={set('serial')} maxLength={80} className="mono" /></label>
          <label>IMEI, UIN, UID, MAC or cloud ID<input value={form.device_id} onChange={set('device_id')} maxLength={120} className="mono" /></label>
          <label className="wide">Anything else about the device<input value={form.other_info} onChange={set('other_info')} maxLength={300} /></label>
        </div>
      </fieldset>
      <fieldset>
        <legend>The device is, by me</legend>
        <div className="cert-row">
          {CONTROL.map((c) => (
            <label key={c} className="cert-check">
              <input type="checkbox" checked={form.control.includes(c)} onChange={() => setForm((f) => ({ ...f, control: toggle(f.control, c) }))} />
              {c}
            </label>
          ))}
        </div>
      </fieldset>
      <p className="note">Part B is left blank for the expert, who fills it from their own check. Names, the date, time and place are written by hand when signing. What you type here goes into the PDF and is kept nowhere.</p>
      <div className="request-add">
        <button type="submit" className="ex-save" disabled={busy || (form.mode === 'report' ? !form.file : form.ids.length === 0)}>Download the draft (PDF)</button>
        <button type="button" className="quiet" onClick={() => { setForm(null); setError(null) }}>Close</button>
      </div>
      {said && <p className="lt-said" role="status">{said}</p>}
      {error && <p className="error-line" role="alert">{error}</p>}
    </form>
  )
}
