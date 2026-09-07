import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchCases, fetchHealth } from '../api'

// A real mainnet address that reaches Binance in two hops — useful both as a
// demo and as a check that the backend is wired up.
const SAMPLE = '0x60d02e0956e2f3795167c15ba61ab452c85c2533'

// Same rules the backend enforces, checked here only so an obvious typo gets
// immediate feedback instead of a round trip. The backend remains the
// authority. The rule depends on the chain: Ethereum and BSC share the EVM
// 0x format, Tron uses case-sensitive Base58 beginning with T.
const ADDRESS_RE = {
  evm: /^0x[0-9a-fA-F]{40}$/,
  tron: /^T[1-9A-HJ-NP-Za-km-z]{33}$/,
}
const PLACEHOLDER = { evm: '0x…', tron: 'T…' }

const short = (a) => (a.length > 18 ? `${a.slice(0, 10)}…${a.slice(-6)}` : a)

export default function Home() {
  const navigate = useNavigate()
  const [health, setHealth] = useState(null)
  const [cases, setCases] = useState([])
  const [address, setAddress] = useState('')
  const [chain, setChain] = useState('ethereum')
  const [asset, setAsset] = useState('ETH')
  const [depth, setDepth] = useState(4)
  const [direction, setDirection] = useState('outgoing')
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        setHealth(h)
        if (h.default_chain) {
          setChain(h.default_chain)
          setAsset(h.chains?.[h.default_chain]?.assets?.[0]?.symbol ?? 'ETH')
        }
      })
      .catch(() => setHealth({ status: 'down' }))
    fetchCases(8).then((d) => setCases(d.cases)).catch(() => {})
  }, [])

  const chains = health?.chains ? Object.values(health.chains) : []
  const active = health?.chains?.[chain]
  const assets = active?.assets ?? []
  const family = active?.address_family ?? 'evm'
  const backendDown = health?.status === 'down'

  const trimmed = address.trim()
  const pattern = ADDRESS_RE[family] ?? ADDRESS_RE.evm
  const valid = pattern.test(trimmed)
  const showInvalid = touched && trimmed.length > 0 && !valid

  // Switching chain must reset the asset: USDT exists on all three, but BNB
  // does not exist on Ethereum, so carrying the symbol across would request an
  // asset the new chain cannot serve.
  const changeChain = useCallback((next) => {
    setChain(next)
    setAsset(health?.chains?.[next]?.assets?.[0]?.symbol ?? 'ETH')
  }, [health])

  const open = useCallback((addr, opts = {}) => {
    const params = new URLSearchParams({
      chain: opts.chain ?? chain,
      asset: opts.asset ?? asset,
      depth: String(opts.depth ?? depth),
      direction: opts.direction ?? direction,
    })
    navigate(`/trace/${addr}?${params}`)
  }, [navigate, chain, asset, depth, direction])

  function submit(event) {
    event.preventDefault()
    setTouched(true)
    if (valid) open(trimmed)
  }

  const labelCount = active?.exchange_labels
  const totalLabels = chains.reduce((sum, c) => sum + (c.exchange_labels || 0), 0)

  return (
    <div className="landing">
      <nav className="landing-nav">
        <div className="wordmark">
          <h1>TraceChain</h1>
          <span className="tag">Cryptocurrency fraud tracing</span>
        </div>
        <div className="nav-status">
          <span className={`dot ${backendDown ? 'down' : health ? 'live' : ''}`} />
          {backendDown
            ? 'Backend unreachable'
            : health
              ? `${chains.filter((c) => c.ready).length} chains · ${totalLabels} labels`
              : 'Connecting…'}
        </div>
      </nav>

      <header className="hero">
        <h2>Follow the money to the exchange it left through.</h2>
        <p>
          {direction === 'outgoing' ? (
            <>
              A victim reports one wallet address. TraceChain follows outgoing transfers
              hop by hop, flags known laundering patterns along the way, and identifies
              the exchange where the funds were cashed out — as a report an investigator
              can attach to a legal request.
            </>
          ) : (
            <>
              Walk the money backwards. TraceChain follows incoming transfers to find
              every address that funded this wallet — where it belongs to an offender,
              those senders are candidate victims of the same operation, each of whom
              may hold a separate complaint.
            </>
          )}
        </p>

        <form className="trace-form" onSubmit={submit}>
          <input
            className={`address-field ${showInvalid ? 'invalid' : ''}`}
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            onBlur={() => setTouched(true)}
            placeholder={`Suspect wallet address  ${PLACEHOLDER[family] ?? ''}`}
            spellCheck={false}
            autoComplete="off"
            aria-label="Suspect wallet address"
            aria-invalid={showInvalid}
          />

          <div className="controls">
            <select
              value={direction}
              onChange={(e) => setDirection(e.target.value)}
              aria-label="Trace direction"
              title="Outgoing follows where this address sent funds. Incoming finds the addresses that paid it."
            >
              <option value="outgoing">Where funds went</option>
              <option value="incoming">Who sent funds here</option>
            </select>

            <select
              value={chain}
              onChange={(e) => changeChain(e.target.value)}
              aria-label="Blockchain"
              title="Which chain to trace on. The same address can exist on several."
            >
              {chains.map((c) => (
                <option key={c.key} value={c.key} disabled={!c.ready}>
                  {c.name}{c.ready ? '' : ' — unavailable'}
                </option>
              ))}
            </select>

            <select
              value={asset}
              onChange={(e) => setAsset(e.target.value)}
              aria-label="Asset"
              title="One asset per trace — amounts in different assets are not comparable."
            >
              {assets.map((a) => <option key={a.symbol} value={a.symbol}>{a.symbol}</option>)}
            </select>

            <select
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
              aria-label="Trace depth"
              title="How many hops to follow. More finds more, and takes longer."
            >
              {[2, 3, 4, 5, 6].map((d) => <option key={d} value={d}>{d} hops</option>)}
            </select>

            <span className="spacer" />
            <button type="submit" className="primary" disabled={!valid || backendDown}>
              {direction === 'outgoing' ? 'Trace' : 'Trace back'}
            </button>
          </div>

          {showInvalid && (
            <div className="banner warn">
              Not a valid {active?.name ?? 'wallet'} address — expected{' '}
              {family === 'tron' ? 'T followed by 33 Base58 characters'
                                 : '0x followed by 40 hexadecimal characters'}.
            </div>
          )}
          {backendDown && (
            <div className="banner warn">
              Cannot reach the backend. Start it with{' '}
              <span className="mono">uvicorn app.main:app --reload</span>.
            </div>
          )}

          <div className="sample">
            <span>Sample</span>
            <button
              type="button"
              className="mono"
              onClick={() => { setChain('ethereum'); setAsset('ETH'); setAddress(SAMPLE) }}
            >
              {SAMPLE}
            </button>
          </div>
        </form>
      </header>

      <section className="section">
        <span className="micro">Method</span>
        <div className="capabilities">
          <div className="capability">
            <div className="n">01</div>
            <h3>Deterministic attribution</h3>
            <p>An address is attributed if and only if it appears in a published label file. No clustering, no inference.</p>
          </div>
          <div className="capability">
            <div className="n mono">{labelCount ?? '—'}</div>
            <h3>Verified exchange wallets</h3>
            <p>Every label proven against live chain data before it is accepted. On {active?.name ?? 'this chain'}.</p>
          </div>
          <div className="capability">
            <div className="n">02</div>
            <h3>Fixed arithmetic rules</h3>
            <p>Peel chain and amount split are threshold comparisons. Each finding reports the exact thresholds it applied.</p>
          </div>
          <div className="capability">
            <div className="n">03</div>
            <h3>No black-box inference</h3>
            <p>Every conclusion is reproducible by hand from the transaction data alone.</p>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="trust">
          Every attribution here is <strong>an exact match against a published exchange
          wallet</strong>, and every pattern is a fixed arithmetic rule that reports the
          thresholds it applied. <strong>Nothing is inferred by a model you cannot
          inspect.</strong> A trace names the exchange funds arrived at — never the person
          who controls the account.
        </div>
      </section>

      {cases.length > 0 && (
        <section className="section">
          <span className="micro">Recent cases</span>
          <div className="cases">
            {cases.map((item) => (
              <button
                key={item.case_id}
                className="case-row"
                onClick={() => navigate(`/case/${item.case_id}`)}
                title={`Open stored case for ${item.address}`}
              >
                <span className="addr">{short(item.address)}</span>
                <span className="meta">{item.chain}{item.asset ? ` · ${item.asset}` : ''}</span>
                <span className={`result ${item.exchange ? '' : 'none'}`}>
                  {item.exchange ?? 'no match'}
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      <footer className="landing-foot">
        <span>Smart India Hackathon 2026 · SIH26183 · Ministry of Home Affairs</span>
        <span>Attribution identifies an exchange, never a person.</span>
      </footer>
    </div>
  )
}
