import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchRecordedDemos, fetchTraceIntake } from '../api'
// The address and hash rules the backend enforces, checked here only so an
// obvious typo gets immediate feedback instead of a round trip.
import { ADDRESS_RE, HASH_RE } from '../find'
import NoHashSearch from './NoHashSearch'
import CaseRefField, { refOk, tidyRef, useSignedIn } from './CaseRefField'
import './TraceForm.css'

// The ten verified traces in DEMO.md, one click each. Addresses and hooks
// are copied from that file; the numbers there were measured cold on
// 15 September 2026. The console offers three of them as recorded cases.
export const DEMOS = [
  { n: '01', address: '0x7c3e9bab6715e4040f013e865b193b0209642e36', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'No cash-out found', hook: 'Three hops, no exchange, no pattern. The score reads "not applicable", not 0 — finding nothing is a result.' },
  { n: '02', address: '0xbc1ada2e98dd0087cf4cc0c8bd0e6276c82fadc9', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'The pattern that stopped firing', hook: 'An amount split fired here on 15 Sep and not on 23 Sep — same rule, the chain moved. Why no pattern is ever scored.' },
  { n: '03', address: '0x536c4921d1aafde6a5cda882fb5ca046f3601c65', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'An attribution that keeps moving', hook: 'Changed six times on live data, each for a stated reason. Two days ago a weak OKX lead (≈ 1.65 of 951 ETH); now the wallet paid a Binance deposit address directly — 1 hop, 0.875.' },
  { n: '04', address: '0x536c4921d1aafde6a5cda882fb5ca046f3601c65', chain: 'ethereum', asset: 'ETH', depth: 1, direction: 'incoming',
    title: 'Who paid the offender', hook: 'The same wallet asked the other question: ten addresses funded it, none an exchange — ten candidate complaints.' },
  { n: '05', address: '0x60d02e0956e2f3795167c15ba61ab452c85c2533', chain: 'ethereum', asset: 'ETH', depth: 1, direction: 'incoming',
    title: 'Why funders are labelled carefully', hook: 'Ten funders, five of them exchange withdrawals marked as such. A tool counting "ten victims" would double the count.' },
  { n: '06', address: '0x00000000072d54638c2c2a3da3f715360269eea1', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'The deposit address to name', hook: 'A phishing wallet: funds reach a probable Binance deposit address — inferred, scored lower — and 10 ETH reach Tornado Cash, where the trace stops.' },
  { n: '07', address: '0x21b8d56bda776bbe68655a16895afd96f5534fed', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'Three governments, one wallet', hook: 'The reported address is on the US, UK and Israeli lists; its funds reach a probable Bybit deposit address.' },
  { n: '08', address: '0x4655b7ad0b5f5bacb9cf960bbffceb3f0e51f363', chain: 'ethereum', asset: 'ETH', depth: 2, direction: 'outgoing',
    title: 'The trail changes asset', hook: '2,000 ETH into 1inch, returned as wstETH. The swap is read from the receipt; the trace says where to re-run.' },
  { n: '09', address: 'THWYhwUQnBcKpwSxaXjqv18RPtSoK4C5Ph', chain: 'tron', asset: 'USDT', depth: 2, direction: 'outgoing',
    title: 'Tron, in under a second', hook: 'USDT-TRC20 to Binance-Hot 7 in one hop, 26,405 USDT, high confidence — against 41 verified Tron labels.' },
  { n: '10', address: '0x000000000532b45f47779fce440748893b257865', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'Three complaints, one operation', hook: 'Shares 60 and 46 intermediaries with two other stored phishing wallets — and all three reach the same known phishing wallet.' },
  { n: '11', address: 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts', chain: 'tron', asset: 'USDT', depth: 2, direction: 'outgoing',
    title: 'Frozen by Tether', hook: 'A Tron wallet whose USDT Tether froze on 11 Sep 2026 — as it did the next wallet — splits 45,968 USDT onward; it reaches Binance-Hot 7 at 0.80.' },
  { n: '12', address: 'TB2KXtbmFJa8PaCPbRXrJrHkZSPU22eqja', chain: 'tron', asset: 'USDT', depth: 2, direction: 'outgoing',
    title: 'An exchange the file does not know', hook: 'Flipster is not among the 41 labelled Tron wallets; TronScan’s own tag, read live, names it with high confidence.' },
]

// The optional wall-clock cap, in seconds. 1:30 is long enough for any of
// the demo traces cold and short enough to keep a room waiting comfortably.
const TIME_BUDGET_SECONDS = 90

