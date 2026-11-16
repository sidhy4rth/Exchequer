import { useEffect, useState } from 'react'
import { fetchCustodyBalance, runCustodyBalance } from '../../api'
import { plain } from '../../text'
import { middle } from './format'
import { money } from './AssetsPanel'
import './CustodyBalance.css'

// Custody balance check (backend custody_balance.py; suite feature 9, part 2): each custody
// address's balance as the chain's provider gave it, beside what the asset register records
// as held there. Every result is said in words, never by colour alone. Hidden unless the
// server's EXCHEQUER_CUSTODY_BALANCE_CHECK flag is on. The button shows only when the server
// says this caller may run a check (can_check; a demo caller gets its note instead).

export const VERDICT = { match: 'Matches the register', mismatch: 'Mismatch', unchecked: 'Not checked' }
const TONE = { match: 'green', mismatch: 'red' }

/** "2 match · 1 mismatch · 1 not checked", leaving out the zeros. */
export function tally(counts = {}) {
  const parts = [[counts.match, 'match'], [counts.mismatch, counts.mismatch === 1 ? 'mismatch' : 'mismatches'], [counts.unchecked, 'not checked']]
  return parts.filter(([n]) => n).map(([n, word]) => `${n} ${word}`).join(' · ') || 'nothing to check'
}

export default function CustodyBalance({ result }) {
  const caseId = result?.case_id
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { if (caseId) fetchCustodyBalance(caseId).then(setData).catch(() => {}) }, [caseId])
  if (!caseId || !data?.enabled) return null

  async function check() {
    setBusy(true)
    setError(null)
    try { setData({ ...data, check: await runCustodyBalance(caseId) }) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const c = data.check

  return (
    <details className="card sec custody-balance" open={Boolean(c?.counts?.mismatch)}>
      <summary>
        <span className="micro">Custody balances · {c ? tally(c.counts) : 'not checked yet'}</span>
        <span className="note">each custody address read on chain against the register</span>
      </summary>
      <div className="body requests-panel">
        {c && <p className="note">Read {String(c.checked_at).replace('T', ' ').replace('Z', ' UTC')}. A balance is a moment: read it again before relying on it.</p>}
        {c?.results.map((r, i) => (
          <div className={`cb-row ${r.status}`} key={i} role="group" aria-label={`${r.asset} at ${r.address || 'no address'}: ${VERDICT[r.status] ?? r.status}`}>
            <div className="top">
              <span>{r.address ? <><span className="mono" title={r.address}>{middle(r.address)}</span> <span className="note">· {plain(r.chain_name)}</span></> : <span className="note">no custody address</span>}</span>
              <span className={`pill ${TONE[r.status] ?? ''}`}>{VERDICT[r.status] ?? r.status}</span>
            </div>
            <dl className="cb-facts">
              <dt>Register</dt><dd className="mono">{money(r.register_amount, r.asset)}</dd>
              <dt>On chain</dt><dd className="mono">{r.chain_amount != null ? money(r.chain_amount, r.asset) : 'not read'}</dd>
            </dl>
            <p className="note">{plain(r.reason)}</p>
            {r.evidence?.map((e, j) => (
              <p className="cb-evidence" key={j}>{e.provider} · {e.retrieved_at} · SHA-256 <span className="mono">{e.sha256}</span>{e.from_cache ? ' (from cache)' : ''}</p>
            ))}
          </div>
        ))}
        {data.can_check
          ? <div className="request-add">
              <button type="button" disabled={busy} onClick={check}>{busy ? 'Reading the chain…' : 'Check balances on chain now'}</button>
            </div>
          : data.check_note && <p className="note">{plain(data.check_note)}</p>}
        {error && <p className="error-line" role="alert">{error}</p>}
        <p className="note">Reads count against the deployment&apos;s daily provider allowance. Only held custody rows are counted.</p>
      </div>
    </details>
  )
}
