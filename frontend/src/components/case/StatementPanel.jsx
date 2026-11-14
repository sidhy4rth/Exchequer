import { useEffect, useMemo, useState } from 'react'
import { fetchCaseStatements, saveStatementRows, withdrawStatementImport } from '../../api'
import { plain } from '../../text'
import {
  FIELDS, casePayments, matchRows, parseAmount, readStatement, statementRows, timeline, toSaved, WINDOW_DAYS,
} from './statement'
import WithdrawImport, { ShowWithdrawn, Withdrawn } from './WithdrawImport'
import './StatementPanel.css'

// A bank statement, or a transaction statement an exchange sent, read against the
// case (suite feature 5; backend statement_imports.py, behind the flag
// EXCHEQUER_STATEMENT_IMPORT). The file is read here, in the browser: nothing is
// sent until the officer saves the rows they ticked, and never the rest of it.

const FIELD_NAMES = {
  date: 'Date', narration: 'Narration', reference: 'Reference / UTR', debit: 'Debit', credit: 'Credit',
  amount: 'Amount (one column)', drcr: 'Dr / Cr', balance: 'Balance', counterparty: 'Counterparty',
}
export const REASON_NAMES = {
  amount_date: 'Amount and date match a payment', utr: 'Bank reference', exchange: 'Names an exchange', tx_hash: 'Hash in the trace',
}

function Saved({ item, onWithdraw }) {
  return (
    <details className={`st-saved${item.withdrawn ? ' withdrawn-import' : ''}`}>
      <summary>{plain(item.title) || item.source_label} · {item.row_count} row{item.row_count === 1 ? '' : 's'} · {item.currency} · saved {String(item.created_at).slice(0, 10)}</summary>
      <ul>
        {item.rows.map((r, i) => (
          <li key={i}>{r.date}{r.time ? ` ${r.time}` : ''} · {r.direction} {r.amount}{r.reference ? <> · <span className="mono">{plain(r.reference)}</span></> : null}
            {r.exchange ? ` · ${plain(r.exchange)}` : ''} · {r.reasons.map((x) => REASON_NAMES[x] ?? x).join(', ')}{r.narration ? <span className="note"> · {plain(r.narration)}</span> : null}</li>
        ))}
      </ul>
      <Withdrawn item={item} />
      {onWithdraw && !item.withdrawn && <WithdrawImport name="these rows" onWithdraw={onWithdraw} />}
    </details>
  )
}