// The NCRP acknowledgement number, as the backend checks it: 10 to 20 digits.
const NCRP_RE = /^[0-9]{10,20}$/

/** Hashes from what the officer pasted: one per line, or separated by commas or spaces. */
export function parseHashes(text) {
  return [...new Set(text.split(/[\s,]+/).map((h) => h.trim()).filter(Boolean))]
}

/** A hash as the backend compares it (normalize_hash): one payment typed in
 * capitals, or with or without 0x, is the same payment. */
const sameHash = (h) => h.toLowerCase().replace(/^0x/, '')

// Short names for the chain picker; the full name stays in its tooltip.
export const SHORT_CHAIN = { ethereum: 'Ethereum', bsc: 'BNB Chain', polygon: 'Polygon', arbitrum: 'Arbitrum', tron: 'Tron' }

// The chips' order on the New trace page: Tron first, where most complaints' USDT is.
const CHAIN_ORDER = ['tron', 'ethereum', 'bsc', 'polygon', 'arbitrum']
const byKey = (a, b) => (CHAIN_ORDER.indexOf(a) + 1 || 99) - (CHAIN_ORDER.indexOf(b) + 1 || 99)
const byOrder = (a, b) => byKey(a.key, b.key)
const listed = (names) => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`)

// What a trace does once started, beside the form (as the Tracing screen's steps).
const NEXT = [
  ['Find the payment on the chain', 'with payment hashes, the trace starts when the money arrived', DownIcon],
  ['Follow it, hop by hop', 'only money that left after it arrived', SplitIcon],
  ['Screen every wallet', 'exchanges, sanctions, freezes, gambling', ShieldIcon],
  ['Show where it is now', 'and who to write to', PageIcon],
]

/** The New trace page: the wallet the victim paid, how to trace it, and the
 * DEMO.md examples to fill it from. `health` is GET /chains as the page
 * loaded it (null while connecting, { status: 'down' } when unreachable).
 * `payments` fills the victim's payment hashes, as the search box sends one,
 * and `startChain` and `startAsset` the chain and asset to start on when the
 * site has them. `onUnlock` runs when the code is entered in the search, after
 * it found the site wants one. */
export default function TraceForm({ health, payments = '', startChain = null, startAsset = null, onUnlock }) {
  const navigate = useNavigate()
  const [address, setAddress] = useState('')
  const [chain, setChain] = useState('ethereum')
  const [asset, setAsset] = useState('ETH')
  // Four hops unless chosen: the depth the recorded results were traced at.
  const [depth, setDepth] = useState(4)
  const [direction, setDirection] = useState('outgoing')
  // Off by default: the trace runs its full course. On, it stops at 1:30 and
  // reports what it reached -- for a live pick whose size nobody knows.
  const [capped, setCapped] = useState(false)
  const [touched, setTouched] = useState(false)
  // The demo last loaded into the form, and which demos have a recording.
  const [loadedDemo, setLoadedDemo] = useState(null)
  const [recordings, setRecordings] = useState({})
  // R1: whether the backend can start a trace from payment hashes, and the
  // hashes and NCRP number the officer entered.
  const [intake, setIntake] = useState(null)
  const [paymentText, setPaymentText] = useState(payments)
  const [ncrpAck, setNcrpAck] = useState('')
  const [showAck, setShowAck] = useState(false)
  const [victimText, setVictimText] = useState('')
  const [showPayments, setShowPayments] = useState(Boolean(payments))
  // Hashes the officer found by searching the wallet (NoHashSearch): the
  // trace says they were not given by the victim.
  const [officerFound, setOfficerFound] = useState([])
  const hashesRef = useRef(null)
  const [picked, setPicked] = useState(0)
  useEffect(() => { if (picked) hashesRef.current?.focus() }, [picked])
  // A signed-in officer traces only under a case reference (case_refs.py).
  const officer = useSignedIn()
  const [caseRef, setCaseRef] = useState('')

  // Trace on the deployment's default chain once /health names it (or the
  // first chain that is on, when the default is off), or on the chain (and
  // asset) asked for when it is one the site traces. On Tron, the money in a
  // complaint is almost always USDT.
  useEffect(() => {
    const on = (key) => health?.chains?.[key]?.ready
    const first = [startChain, health?.default_chain, ...Object.keys(health?.chains ?? {}).sort(byKey)].find(on) ?? health?.default_chain
    if (!first) return
    const symbols = (health.chains?.[first]?.assets ?? []).map((a) => a.symbol)
    const asked = [first === startChain && startAsset, (first === startChain || first === 'tron') && 'USDT']
      .find((s) => s && symbols.includes(s))
    setChain(first)
    setAsset(asked || (symbols[0] ?? 'ETH'))
  }, [health, startChain, startAsset])

  // Unreachable reads as off: the form cannot offer payments either way.
  useEffect(() => {
    fetchTraceIntake().then(setIntake).catch(() => setIntake({ payments: false }))
  }, [])

  useEffect(() => {
    fetchRecordedDemos()
      .then((d) => setRecordings(Object.fromEntries(d.demos.map((r) => [r.demo, r]))))
      .catch(() => {})
  }, [])

  const chains = health?.chains ? Object.values(health.chains).sort(byOrder) : []
  const off = chains.filter((c) => !c.ready).map((c) => SHORT_CHAIN[c.key] ?? c.name)
  const active = health?.chains?.[chain]
  const assets = active?.assets ?? []
  const family = active?.address_family ?? 'evm'
  const backendDown = health?.status === 'down'

  const trimmed = address.trim()
  const valid = (ADDRESS_RE[family] ?? ADDRESS_RE.evm).test(trimmed)
  const showInvalid = touched && trimmed.length > 0 && !valid

  // Payments start a trace of where the money went, so they are offered only
  // for that direction, and only when the backend has them switched on.
  const paymentMode = Boolean(intake?.payments) && direction === 'outgoing'
  // Only what the officer can see is sent or checked: a collapsed panel keeps
  // its text for when it is opened again, but the trace is then address-only.
  const entered = paymentMode ? parseHashes(paymentText) : []
  const hashes = showPayments ? entered : []
  const badHashes = hashes.filter((h) => !(HASH_RE[family] ?? HASH_RE.evm).test(h))
  const ack = hashes.length ? ncrpAck.trim() : ''
  const badAck = ack !== '' && !NCRP_RE.test(ack)
  // The victim's own wallet: each payment's sender is compared with it.
  const victim = hashes.length ? victimText.trim() : ''
  const victimIsReported = victim !== '' && (family === 'tron' ? victim === trimmed : victim.toLowerCase() === trimmed.toLowerCase())
  const badVictim = victim !== '' && (!(ADDRESS_RE[family] ?? ADDRESS_RE.evm).test(victim) || victimIsReported)
  const searched = hashes.filter((h) => officerFound.includes(sameHash(h)))
  const ref = officer && refOk(caseRef) ? tidyRef(caseRef) : ''
  // officer is null until GET /auth/me answers: wait, rather than start without a reference.
  const blocked = badHashes.length > 0 || badAck || badVictim || officer === null || (officer && !ref)

  // Switching chain resets the asset: BNB does not exist on Ethereum, so the
  // symbol cannot be carried across.
  const changeChain = useCallback((next) => {
    setChain(next)
    setAsset(health?.chains?.[next]?.assets?.[0]?.symbol ?? 'ETH')
  }, [health])

  const open = useCallback((addr, opts = {}) => {
    const q = new URLSearchParams({
      chain: opts.chain ?? chain, asset: opts.asset ?? asset,
      depth: String(opts.depth ?? depth), direction: opts.direction ?? direction,
    })
    if (opts.capped ?? capped) q.set('budget', String(TIME_BUDGET_SECONDS))
    // Payment hashes are public chain data and make the link reproducible, so
    // they go in the URL. The NCRP number is a complaint reference: it travels
    // in this tab's navigation state, never in the URL, the server's logs or
    // another browser's view of the case (backend/app/case_privacy.py). The
    // victim's wallet is the complaint's too, so it travels the same way.
    if (hashes.length) q.set('pay', hashes.join(','))
    if (searched.length) q.set('found', searched.join(','))
    // startedHere: the trace page runs it at once; a link opened from elsewhere asks first.
    // An officer's case reference travels the same way.
    const state = { startedHere: true, ...(ack ? { ncrpAck: ack } : {}), ...(victim ? { victimAddress: victim } : {}), ...(ref ? { caseRef: ref } : {}) }
    navigate(`/trace/${addr}?${q}`, { state })
  }, [navigate, chain, asset, depth, direction, capped, hashes, searched, ack, victim, ref])

  /** A payment the search found, added to the hashes and marked as found by the officer. */
  function takeMatch(hash) {
    const key = sameHash(hash)
    setPaymentText((text) => (parseHashes(text).some((h) => sameHash(h) === key) ? text : [text.trim(), hash].filter(Boolean).join('\n')))
    setOfficerFound((found) => (found.includes(key) ? found : [...found, key]))
    setShowPayments(true)
    setPicked((n) => n + 1)
  }

  // Fill the form from one of the verified DEMO.md traces. The trace is not
  // started: the officer still presses the same button they would for a real
  // address, so the demo path and the real path are the same path.
  function loadDemo(n) {
    const d = DEMOS.find((x) => x.n === n)
    if (!d) return
    setChain(d.chain); setAsset(d.asset); setDepth(d.depth); setDirection(d.direction)
    setAddress(d.address); setTouched(false); setLoadedDemo(d)
    // A demo is an address-only trace: payments typed for another case don't carry over.
    setPaymentText(''); setNcrpAck(''); setVictimText('')
  }

  // Shown while the form still holds the demo exactly as loaded: edit the
  // address or the direction and it is no longer that demo.
  const demoInForm = loadedDemo && loadedDemo.address === trimmed && loadedDemo.direction === direction
    && loadedDemo.depth === depth && loadedDemo.chain === chain ? loadedDemo : null
  const recording = demoInForm && recordings[Number(demoInForm.n)]

  function submit(event) {
    event.preventDefault()
    setTouched(true)
    if (valid && !blocked) open(trimmed)
  }

  const outgoing = direction === 'outgoing'
  return (
    <div className="trace-new">
      <form onSubmit={submit} className="card trace-card" aria-label="New trace">
        <fieldset className="nt-group">
          <legend className="nt-k">Chain and asset</legend>
          <div className="nt-chips" role="radiogroup" aria-label="Blockchain" title="The same address can exist on several chains; it is never inferred.">
            {chains.map((c) => (
              <label key={c.key} className="nt-chip" title={c.name}>
                <input type="radio" name="chain" value={c.key} checked={chain === c.key} disabled={!c.ready} onChange={() => changeChain(c.key)} />
                {SHORT_CHAIN[c.key] ?? c.name}{!c.ready && <span className="nt-off"> off</span>}
              </label>
            ))}
          </div>
          <div className="nt-chips" role="radiogroup" aria-label="Asset" title="One asset per trace — amounts in different assets are not comparable.">
            {assets.map((a) => (
              <label key={a.symbol} className="nt-chip mono">
                <input type="radio" name="asset" value={a.symbol} checked={asset === a.symbol} onChange={() => setAsset(a.symbol)} />{a.symbol}
              </label>
            ))}
          </div>
          {off.length > 0 && <p className="nt-hint">{listed(off)} {off.length === 1 ? 'is' : 'are'} off on this site: no chain data provider is set up for {off.length === 1 ? 'it' : 'them'}.</p>}
        </fieldset>

        <div className="nt-field">
          <label className="nt-k" htmlFor="reported-wallet">Wallet the victim paid</label>
          <input
            id="reported-wallet" className={`fld mono ${showInvalid ? 'invalid' : ''}`} value={address}
            onChange={(e) => setAddress(e.target.value)} onBlur={() => setTouched(true)}
            placeholder="Paste the address from the complaint" spellCheck={false} autoComplete="off"
            aria-invalid={showInvalid} aria-describedby="reported-wallet-hint"
          />
          <span id="reported-wallet-hint" className="nt-hint">The reported wallet · 0x… on EVM chains, T… on Tron</span>
        </div>
        {officer && <CaseRefField value={caseRef} onChange={setCaseRef} />}

        {payments && intake && !intake.payments && (
          <p className="note pay-note" role="status">
            Tracing from a payment hash is off on this site, so <span className="mono pay-hash">{payments}</span> is
            not used. Paste the wallet the victim paid into instead.
          </p>
        )}
        {paymentMode && (
          <div className="nt-pay">
            <button type="button" className="nt-toggle" aria-expanded={showPayments} onClick={() => setShowPayments((v) => !v)}>
              <PlusIcon />Victim's payments{!showPayments && entered.length > 0 ? ` · ${entered.length} entered, not sent` : ''}
            </button>
            {showPayments && (
              <>
                <div className="nt-field">
                  <label className="nt-k" htmlFor="payment-hashes">The victim's payment hashes, one per line</label>
                  <textarea
                    id="payment-hashes" ref={hashesRef} rows={2} value={paymentText} className="fld mono"
                    onChange={(e) => setPaymentText(e.target.value)}
                    placeholder={family === 'tron' ? 'One per line: 64 hex characters' : 'One per line: 0x followed by 64 hex characters'}
                    spellCheck={false} autoComplete="off" aria-invalid={badHashes.length > 0}
                  />
                  <p className="nt-hint nt-count" role="status">
                    {hashes.length > 0 && <>{badHashes.length === 0 && <CheckIcon />}{hashes.length} payment{hashes.length === 1 ? '' : 's'} · read on the chain when the trace starts{searched.length > 0 && ` · ${searched.length} found by officer search`}</>}
                  </p>
                </div>
                <div className="nt-pair">
                  <div className="nt-field">
                    <label className="nt-k" htmlFor="victim-wallet">Victim's own wallet</label>
                    <input id="victim-wallet" className="fld mono" value={victimText} onChange={(e) => setVictimText(e.target.value)}
                      maxLength={100} spellCheck={false} autoComplete="off" disabled={hashes.length === 0} aria-invalid={badVictim}
                      placeholder="Optional: the wallet the victim paid from" />
                  </div>
                  <div className="nt-field">
                    <label className="nt-k" htmlFor="ncrp-ack">NCRP acknowledgement</label>
                    <span className="nt-secret">
                      {/* Masked by the stylesheet, not type=password, so no browser offers to save it. */}
                      <input id="ncrp-ack" type="text" className={`fld mono${showAck ? '' : ' masked'}`} value={ncrpAck} onChange={(e) => setNcrpAck(e.target.value)}
                        maxLength={64} spellCheck={false} autoComplete="off" placeholder="Optional" disabled={hashes.length === 0}
                        inputMode="numeric" pattern="[0-9]{10,20}" aria-invalid={badAck} aria-describedby="ncrp-note" />
                      <button type="button" className="nt-reveal" aria-pressed={showAck} aria-label="Show the NCRP number" onClick={() => setShowAck((v) => !v)}>Show</button>
                    </span>
                    <span id="ncrp-note" className="nt-hint"><LockIcon />never in links or logs</span>
                  </div>
                </div>
                <p className="nt-hint">Optional. With them, the trace starts when the money arrived and the case records what the victim paid. Without them, it follows the wallet's whole recent history and is marked exploratory.</p>
              </>
            )}
          </div>
        )}

        {intake && direction === 'outgoing' && (
          <NoHashSearch chain={chain} chainName={active?.name ?? chain} asset={asset} wallet={trimmed} walletValid={valid}
            intakeOn={paymentMode} onPick={takeMatch} onUnlock={onUnlock} />
        )}

        <div className="nt-pair">
          <fieldset className="nt-field" title="How many hops to follow. More finds more and takes longer.">
            <legend className="nt-k">How far to follow</legend>
            <div className="nt-seg">
              {[1, 2, 3, 4].map((d) => (
                <label key={d}>
                  <input type="radio" name="depth" value={d} checked={depth === d} onChange={() => setDepth(d)} aria-label={`${d} hop${d === 1 ? '' : 's'}`} />{d}
                </label>
              ))}
            </div>
            <span className="nt-hint">hops · more hops, more provider requests</span>
          </fieldset>
          <div className="nt-field">
            <label className="tog" title="With this on, the trace stops expanding after 1 minute 30 seconds and reports what it reached, marked truncated. Off, it runs until the depth, fan-out and size limits stop it -- which on a busy wallet at 4 hops can take several minutes.">
              <input type="checkbox" checked={capped} onChange={(e) => setCapped(e.target.checked)} />
              <span className="track" aria-hidden="true"><span className="knob" /></span>
              <span>Stop after <span className="mono">1:30</span></span>
            </label>
            <span className="nt-hint">reports what it reached by then, marked truncated</span>
          </div>
        </div>

        {showInvalid && (
          <div className="banner warn">
            Not a valid {active?.name ?? 'wallet'} address — expected {family === 'tron' ? 'T followed by 33 Base58 characters' : '0x followed by 40 hexadecimal characters'}.
          </div>
        )}
        {badHashes.length > 0 && (
          <div className="banner warn">
            Not a valid {active?.name ?? ''} transaction hash: <span className="mono">{badHashes[0]}</span>{badHashes.length > 1 ? ` and ${badHashes.length - 1} more` : ''}.
          </div>
        )}
        {badAck && <div className="banner warn">An NCRP acknowledgement number is 10 to 20 digits, as on the complaint's acknowledgement.</div>}
        {badVictim && (
          <div className="banner warn">
            {victimIsReported
              ? "The victim's wallet is the reported wallet: enter the wallet the victim paid from."
              : `The victim's wallet is not a valid ${active?.name ?? ''} address.`}
          </div>
        )}
        {backendDown && (
          <div className="banner error">Cannot reach the backend. Start it with <span className="mono">uvicorn app.main:app --reload --port 8000</span>.</div>
        )}

        <div className="nt-foot">
          <p className="nt-direction">
            <span>Direction:</span> {outgoing ? 'where the money went' : 'who paid in'}
            <button type="button" className="quiet" onClick={() => setDirection(outgoing ? 'incoming' : 'outgoing')}
              title="Where it went follows what this address sent. Who paid in finds the addresses that paid it.">
              {outgoing ? 'Trace who paid in instead' : 'Trace where it went instead'}
            </button>
          </p>
          <button type="submit" className="primary nt-go" disabled={!valid || blocked || backendDown}>
            {outgoing ? 'Start trace' : 'Start trace back'}<ArrowIcon />
          </button>
        </div>
        <div className="nt-examples">
          <label className="nt-example" htmlFor="example">
            <StarIcon />
            <select id="example" aria-label="Load a verified example" value="" onChange={(e) => { loadDemo(e.target.value); e.target.value = '' }} disabled={backendDown}>
              <option value="">Load a verified example</option>
              {DEMOS.map((d) => (
                <option key={d.n} value={d.n} title={d.hook}>
                  {d.n} · {d.title} · {SHORT_CHAIN[d.chain] ?? 'Ethereum'} {d.asset} · {d.depth} hop{d.depth === 1 ? '' : 's'}{d.direction === 'incoming' ? ' · reverse' : ''}
                </option>
              ))}
            </select>
          </label>
          {recording && (
            <Link className="recorded-link" to={`/demo/${Number(demoInForm.n)}`} title="The trace as recorded on that date. Opens instantly; nothing is re-traced.">
              Open as recorded · <span className="mono">{recording.recorded_at.slice(0, 10)}</span>
            </Link>
          )}
        </div>
      </form>

      <section className="card glass nt-next" aria-labelledby="nt-next-title">
        <h2 id="nt-next-title">What happens next</h2>
        <ol>
          {NEXT.map(([step, line, Icon]) => (
            <li key={step}><span className="nt-icon"><Icon /></span><span><b>{step}</b><span className="nt-hint">{line}</span></span></li>
          ))}
        </ol>
      </section>
    </div>
  )
}

