import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { addWalletIdentifier, fetchExportScan, recordExportScan } from '../../api'
import { findTarget } from '../../find'
import { size } from './ExhibitsPanel'
import { scanFile } from './exportScan'
import './ExportScanPanel.css'

// Scanning a phone or computer export on the Evidence tab (suite feature 2,
// slice 1). The officer picks a text export from the extraction; it is read on
// this computer (exportScan.js) and only counts reach the server, for the audit
// trail. Hidden unless the server offers it (EXCHEQUER_EXPORT_SCAN).

const CHAIN = {
  evm: 'EVM: Ethereum, BNB Chain, Polygon or Arbitrum (the address alone does not say which)',
  tron: 'Tron',
}
// 64 hex is only a shape: a transaction hash, a file's SHA-256 and a raw
// private key all look like it, so the panel says what each may be.
const HASH = {
  hex0x: '0x and 64 hex: may be an EVM transaction hash (or a Tron one written with 0x), a private key or another hash',
  hex: "64 hex: may be a Tron transaction hash, a file's SHA-256 or a private key",
}
const FIRST_ROWS = 50

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString('en-IN')} ${n === 1 ? one : many}`
const where = (f) => `${f.lines.length > 1 ? 'lines' : 'line'} ${f.lines.join(', ')}${f.count > f.lines.length ? ` (${plural(f.count, 'time')} in all)` : ''}`

/** What a seed-phrase run is shown as: its size and place, never its words. */
export function seedLine(s) {
  return `${s.words} BIP-39 words at ${s.endLine > s.line ? `lines ${s.line} to ${s.endLine}` : `line ${s.line}`}, hidden`
}

function Found({ title, rows, what, action }) {
  const [all, setAll] = useState(false)
  if (!rows.length) return null
  return <>
    <h3 className="xs-title">{title} · {rows.length}</h3>
    <div className="ev-scroll" role="region" aria-label={title} tabIndex={0}>
      <table className="ev-table xs-table">
        <caption className="visually-hidden">{title}</caption>
        <thead><tr><th scope="col">Value</th><th scope="col">What it is</th><th scope="col">Where</th><th scope="col"><span className="visually-hidden">Action</span></th></tr></thead>
        <tbody>
          {(all ? rows : rows.slice(0, FIRST_ROWS)).map((f) => (
            <tr key={f.value}>
              <td className="mono xs-value">{f.value}</td>
              <td>{what(f)}</td>
              <td className="xs-where">{where(f)}</td>
              <td>{action(f)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    {rows.length > FIRST_ROWS && <button type="button" className="quiet" aria-expanded={all} onClick={() => setAll((v) => !v)}>{all ? 'Show fewer' : `Show all ${rows.length}`}</button>}
  </>
}

const ADDED = { added: 'Added to the case', duplicate: 'Already on the case' }

/** Save one found address to the case's identifiers (identifiers.py, kind wallet): only
 * this address is sent, when the officer clicks; the audit row holds its kind, not it. */
function AddWallet({ caseId, value }) {
  const [state, setState] = useState(null) // null, 'busy', 'added', 'duplicate', or an error message
  if (ADDED[state]) return <span className="note" role="status">{ADDED[state]}</span>
  async function add() {
    setState('busy')
    try {
      const out = await addWalletIdentifier(caseId, value)
      setState(out.duplicate ? 'duplicate' : 'added')
    } catch (err) { setState(err.message || 'Could not add it.') }
  }
  return <>
    <button type="button" className="quiet" disabled={state === 'busy'} onClick={add}>
      Add as case identifier <span className="visually-hidden">{value}</span>
    </button>
    {state && state !== 'busy' && <span className="error-line" role="alert">{state}</span>}
  </>
}

export default function ExportScanPanel({ result }) {
  const caseId = result?.case_id
  const [offered, setOffered] = useState(false)
  const [busy, setBusy] = useState(null) // { name, done }
  const [found, setFound] = useState(null) // { name, ...scanFile's result }
  const [error, setError] = useState(null)
  const [unrecorded, setUnrecorded] = useState(null)
  const stop = useRef(null)

  useEffect(() => {
    setOffered(false)
    setFound(null)
    if (!caseId) return undefined
    let live = true
    fetchExportScan(caseId).then(() => { if (live) setOffered(true) }, () => {})
    return () => { live = false; stop.current?.abort() }
  }, [caseId])
  if (!offered) return null

  async function pick(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setError(null)
    setUnrecorded(null)
    setFound(null)
    stop.current = new AbortController()
    setBusy({ name: file.name, done: 0 })
    try {
      const out = await scanFile(file, { signal: stop.current.signal, onProgress: (done) => setBusy({ name: file.name, done }) })
      setFound({ name: file.name, ...out })
      recordExportScan(caseId, {
        lines: out.lines, bytes: out.bytes, addresses: out.addresses.length, txHashes: out.hashes.length, seedRuns: out.seeds.length,
      }).catch((err) => setUnrecorded(err.message))
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message)
    } finally { setBusy(null) }
  }

  return (
    <details className="card sec export-scan" open>
      <summary><span className="micro">Export scan</span><span className="note">addresses, hashes and seed phrases in a phone or computer export</span></summary>
      <div className="body">
        <p className="note">
          Pick a text export from the extraction: chats, notes or a tool's report as CSV, TSV, XML, JSON, HTML or text.
          It is read on this computer and nothing in it is sent. The audit trail records only that a scan ran and how many of each kind it found.
        </p>
        <label className="xs-file">Export file
          <input type="file" accept=".csv,.tsv,.txt,.xml,.json,.html,.htm,.log,.md,text/*,application/json,application/xml" disabled={Boolean(busy)} onChange={pick} />
        </label>
        {busy && (
          <div className="xs-progress" role="status">
            <span>Reading {busy.name} on this computer… {Math.round(busy.done * 100)}%</span>
            <progress max="1" value={busy.done} aria-label="Scan progress" />
            <button type="button" className="quiet" onClick={() => stop.current?.abort()}>Stop</button>
          </div>
        )}
        {error && <p className="error-line" role="alert">The file could not be read: {error}</p>}
        {found && <>
          <p className="xs-summary" role="status">
            {found.name}: {plural(found.lines, 'line')} read ({size(found.bytes)}) · {plural(found.addresses.length, 'address', 'addresses')} ·{' '}
            {plural(found.hashes.length, '64-hex value (may be a transaction hash)', '64-hex values (may be transaction hashes)')} · {plural(found.seeds.length, 'seed-phrase run')}
          </p>
          {found.binary && <p className="note">This file looks binary rather than text, so little in it can be read. Export the items as CSV, XML or text from the forensic tool and scan that.</p>}
          {found.dropped > 0 && <p className="note">{plural(found.dropped, 'more find')} past the first 5,000 distinct values are not listed or counted above.</p>}
          {unrecorded && <p className="note">The scan could not be recorded in the audit trail: {unrecorded}</p>}
          {found.seeds.length > 0 && (
            <div className="xs-seeds">
              <h3 className="xs-title">Possible seed phrases · {found.seeds.length}</h3>
              <ul>{found.seeds.map((s, i) => <li key={i}>{seedLine(s)}</li>)}</ul>
              <p className="note">
                A run of BIP-39 words may be a wallet's seed phrase, and whoever holds the words controls the wallet.
                Exchequer has not shown, kept or sent them. Secure the device and this export as your procedure for seized wallets requires.
              </p>
            </div>
          )}
          <Found title="Addresses" rows={found.addresses} what={(f) => CHAIN[f.kind]}
            action={(f) => <span className="xs-actions">
              <Link to={findTarget(f.value)}>Trace <span className="visually-hidden">{f.value}</span></Link>
              <AddWallet key={`${found.name}-${f.value}`} caseId={caseId} value={f.value} />
            </span>} />
          <Found title="64-hex values" rows={found.hashes} what={(f) => HASH[f.kind]}
            action={(f) => <Link to={findTarget(f.value)}>Trace from this payment <span className="visually-hidden">{f.value}</span></Link>} />
          {!found.addresses.length && !found.hashes.length && !found.seeds.length && <p className="note">Nothing of these kinds was found in this file.</p>}
        </>}
      </div>
    </details>
  )
}
