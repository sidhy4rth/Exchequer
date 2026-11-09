import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchBatch } from '../api'
import { bandLabel, bandOf } from '../components/confidence'
import Mark from '../components/Mark'
import ThemeToggle from '../components/ThemeToggle'

// One batch: progress while it runs, then the exchanges its complaints reached
// and the wallets two or more of them share.

const STATUS = { pending: 'waiting', running: 'tracing…', done: 'done', failed: 'failed', interrupted: 'interrupted', same: 'same as an earlier row' }
const short = (a) => (a && a.length > 22 ? `${a.slice(0, 10)}…${a.slice(-8)}` : a)
// Polls (3 s apart) in which no row finished before the page stops asking:
// about 10 minutes. A row traces for 5 minutes at most, so a batch that quiet
// has stopped moving, and an open tab must not poll it for ever.
export const STALL_POLLS = 200
const rowStatus = (r) => (r.status === 'same' && r.same_as ? `same as row ${r.same_as}` : (STATUS[r.status] ?? r.status))

export default function Batch() {
  const { batchId } = useParams()
  const [batch, setBatch] = useState(null)
  const [error, setError] = useState(null)
  const [allShared, setAllShared] = useState(false)
  const [stalled, setStalled] = useState(false)

  useEffect(() => {
    let live = true
    let timer
    let finishedBefore = -1
    let quiet = 0
    const load = () => fetchBatch(batchId)
      .then((b) => {
        if (!live) return
        setBatch(b)
        if (b.status !== 'running') return
        const finished = b.done + b.failed + (b.interrupted ?? 0)
        quiet = finished === finishedBefore ? quiet + 1 : 0
        finishedBefore = finished
        if (quiet >= STALL_POLLS) { setStalled(true); return }
        timer = setTimeout(load, 3000)
      })
      .catch((e) => live && setError(e.message))
    setStalled(false)
    load()
    return () => { live = false; clearTimeout(timer) }
  }, [batchId])

  return (
    <div className="citizen">
      <header className="citizen-top">
        <Link to="/" className="brand" style={{ textDecoration: 'none' }}><Mark size={20} /><span>Exchequer</span></Link>
        <span className="citizen-actions"><Link to="/" className="quiet-link">Back to the console</Link><ThemeToggle /></span>
      </header>
      <main className="batch-body">
        {error && <div className="banner error">{error}</div>}
        {stalled && <div className="banner">No row has finished for 10 minutes, so this page stopped checking. Reload to check again.</div>}
        {batch && (
          <>
            <span className="micro">Batch · {batch.status === 'running' ? `${batch.done + batch.failed} of ${batch.total} traced` : batch.status}</span>
            <h1>{batch.name || 'Untitled batch'}</h1>
            {batch.status === 'running' && <div className="loading"><div className="bar determinate"><span style={{ width: `${Math.round(100 * (batch.done + batch.failed) / batch.total)}%` }} /></div></div>}
            <div className="batch-grid">
              <div className="card">
                <div className="head"><span className="micro">Complaints · {batch.total}</span><span className="note">{batch.done} traced{batch.failed ? ` · ${batch.failed} failed` : ''}{batch.interrupted ? ` · ${batch.interrupted} interrupted by a restart` : ''}</span></div>
                <table className="cases-table" tabIndex={0} aria-label="Complaints in this batch">
                  <thead><tr><th>#</th><th>Reference</th><th>Reported address</th><th>Chain</th><th>Result</th><th style={{ textAlign: 'right' }}>Confidence</th></tr></thead>
                  <tbody>
                    {batch.rows.map((r) => (
                      <tr key={r.row} className={r.case_id ? 'row' : ''}>
                        <td className="num">{r.row}</td>
                        <td>{r.reference || '—'}</td>
                        <td className="mono">{r.case_id ? <Link to={`/case/${r.case_id}`}>{short(r.address)}</Link> : short(r.address)}</td>
                        <td>{r.chain} · {r.asset}</td>
                        <td className={r.exchange ? '' : 'none'}>{r.status === 'done' ? (r.exchange ?? 'no match') : <span title={r.error ?? ''}>{rowStatus(r)}{r.error ? `: ${r.error}` : ''}</span>}{r.same_as && r.status !== 'same' ? <span className="note"> · same as row {r.same_as}</span> : null}</td>
                        <td>{r.confidence == null ? '' : bandLabel(bandOf(r.confidence))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="rail">
                <div className="card">
                  <div className="head"><span className="micro">Exchanges reached</span></div>
                  <div className="body">
                    {(batch.exchanges ?? []).length === 0 ? <p className="note">None yet.</p>
                      : batch.exchanges.map(([name, n]) => <div className="kv" key={name}><span className="k">{name}</span><span className="v">{n} complaint{n === 1 ? '' : 's'}</span></div>)}
                  </div>
                </div>
                <div className="card">
                  <div className="head"><span className="micro">Shared wallets · {(batch.shared_wallets ?? []).length}</span><span className="note">same operation?</span></div>
                  <div className="body">
                    {(batch.shared_wallets ?? []).length === 0
                      ? <p className="note">No unlabelled wallet is shared by two of these complaints{batch.status === 'running' ? ' so far' : ''}.</p>
                      : batch.shared_wallets.slice(0, allShared ? undefined : 10).map((w) => (
                        <div className="rule-block" key={w.address}>
                          <div className="top"><span className="mono">{short(w.address)}</span><span className="st">rows {w.rows.join(', ')}</span></div>
                          <div className="note">{w.inferred_exchange ? `probable ${w.inferred_exchange} deposit · ` : ''}{w.risk_category ? `${w.risk_category} · ` : ''}{w.references.length ? w.references.join(', ') : `${w.rows.length} complaints`}</div>
                        </div>
                      ))}
                    {!allShared && (batch.shared_wallets ?? []).length > 10 && (
                      <button className="quiet link-like" onClick={() => setAllShared(true)}>Show all {batch.shared_wallets.length}</button>
                    )}
                    <p className="note">An exchange two complaints both reached is a shared bank, not a shared offender, so exchange wallets never count here.</p>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  )
}