const svg = { fill: 'none', stroke: 'currentColor', strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true }
const ArrowIcon = () => <svg width="14" height="14" viewBox="0 0 14 14" strokeWidth="1.5" {...svg}><path d="M2 7h10M8 3l4 4-4 4" /></svg>
const PlusIcon = () => <svg width="12" height="12" viewBox="0 0 12 12" strokeWidth="1.5" {...svg}><path d="M6 2v8M2 6h8" /></svg>
const StarIcon = () => <svg width="14" height="14" viewBox="0 0 24 24" strokeWidth="1.6" {...svg}><path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.4 6.8 19.1l1-5.8L3.5 9.2l5.9-.9z" /></svg>
const CheckIcon = () => <svg className="ok" width="14" height="14" viewBox="0 0 16 16" strokeWidth="1.5" {...svg}><circle cx="8" cy="8" r="6.2" /><path d="M5.2 8.2l1.9 1.9 3.8-4" /></svg>
const LockIcon = () => <svg width="12" height="12" viewBox="0 0 16 16" strokeWidth="1.4" {...svg}><rect x="3" y="7" width="10" height="7" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" /></svg>
function DownIcon() { return <svg width="16" height="16" viewBox="0 0 16 16" strokeWidth="1.4" {...svg}><path d="M8 2v8M4.5 6.5L8 10l3.5-3.5M3 13.5h10" /></svg> }
function SplitIcon() { return <svg width="16" height="16" viewBox="0 0 16 16" strokeWidth="1.4" {...svg}><path d="M1.5 4c5 0 6 8 13 8M1.5 8h13M1.5 12c5 0 6-8 13-8" /></svg> }
function ShieldIcon() { return <svg width="16" height="16" viewBox="0 0 16 16" strokeWidth="1.4" {...svg}><path d="M8 1.8l5 2v4.1c0 3-2.2 5.2-5 6.3-2.8-1.1-5-3.3-5-6.3V3.8z" /></svg> }
function PageIcon() { return <svg width="16" height="16" viewBox="0 0 16 16" strokeWidth="1.4" {...svg}><path d="M2.5 2.5h8l3 3v8h-11zM5 8h6M5 10.5h6" /></svg> }
