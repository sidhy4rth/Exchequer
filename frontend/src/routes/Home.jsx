import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ThemeToggle from '../components/ThemeToggle'
import Mark from '../components/Mark'
import { fetchAccess, fetchCases, fetchChains, fetchExchanges, fetchRiskLabels } from '../api'
import Showroom from '../components/Showroom'
import TraceForm from '../components/TraceForm'
import Watchlist from '../components/Watchlist'
import OpenRequests from '../components/OpenRequests'
import BulkIntake from '../components/BulkIntake'
import { demoCode } from '../demoCode'

const middle = (a, head = 10, tail = 8) => (a && a.length > head + tail + 1 ? `${a.slice(0, head)}…${a.slice(-tail)}` : a)

export default function Home() {
  const navigate = useNavigate()
  const [health, setHealth] = useState(null)
  const [cases, setCases] = useState([])
  const [coverage, setCoverage] = useState({})
  // Whether this site asks for a demo code (backend/app/access.py). Until it
  // answers, or if it cannot, the form shows: the backend refuses a trace
  // without the code either way, so the worst case is its message.
  const [access, setAccess] = useState(null)
  const [unlocked, setUnlocked] = useState(() => Boolean(demoCode()))

  // Every path out of this page leads to a trace; fetch that page's code
  // (the graph layout is most of it) before the button is pressed.
  useEffect(() => { import('./TraceView') }, [])

  useEffect(() => {
    fetchChains()
      .then((h) => {
        setHealth(h)
        // Coverage per chain: what the label files and screening lists hold.
        Object.keys(h.chains ?? {}).forEach((key) => {
          Promise.all([fetchExchanges(key), fetchRiskLabels(key)])
            .then(([ex, risk]) => setCoverage((c) => ({ ...c, [key]: { exchanges: ex, risk } })))
            .catch(() => {})
        })
      })
      .catch(() => setHealth({ status: 'down' }))
    fetchCases(20).then((d) => setCases(d.cases)).catch(() => {})
    fetchAccess().then(setAccess).catch(() => setAccess({ demo_code_required: false }))
  }, [])

  const chains = health?.chains ? Object.values(health.chains) : []
  const backendDown = health?.status === 'down'
  // A public site without the code: recorded demos only, nothing that would
  // spend the provider quota or keep running (batches, watches).
  const locked = Boolean(access?.demo_code_required) && !unlocked

  // The exchanges' own wallets and their customers' deposit addresses, apart:
  // one total read as that many exchange wallets (R14). Both from /chains.
  const totalWallets = chains.reduce((sum, c) => sum + (c.exchange_wallets || 0), 0)
  const totalDeposits = chains.reduce((sum, c) => sum + (c.deposit_addresses || 0), 0)

  return (
    <div className="home">
      <header className="topbar">
        <Link to="/" className="brand"><Mark size={18} />Exchequer<small>Cryptocurrency fraud tracing</small></Link>
        <span className="sysline mono">
          {backendDown ? <><span className="dot down" />BACKEND UNREACHABLE</>
            : health ? <><span className="dot live" />SYSTEM OPERATIONAL · {chains.filter((c) => c.ready).length} CHAINS · SOURCE: LIVE BLOCKCHAIN APIS</>
            : <><span className="dot" />CONNECTING</>}
        </span>
        <span className="grow" />
        <ThemeToggle />
      </header>

      <div className="home-body">
        <section className="intake">
          {locked ? <Showroom onUnlock={() => setUnlocked(true)} /> : <TraceForm health={health} />}

          <div className="card">
            <div className="head"><span className="micro">Coverage</span><span className="note">{health ? `${totalWallets} exchange wallets · ${totalDeposits} deposit addresses` : ''}</span></div>
            <div className="body status">
              {!health && <span className="note">Connecting…</span>}
              {backendDown && <div className="line"><span className="dot down" /><span>Backend unreachable</span><span /></div>}
              {chains.map((c) => (
                <div className="line" key={c.key}>
                  <span className={`dot ${c.ready ? 'live' : 'down'}`} />
                  <span>{c.name}</span>
                  <span className="n">{c.exchange_wallets} wallets{c.deposit_addresses ? ` · ${c.deposit_addresses} deposit addresses` : ''} · {Object.values(c.risk_labels ?? {}).reduce((a, b) => a + b, 0)} screened</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <details className="card sec">
          <summary><span className="micro">What the label files cover</span><span className="note">exchanges by chain · sanctions, hack and mixer screening · what a trace does</span></summary>
          <div className="coverage">
            <div>
              <div className="head"><span className="micro">Exchange labels</span><span className="note">exact-match attribution</span></div>
              <table>
                <thead><tr><th>Chain</th><th style={{ textAlign: 'right' }}>Exchange wallets</th><th style={{ textAlign: 'right' }}>Deposit addresses</th><th>Exchanges</th></tr></thead>
                <tbody>
                  {chains.map((c) => (
                    <tr key={c.key}>
                      <td>{c.name}</td>
                      <td className="num">{c.exchange_wallets}</td>
                      <td className="num">{c.deposit_addresses}</td>
                      <td className="exchanges">{coverage[c.key]?.exchanges?.exchanges?.join(', ') ?? '…'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="note" style={{ padding: '8px 14px' }}>A deposit address belongs to one customer's account at the exchange. A match names the exchange that holds the account, never the customer: only the exchange can say whose it is.</p>
            </div>
            <div>
              <div className="head"><span className="micro">Risk screening</span><span className="note">US, UK, EU, Israel, Japan, France · Tether freezes · explorer-tagged hacks and mixers</span></div>
              <table>
                <thead><tr><th>Chain</th><th style={{ textAlign: 'right' }}>Sanctioned</th><th style={{ textAlign: 'right' }}>Mixers</th><th style={{ textAlign: 'right' }}>Frozen</th><th style={{ textAlign: 'right' }}>Stolen funds</th></tr></thead>
                <tbody>
                  {chains.map((c) => (
                    <tr key={c.key}>
                      <td>{c.name}</td>
                      <td className="num">{coverage[c.key]?.risk?.counts_by_category?.sanctioned ?? c.risk_labels?.sanctioned ?? 0}</td>
                      <td className="num">{coverage[c.key]?.risk?.counts_by_category?.mixer ?? c.risk_labels?.mixer ?? 0}</td>
                      <td className="num">{coverage[c.key]?.risk?.counts_by_category?.frozen ?? c.risk_labels?.frozen ?? 0}</td>
                      <td className="num">{coverage[c.key]?.risk?.counts_by_category?.stolen ?? c.risk_labels?.stolen ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="note" style={{ padding: '8px 14px' }}>Every mixer on the current SDN list is a Bitcoin service, so the count is zero; the stop-at-a-mixer rule is built and tested.</p>
            </div>
            <div>
              <div className="head"><span className="micro">What a trace does</span></div>
              <div className="body">
                <div className="kv"><span className="k">Attribution</span><span className="v">exact label match, or a stated inference</span></div>
                <div className="kv"><span className="k">Patterns</span><span className="v">fixed arithmetic, thresholds printed</span></div>
                <div className="kv"><span className="k">Time rule</span><span className="v">only transfers after the funds arrived</span></div>
                <div className="kv"><span className="k">Stops at</span><span className="v">exchanges, mixers, routers, service contracts</span></div>
                <div className="kv"><span className="k">Score</span><span className="v">three weighted inputs; null when nothing matched</span></div>
                <div className="kv"><span className="k">Never</span><span className="v">a person, a model, a guess</span></div>
              </div>
            </div>
          </div>
        </details>

        {!locked && <BulkIntake />}
        {!locked && <Watchlist />}
        <OpenRequests />

        <section>
          <div className="card">
            <div className="head"><span className="micro">Stored cases · {cases.length}</span><span className="note">yours and the demos · only this browser sees yours · opening one does not re-trace</span></div>
            {cases.length === 0 ? <p className="note" style={{ padding: 12 }}>No stored cases yet. Cases you trace are listed here, in this browser only.</p> : (
              <table className="cases-table" tabIndex={0} aria-label="Stored cases">
                <thead><tr><th>Reported address</th><th>Chain</th><th>Asset</th><th>Result</th><th style={{ textAlign: 'right' }}>Confidence</th><th style={{ textAlign: 'right' }}>Addresses</th><th>Flags</th><th>Traced</th></tr></thead>
                <tbody>
                  {cases.map((c) => (
                    <tr className="row" key={c.case_id} onClick={() => navigate(`/case/${c.case_id}`)} title={`Open stored case for ${c.address}`}>
                      <td className="mono">{middle(c.address, 12, 10)}{c.direction === 'incoming' && <span className="pill navy" style={{ marginLeft: 8 }}>reverse</span>}{c.demo && <span className="pill" style={{ marginLeft: 8 }}>demo</span>}</td>
                      <td>{c.chain}</td>
                      <td className="mono">{c.asset ?? '—'}</td>
                      <td className={c.exchange ? '' : 'none'}>{c.exchange ?? 'no match'}</td>
                      <td className="num">{c.confidence == null ? 'n/a' : c.confidence.toFixed(2)}</td>
                      <td className="num">{c.node_count}</td>
                      <td>{(c.flags ?? []).map((f) => <span className="pill amber" key={f} style={{ marginRight: 4 }}>{f.replace('_', ' ')}</span>)}</td>
                      <td className="mono">{String(c.created_at).slice(0, 10)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </div>

      <footer className="foot">
        <span>Attribution identifies an exchange, never a person. Only the exchange can link an address to a customer, on a lawful request.</span>
        <span>{health ? `${chains.filter((c) => c.ready).length} chains ready` : ''}</span>
      </footer>
    </div>
  )
}
