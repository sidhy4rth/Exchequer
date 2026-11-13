import { useState } from 'react'
import { draftCertificate } from '../../api'
import { plain } from '../../text'
import { middle } from './format'
import './CertificateForm.css'

// A draft of the certificate in the Bharatiya Sakshya Adhiniyam's Schedule
// (s.63(4)(c)) for some of the case's exhibits (backend certificates.py). The
// officer picks the exhibits and types the source device for Part A; Part B is
// the expert's own statement and stays blank. The PDF is a draft to check and
// sign: what is typed here goes into it and is kept nowhere.

// The Schedule's own list of devices and of how the device is held, in its order.
export const DEVICES = ['Computer / Storage Media', 'DVR', 'Mobile', 'Flash Drive', 'CD/DVD', 'Server', 'Cloud', 'Other']
export const CONTROL = ['Owned', 'Maintained', 'Managed', 'Operated']
const EMPTY = { ids: [], device: '', device_other: '', make_model: '', color: '', serial: '', device_id: '', other_info: '', control: [] }

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

const toggle = (list, item) => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item])

export default function CertificateForm({ caseId, exhibits }) {
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [said, setSaid] = useState(null)
  if (!exhibits?.length) return null

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
  async function download(e) {
    e.preventDefault()
    setError(null)
    setSaid(null)
    setBusy(true)
    const { ids, ...device } = form
    try {
      const blob = await draftCertificate(caseId, { exhibit_ids: ids, ...device, device_other: device.device === 'Other' ? device.device_other : '' })
      save(blob, `exchequer-${caseId.slice(0, 8)}-s63-certificate-draft.pdf`)
      setSaid(`Drafted for ${ids.length} exhibit${ids.length === 1 ? '' : 's'}: check every value in bold before anyone signs.`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!form) {
    return (
      <div className="request-add cert-open">
        <button type="button" onClick={() => setForm(EMPTY)}>Draft the s.63(4) certificate</button>
      </div>
    )
  }
  return (
    <form className="cert-form" aria-label="Draft the s.63(4) certificate" onSubmit={download}>
      <fieldset>
        <legend>Exhibits on this certificate</legend>
        {exhibits.map((ex) => (
          <label key={ex.exhibit_id} className="cert-check">
            <input type="checkbox" checked={form.ids.includes(ex.exhibit_id)}
              onChange={() => setForm((f) => ({ ...f, ids: toggle(f.ids, ex.exhibit_id) }))} />
            <span>{plain(ex.label)} <span className="note">· {ex.kind_label}{ex.sha256 ? ` · ${middle(ex.sha256)}` : ''}</span></span>
          </label>
        ))}
      </fieldset>
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
        <button type="submit" className="ex-save" disabled={busy || form.ids.length === 0}>Download the draft (PDF)</button>
        <button type="button" className="quiet" onClick={() => { setForm(null); setError(null) }}>Close</button>
      </div>
      {said && <p className="lt-said" role="status">{said}</p>}
      {error && <p className="error-line" role="alert">{error}</p>}
    </form>
  )
}
