import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ThemeToggle from '../components/ThemeToggle'
import Mark from '../components/Mark'
import { fetchAccess, fetchCases, fetchChains, fetchExchanges, fetchRiskLabels } from '../api'
import Showroom from '../components/Showroom'
import TraceForm, { SHORT_CHAIN } from '../components/TraceForm'
import Watchlist from '../components/Watchlist'
import OpenRequests from '../components/OpenRequests'
import BulkIntake from '../components/BulkIntake'
import GlobeBackground from '../components/GlobeBackground'
import { demoCode } from '../demoCode'
import { bandLabel, bandOf } from '../components/confidence'

const middle = (a, head = 10, tail = 8) => (a && a.length > head + tail + 1 ? `${a.slice(0, head)}…${a.slice(-tail)}` : a)
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })
// Each chain's own colour, for its dot and bar only: never for text or risk.
const CHAIN_TOKEN = { tron: 'tron', ethereum: 'eth', arbitrum: 'arb', polygon: 'poly', bsc: 'bnb' }
const chainColour = (key) => `var(--c-${CHAIN_TOKEN[key] ?? 'eth'})`
const ChainDot = ({ chain }) => <i className="chain-dot" style={{ background: chainColour(chain) }} aria-hidden="true" />

export default function Home() {
  const navigate = useNavigate()
  const [health, setHealth] = useState(null)
  const [cases, setCases] = useState([])
  const [coverage, setCoverage] = useState({})
  // Whether this site asks for an access code (backend/app/access.py). Until it
  // answers, or if it cannot, the form shows: the backend refuses a trace
  // without the code either way, so the worst case is its message.
  const [access, setAccess] = useState(null)
  const [unlocked, setUnlocked] = useState(() => Boolean(demoCode()))
  const [tab, setTab] = useState('cases')
  const [watchCount, setWatchCount] = useState(0)
  const [requestCount, setRequestCount] = useState(0)

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
  const ready = chains.filter((c) => c.ready).length
  const backendDown = health?.status === 'down'
  // A public site without the code: verified examples only, nothing that would
  // spend the provider quota or keep running (batches, watches).
  const locked = Boolean(access?.demo_code_required) && !unlocked

  // Flagged addresses per chain: the risk-label count (label files plus the
  // label store), from /risk-labels once it answers, /chains until then.
  const flaggedOf = (c) => coverage[c.key]?.risk?.count ?? Object.values(c.risk_labels ?? {}).reduce((a, b) => a + (b || 0), 0)
  const perChain = chains.map((c) => ({ ...c, flagged: flaggedOf(c) })).sort((a, b) => b.flagged - a.flagged)
  const totalFlagged = perChain.reduce((s, c) => s + c.flagged, 0)
  const top = perChain[0]?.flagged || 1

  const tabs = [
    { key: 'cases', label: `Stored cases · ${cases.length}` },
    !locked && { key: 'watch', label: `Watchlist · ${watchCount}` },
    { key: 'requests', label: `Open requests · ${requestCount}` },
    !locked && { key: 'bulk', label: 'Bulk intake' },
    { key: 'coverage', label: 'Coverage' },
  ].filter(Boolean)
  const current = tabs.some((t) => t.key === tab) ? tab : 'cases'

  return (
    <div className="home console">
      <GlobeBackground />
      <header className="topbar glass">
        <Link to="/" className="brand"><Mark size={18} />Exchequer</Link>
        <span className="status-chip">
          {backendDown ? <><span className="dot down" />Backend unreachable</>
            : health ? <><span className="dot live" />Live · {ready} {ready === 1 ? 'chain' : 'chains'}</>
            : <><span className="dot" />Connecting</>}
        </span>
        <span className="grow" />
        <ThemeToggle />
      </header>

      <div className="home-body">
        <section className="intake">
          <div className="intake-form">
            {locked ? <Showroom onUnlock={() => setUnlocked(true)} /> : <TraceForm health={health} />}
          </div>

          <div className="card glass flagged-card" aria-label="Flagged addresses screened">
            <div className="body">
              <div className="flagged-total">
                <strong>{health && !backendDown ? compact.format(totalFlagged) : '—'}</strong>
                <span>flagged addresses</span>
              </div>
              <span className="mono exact">{health && !backendDown ? `${totalFlagged.toLocaleString('en')} · screened on every hop` : backendDown ? 'Backend unreachable' : 'Connecting…'}</span>
              <ul className="chain-bars">
                {perChain.map((c) => (
                  <li key={c.key}>
                    <span className="name" title={c.name}><ChainDot chain={c.key} />{SHORT_CHAIN[c.key] ?? c.name}</span>
                    <span className="n mono">{c.flagged.toLocaleString('en')}</span>
                    <span className="bar" aria-hidden="true"><i style={{ width: `${Math.max(1.5, (c.flagged / top) * 100)}%`, background: chainColour(c.key) }} /></span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section className="card glass tabbed">
          <div className="tabs" role="tablist" aria-label="Your work">
            {tabs.map((t) => (
              <button key={t.key} role="tab" type="button" aria-selected={current === t.key} className={current === t.key ? 'on' : ''} onClick={() => setTab(t.key)}>{t.label}</button>
            ))}
          </div>

          <div className="tab-panel" role="tabpanel" hidden={current !== 'cases'}>
            {cases.length === 0 ? <p className="note empty">No cases yet. Cases you trace show here, in this browser only.</p> : (
              <table className="cases-table" tabIndex={0} aria-label="Stored cases">
                <thead><tr><th>Reported address</th><th>Chain</th><th>Asset</th><th>Result</th><th style={{ textAlign: 'right' }}>Confidence</th><th style={{ textAlign: 'right' }}>Addresses</th><th>Flags</th><th>Traced</th></tr></thead>
                <tbody>
                  {cases.map((c) => (
                    <tr className="row" key={c.case_id} onClick={() => navigate(`/case/${c.case_id}`)} title={`Open stored case for ${c.address}`}>
                      <td className="mono">{middle(c.address, 12, 10)}{c.direction === 'incoming' && <span className="pill navy" style={{ marginLeft: 8 }}>reverse</span>}{c.demo && <span className="pill" style={{ marginLeft: 8 }}>example</span>}</td>
                      <td><ChainDot chain={c.chain} />{c.chain}</td>
                      <td className="mono">{c.asset ?? '—'}</td>
                      <td className={c.exchange ? '' : 'none'}>{c.exchange ?? 'no match'}</td>
                      <td>{c.confidence == null ? 'n/a' : bandLabel(bandOf(c.confidence))}</td>
                      <td className="num">{c.node_count}</td>
                      <td>{(c.flags ?? []).map((f) => <span className="pill amber" key={f} style={{ marginRight: 4 }}>{f.replace('_', ' ')}</span>)}</td>
                      <td className="mono">{String(c.created_at).slice(0, 10)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {cases.length > 0 && <p className="note foot-note">Only this browser sees your cases. Opening one does not re-trace.</p>}
          </div>

          {!locked && (
            <div className="tab-panel" role="tabpanel" hidden={current !== 'watch'}>
              <Watchlist onCount={setWatchCount} />
              {watchCount === 0 && <p className="note empty">Nothing watched yet. Open a case and choose Watch to be told when the money moves.</p>}
            </div>
          )}

          <div className="tab-panel" role="tabpanel" hidden={current !== 'requests'}>
            <OpenRequests onCount={setRequestCount} />
            {requestCount === 0 && <p className="note empty">No open requests. Letters you log from a case are tracked here.</p>}
          </div>

          {!locked && (
            <div className="tab-panel" role="tabpanel" hidden={current !== 'bulk'}>
              <BulkIntake defaultOpen />
            </div>
          )}

          <div className="tab-panel" role="tabpanel" hidden={current !== 'coverage'}>
            <div className="coverage">
              <div>
                <div className="head"><span className="micro">Exchange labels</span><span className="note">exact-match attribution</span></div>
                <table>
                  <thead><tr><th>Chain</th><th style={{ textAlign: 'right' }}>Exchange wallets</th><th style={{ textAlign: 'right' }}>Deposit addresses</th><th>Exchanges</th></tr></thead>
                  <tbody>
                    {chains.map((c) => (
                      <tr key={c.key}>
                        <td title={c.name}><ChainDot chain={c.key} />{SHORT_CHAIN[c.key] ?? c.name}</td>
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
                        <td title={c.name}><ChainDot chain={c.key} />{SHORT_CHAIN[c.key] ?? c.name}</td>
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
          </div>
        </section>
      </div>

      <footer className="foot">
        <span>Names an exchange, never a person.</span>
      </footer>
    </div>
  )
}