export default function StatementPanel({ result }) {
  const caseId = result?.case_id
  const [info, setInfo] = useState(null)
  const [error, setError] = useState(null)
  const [source, setSource] = useState('bank')
  const [currency, setCurrency] = useState('INR')
  const [read, setRead] = useState(null) // {name, headers, records, columns} or {error}
  const [columns, setColumns] = useState(null)
  const [reported, setReported] = useState([]) // rupee payments the officer types from the complaint
  const [entry, setEntry] = useState({ amount: '', date: '' })
  const [ticked, setTicked] = useState({})
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [showWithdrawn, setShowWithdrawn] = useState(false)

  // The panel shows only once the server says the feature is on. A failed reload after
  // that says so: a short list would read as "nothing was saved".
  const load = () => caseId && fetchCaseStatements(caseId, { withdrawn: showWithdrawn }).then(setInfo)
    .catch(() => { if (info?.enabled) setError('Saved statement rows could not be loaded. Reload the page before relying on this list.') })
  useEffect(() => { load() }, [caseId, showWithdrawn]) // eslint-disable-line react-hooks/exhaustive-deps

  const parsed = useMemo(() => (read?.records && columns ? statementRows(read.records, columns) : null), [read, columns])
  const payments = useMemo(() => [...casePayments(result), ...reported], [result, reported])
  const hashes = useMemo(() => [...(result?.intake?.payments ?? []).map((p) => p.tx_hash), ...(result?.transfers ?? []).map((t) => t.hash)], [result])
  const matches = useMemo(() => (parsed ? matchRows(parsed.rows, { payments, currency, names: info?.exchange_names ?? [], hashes }) : []),
    [parsed, payments, currency, info, hashes])
  const events = useMemo(() => timeline(matches, result), [matches, result])

  if (!caseId || !info?.enabled) return null

  async function pickFile(e) {
    const file = e.target.files?.[0]
    if (!file) return
    const out = readStatement(await file.text())
    setRead({ name: file.name, ...out })
    setColumns(out.columns ?? null)
    setTicked({})
  }
  const chooseSource = (value) => {
    setSource(value)
    setCurrency(value === 'bank' ? 'INR' : String(result?.asset ?? '').toUpperCase())
  }
  function addReported() {
    const amount = parseAmount(entry.amount)
    if (!amount || amount.value <= 0 || !/^\d{4}-\d{2}-\d{2}$/.test(entry.date)) return
    setReported((r) => [...r, { amount: amount.value, currency: 'INR', date: entry.date, typed: true }])
    setEntry({ amount: '', date: '' })
  }
  const isTicked = (m) => ticked[m.row.line] ?? true
  const chosen = matches.filter(isTicked)
  // The server's own limit (rows_max), so the two never disagree.
  const most = info?.rows_max ?? Infinity
  const tooMany = chosen.length > most
  async function save() {
    setBusy(true); setError(null)
    try {
      await saveStatementRows(caseId, { source, currency, title, rows: chosen.map(toSaved) })
      setRead(null); setColumns(null); setTitle('')
      await load()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const saved = info?.imports ?? []
  const withdraw = (id) => async (reason) => { await withdrawStatementImport(caseId, id, reason); await load() }
  return (
    <details className="card sec statement-panel" open={saved.length > 0 || Boolean(error) || Boolean(read)}>
      <summary><span className="micro">Bank and exchange statements · {saved.filter((s) => !s.withdrawn).length}</span><span className="note">rows lined up with the trace</span></summary>
      <div className="body">
        {error && <p className="note st-error" role="alert">{error}</p>}
        <ShowWithdrawn count={info.withdrawn_count} shown={showWithdrawn} onChange={setShowWithdrawn} />
        {saved.map((item) => <Saved key={item.import_id} item={item} onWithdraw={info.can_withdraw ? withdraw(item.import_id) : null} />)}
        <div className="st-pick">
          <label>Statement from
            <select value={source} onChange={(e) => chooseSource(e.target.value)}>
              <option value="bank">A bank</option><option value="exchange">An exchange</option>
            </select>
          </label>
          <label>Currency<input value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} className="mono" maxLength={12} /></label>
          <label className="wide">CSV file<input type="file" accept=".csv,text/csv" onChange={pickFile} /></label>
        </div>
        <p className="note">The file is read in this browser. Nothing is sent until you save the rows you tick, and the rest of the statement never is.</p>
        {read?.error && <p className="note st-error" role="alert">{plain(read.name)}: {read.error}</p>}
        {columns && (
          <fieldset className="st-columns">
            <legend className="micro">Columns in {plain(read.name)}</legend>
            {FIELDS.map((f) => (
              <label key={f}>{FIELD_NAMES[f]}
                <select value={columns[f]} onChange={(e) => setColumns((c) => ({ ...c, [f]: Number(e.target.value) }))}>
                  <option value={-1}>(none)</option>
                  {read.headers.map((h, i) => <option key={i} value={i}>{plain(h) || `column ${i + 1}`}</option>)}
                </select>
              </label>
            ))}
          </fieldset>
        )}
        {parsed && (
          <>
            <div className="st-reported">
              <span className="micro">Payments to match ({payments.length})</span>
              <ul>{payments.map((p, i) => <li key={i}>{p.amount} {p.currency} {p.date ? `on ${p.date}` : '(time withheld from you)'}{p.typed ? ' · from the complaint' : ' · on the case'}</li>)}</ul>
              <div className="st-entry">
                <label>Rupees paid, from the complaint<input value={entry.amount} onChange={(e) => setEntry((x) => ({ ...x, amount: e.target.value }))} placeholder="e.g. 2,50,000" /></label>
                <label>On<input type="date" value={entry.date} onChange={(e) => setEntry((x) => ({ ...x, date: e.target.value }))} /></label>
                <button type="button" onClick={addReported}>Add</button>
              </div>
              <p className="note">A match is the same currency, the same amount, and a date within {WINDOW_DAYS} days. No exchange rate is used.</p>
            </div>
            <p className="note">{parsed.rows.length} rows read{parsed.skipped.length ? `, ${parsed.skipped.length} skipped (no date or amount)` : ''}; {matches.length} worth a look.</p>
            {matches.length > 0 && (
              <ul className="st-matches" aria-label="Rows worth a look">
                {matches.map((m) => (
                  <li key={m.row.line}>
                    <label>
                      <input type="checkbox" checked={isTicked(m)} onChange={(e) => setTicked((t) => ({ ...t, [m.row.line]: e.target.checked }))} />
                      <span>Line {m.row.line} · {m.row.date}{m.row.time ? ` ${m.row.time}` : ''} · {m.row.direction} {m.row.text} {currency}</span>
                    </label>
                    <span className="st-why">{m.reasons.map((x) => <span className="pill" key={x}>{REASON_NAMES[x]}{x === 'exchange' ? `: ${m.exchange}` : ''}</span>)}
                      {m.utrs.map((u) => <span className="mono note" key={u.value}>{u.kind} {u.value}</span>)}</span>
                    {m.row.narration && <span className="note">{plain(m.row.narration)}</span>}
                  </li>
                ))}
              </ul>
            )}
            {events.length > 0 && (
              <ol className="st-timeline" aria-label="Statement beside the trace">
                {events.map((e, i) => <li key={i} className={e.side}><span className="mono">{e.date}{e.time ? ` ${e.time}` : ''}</span> <span className="micro">{e.side === 'chain' ? 'On chain' : 'Statement'}</span> {plain(e.text)}</li>)}
              </ol>
            )}
            <p className="note">A row is a lead for a notice to the bank or the exchange, not a finding: only they can say whose account it is.</p>
            {tooMany && <p className="note st-error" role="alert">Tick at most {most} row{most === 1 ? '' : 's'} at a time: the server keeps the matches, not the statement. Untick {chosen.length - most}, or save in parts.</p>}
            <div className="st-save">
              <label>Name for these rows<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} placeholder="e.g. victim's statement, March" /></label>
              <button type="button" disabled={busy || chosen.length === 0 || tooMany} onClick={save}>{busy ? 'Saving…' : `Save ${chosen.length} ticked row${chosen.length === 1 ? '' : 's'} to the case`}</button>
            </div>
          </>
        )}
      </div>
    </details>
  )
}
