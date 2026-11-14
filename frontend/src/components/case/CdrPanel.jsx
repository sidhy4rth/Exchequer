import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { checkCdrNumbers, fetchCaseCdr, fetchCaseIdentifiers, saveCdrSummary } from '../../api'
import { plain } from '../../text'
import { CDR_FIELDS, analyse, casePhones, cdrEvents, contactRow, imeiRow, readCdr, subjectRow, topContacts } from './cdr'
import './CdrPanel.css'

// A call detail record read against the case (suite feature 5; backend cdr_imports.py,
// behind the flag EXCHEQUER_CDR_IMPORT). The file is read here, in the browser: nothing
// is sent until the officer checks the numbers they choose or saves the summary, and the
// CDR's rows never are.

const FIELD_NAMES = {
  a: 'A party', b: 'B party', date: 'Date', time: 'Time', duration: 'Duration', type: 'Call type (MO / MT / SMS)',
  imei: 'IMEI', imsi: 'IMSI', firstCell: 'First cell ID', lastCell: 'Last cell ID', location: 'Tower location',
}
const KIND_NAMES = { subject: "The CDR's own number", number: 'Number', imei: 'Handset (IMEI)' }
const TOP = 20
const mmss = (s) => `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

function Saved({ item }) {
  return (
    <details className="cdr-saved">
      <summary>{plain(item.title) || 'CDR summary'} · {plural(item.row_count, 'row')} · saved {String(item.created_at).slice(0, 10)}</summary>
      <ul>
        {item.rows.map((r, i) => (
          <li key={i}>{KIND_NAMES[r.kind] ?? r.kind} <span className="mono">{plain(r.value)}</span> · {r.kind === 'imei' ? plural(r.events, 'event') : `${plural(r.calls, 'call')}, ${r.sms} SMS, ${mmss(r.seconds)}`} · {r.first} to {r.last}{r.reasons?.length ? ` · ${r.reasons.join(', ')}` : ''}</li>
        ))}
      </ul>
    </details>
  )
}

function Elsewhere({ found }) {
  if (!found) return null
  if (!found.also_in.length) return <span className="note">not on your other cases</span>
  return <span>on {found.also_in.map((o) => <Link key={o.case_id} to={`/case/${encodeURIComponent(o.case_id)}?tab=evidence`} className="quiet-link mono">case {o.case_id.slice(0, 8)}</Link>)}</span>
}

export default function CdrPanel({ result }) {
  const caseId = result?.case_id
  const [info, setInfo] = useState(null)
  const [phones, setPhones] = useState(new Set())
  const [error, setError] = useState(null)
  const [read, setRead] = useState(null) // {name, headers, records, columns} or {name, error}
  const [columns, setColumns] = useState(null)
  const [order, setOrder] = useState('count')
  const [keep, setKeep] = useState({}) // number or IMEI -> true
  const [toCheck, setToCheck] = useState({}) // number -> true
  const [checked, setChecked] = useState({}) // number -> {on_this_case, also_in}
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => caseId && fetchCaseCdr(caseId).then((got) => {
    setInfo(got)
    if (got.enabled) fetchCaseIdentifiers(caseId).then((ids) => setPhones(casePhones(ids.identifiers))).catch(() => {})
  }).catch(() => { if (info?.enabled) setError('Saved CDR summaries could not be loaded. Reload the page before relying on this list.') })
  useEffect(() => { load() }, [caseId]) // eslint-disable-line react-hooks/exhaustive-deps

  const parsed = useMemo(() => (read?.records && columns ? cdrEvents(read.records, columns) : null), [read, columns])
  const found = useMemo(() => (parsed?.events.length ? analyse(parsed.events) : null), [parsed])
  const top = useMemo(() => (found ? topContacts(found.contacts, order, TOP) : []), [found, order])

  if (!caseId || !info?.enabled) return null

  async function pickFile(e) {
    const file = e.target.files?.[0]
    if (!file) return
    const out = readCdr(await file.text())
    setRead({ name: file.name, ...out })
    setColumns(out.columns ?? null)
    setKeep({}); setToCheck({}); setChecked({}); setError(null)
  }
  const chosen = Object.keys(toCheck).filter((n) => toCheck[n])
  const most = info.check_max ?? Infinity
  async function check() {
    setBusy(true); setError(null)
    try {
      const out = await checkCdrNumbers(caseId, chosen)
      setChecked((c) => ({ ...c, ...Object.fromEntries(chosen.map((n, i) => [n, out.results[i]])) }))
      setToCheck({})
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const reasons = (n, base) => [...base, ...(phones.has(n) ? ['case_identifier'] : []), ...(checked[n]?.also_in.length ? ['other_case'] : [])]
  const rows = found ? [
    subjectRow(found, reasons(found.subject, [])),
    ...found.contacts.filter((c) => keep[c.number]).map((c) => contactRow(c, reasons(c.number, ['top_contact']))),
    ...found.imeis.filter((u) => keep[u.value]).map(imeiRow),
  ] : []
  const rowsMax = info.rows_max ?? Infinity
  async function save() {
    setBusy(true); setError(null)
    try {
      await saveCdrSummary(caseId, { title, rows })
      setRead(null); setColumns(null); setTitle('')
      await load()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const tick = (set, key) => (e) => set((t) => ({ ...t, [key]: e.target.checked }))

  const saved = info.imports ?? []
  return (
    <details className="card sec cdr-panel" open={saved.length > 0 || Boolean(error) || Boolean(read)}>
      <summary><span className="micro">Call detail records · {saved.length}</span><span className="note">contacts and handsets, read in this browser</span></summary>
      <div className="body">
        {error && <p className="note cdr-error" role="alert">{error}</p>}
        {saved.map((item) => <Saved key={item.import_id} item={item} />)}
        <label>CDR file (CSV; save an XLSX as CSV first)<input type="file" accept=".csv,text/csv" onChange={pickFile} /></label>
        <p className="note">The file is read in this browser. Nothing is sent until you check the numbers you choose or save the summary, and the CDR&apos;s rows never are.</p>
        {read?.error && <p className="note cdr-error" role="alert">{plain(read.name)}: {read.error}</p>}
        {columns && (
          <fieldset className="cdr-columns">
            <legend className="micro">Columns in {plain(read.name)}</legend>
            {CDR_FIELDS.map((f) => (
              <label key={f}>{FIELD_NAMES[f]}
                <select value={columns[f]} onChange={(e) => setColumns((c) => ({ ...c, [f]: Number(e.target.value) }))}>
                  <option value={-1}>(none)</option>
                  {read.headers.map((h, i) => <option key={i} value={i}>{plain(h) || `column ${i + 1}`}</option>)}
                </select>
              </label>
            ))}
          </fieldset>
        )}
        {parsed && !found && <p className="note cdr-error" role="alert">No row with a date and a number could be read. Check the columns.</p>}
        {found && (
          <>
            <p className="note">{plural(found.totals.events, 'event')} read{parsed.skipped.length ? `, ${parsed.skipped.length} skipped (no date or number)` : ''}: {plural(found.totals.calls, 'call')}, {found.totals.sms} SMS, {mmss(found.totals.seconds)} of calls, {found.totals.first.slice(0, 10)} to {found.totals.last.slice(0, 10)}.</p>
            <p>The CDR&apos;s own number, as it is on the most rows: <span className="mono">{plain(found.subject)}</span>
              {phones.has(found.subject) && <span className="pill">On this case&apos;s phone identifiers</span>}</p>
            <div className="cdr-order">
              <label>Top {TOP} contacts by
                <select value={order} onChange={(e) => setOrder(e.target.value)}>
                  <option value="count">Calls and SMS</option><option value="seconds">Call time</option>
                </select>
              </label>
            </div>
            <table className="cdr-contacts" aria-label="Top contacts">
              <thead><tr><th>Number</th><th>Calls</th><th>SMS</th><th>Out / in</th><th>Call time</th><th>First</th><th>Last</th><th>On cases</th><th>Check</th><th>Keep</th></tr></thead>
              <tbody>
                {top.map((c) => (
                  <tr key={c.number}>
                    <td className="mono">{plain(c.number)}</td><td>{c.calls}</td><td>{c.sms}</td><td>{c.out} / {c.in}</td><td>{mmss(c.seconds)}</td>
                    <td className="mono">{c.first}</td><td className="mono">{c.last}</td>
                    <td>{phones.has(c.number) && <span className="pill">This case</span>} <Elsewhere found={checked[c.number]} /></td>
                    <td>{c.checkable && <input type="checkbox" aria-label={`Check ${c.number}`} checked={Boolean(toCheck[c.number])} onChange={tick(setToCheck, c.number)} />}</td>
                    <td><input type="checkbox" aria-label={`Keep ${c.number}`} checked={Boolean(keep[c.number])} onChange={tick(setKeep, c.number)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="cdr-check">
              <button type="button" disabled={busy || chosen.length === 0 || chosen.length > most} onClick={check}>Check {plural(chosen.length, 'chosen number')} against your other cases</button>
              <span className="note">Only the numbers you tick are sent, and only cases you can already read are searched.</span>
            </div>
            <div className="cdr-handsets">
              <span className="micro">Handsets (IMEI) · changed {plural(found.handsetChanges, 'time')}</span>
              <ul>{found.imeis.map((u) => (
                <li key={u.value}><label><input type="checkbox" aria-label={`Keep IMEI ${u.value}`} checked={Boolean(keep[u.value])} onChange={tick(setKeep, u.value)} />
                  <span className="mono">{u.value}</span> · {plural(u.events, 'event')} · {u.first} to {u.last}</label></li>))}
              </ul>
              {found.imsis.length > 0 && <p className="note">{plural(found.imsis.length, 'SIM (IMSI)', 'SIMs (IMSI)')}, changed {plural(found.simChanges, 'time')}.</p>}
              {found.cells.length > 0 && <p className="note">Most used first cells: {found.cells.slice(0, 5).map((c) => `${c.cell}${c.location ? ` (${c.location})` : ''} ×${c.events}`).join(', ')}.</p>}
            </div>
            <p className="note">A number is a lead, not a person: subscriber details come from the operator under a lawful request.</p>
            {rows.length > rowsMax && <p className="note cdr-error" role="alert">Keep at most {rowsMax} rows at a time.</p>}
            <div className="cdr-save">
              <label>Name for this summary<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} placeholder="e.g. CDR from the operator, March" /></label>
              <button type="button" disabled={busy || rows.length > rowsMax} onClick={save}>{busy ? 'Saving…' : `Save the summary: its own number, ${plural(rows.length - 1, 'kept row')}`}</button>
            </div>
          </>
        )}
      </div>
    </details>
  )
}
