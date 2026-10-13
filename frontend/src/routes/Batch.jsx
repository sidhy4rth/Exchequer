import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchBatch } from '../api'
import Mark from '../components/Mark'
import ThemeToggle from '../components/ThemeToggle'

// One batch: progress while it runs, then the exchanges its complaints reached
// and the wallets two or more of them share.

const STATUS = { pending: 'waiting', running: 'tracing…', done: 'done', failed: 'failed', interrupted: 'interrupted' }
const short = (a) => (a && a.length > 22 ? `${a.slice(0, 10)}…${a.slice(-8)}` : a)

export default function Batch() {
  const { batchId } = useParams()
  const [batch, setBatch] = useState(null)
  const [error, setError] = useState(null)
  const [allShared, setAllShared] = useState(false)

  useEffect(() => {
    let live = true
    let timer
    const load = () => fetchBatch(batchId)
      .then((b) => { if (!live) return; setBatch(b); if (b.status === 'running') timer = setTimeout(load, 3000) })
      .catch((e) => live && setError(e.message))
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
        {batch && (
          <>
            <span className="micro">Batch · {batch.status === 'running' ? `${batch.done + batch.failed} of ${batch.total} traced` : batch.status}</span>
            <h1>{batch.name || 'Untitled batch'}</h1>
            {batch.status === 'running' && <div className="loading"><div className="bar determinate"><span style={{ width: `${Math.round(100 * (batch.done + batch.failed) / batch.total)}%` }} /></div></div>}
            <div className="batch-grid">
              <div className="card">
                <div className="head"><span className="micro">Complaints · {batch.total}</span><span className="note">{batch.done} traced{batch.failed ? ` · ${batch.failed} failed` : ''}{batch.interrupted ? ` · ${batch.interrupted} interrupted by a restart` : ''}</span></div>
                <table className="cases-table">
                  <thead><tr><th>#</th><th>Reference</th><th>Reported address</th><th>Chain</th><th>Result</th><th style={{ textAlign: 'right' }}>Confidence</th></tr></thead>
                  <tbody>
                    {batch.rows.map((r) => (
                      <tr key={r.row} className={r.case_id ? 'row' : ''}>
                        <td className="num">{r.row}</td>
                        <td>{r.reference || '—'}</td>
                        <td className="mono">{r.case_id ? <Link to={`/case/${r.case_id}`}>{short(r.address)}</Link> : short(r.address)}</td>
                        <td>{r.chain} · {r.asset}</td>
                        <td className={r.exchange ? '' : 'none'}>{r.status === 'done' ? (r.exchange ?? 'no match') : <span title={r.error ?? ''}>{STATUS[r.status] ?? r.status}{r.error ? `: ${r.error}` : ''}</span>}</td>
                        <td className="num">{r.confidence == null ? '' : r.confidence.toFixed(2)}</td>
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
