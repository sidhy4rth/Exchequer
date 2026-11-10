import { useEffect, useRef, useState } from 'react'
import { searchPayments } from '../api'
import { plain } from '../text'
import { unlockLive } from './Showroom'
import { ist, middle, when } from './case/format'

// New trace's "I don't have the payment hash" path: search the reported
// wallet for the victim's payment by its exact amount and a time window in
// IST (POST /payments/search, backend/app/payment_search.py). The backend
// returns only the transfers into that wallet of exactly that amount, never
// its other transfers, and this shows only those. Nothing runs without a click.

// Either side of the time typed in. The backend takes a window of at most
// 7 days, so the widest is 3 days either side.
const SPANS = [[1, '1 h', '1 hour'], [3, '3 h', '3 hours'], [12, '12 h', '12 hours'], [72, '3 days', '3 days']]
const HOUR = 3600_000
const IST_OFFSET = 330 * 60_000
// What the chain counts: digits, and one decimal point. No grouping commas.
const AMOUNT_RE = /^\d+(\.\d+)?$/

/** A datetime-local value ("2026-11-09T14:30") read as a time in India. */
function fromIst(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value)
  return m ? new Date(Date.UTC(+m[1], m[2] - 1, +m[3], +m[4], +m[5]) - IST_OFFSET) : null
}

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

/** What a refused or failed search says, by its status. */
function failure(err) {
  // A 429 has several causes (this connection, the whole site, a running
  // trace, the provider): the backend's sentence says which, and when to retry.
  if (err.status === 429) return `The search was refused for now. ${err.message}`
  if (err.status >= 500) return `The wallet could not be read just now. ${err.message} You can also start the trace from the wallet without a hash.`
  if (err.status) return err.message
  return 'Cannot reach the Exchequer backend. Check the connection, then search again.'
}

export default function NoHashSearch({ chain, chainName, asset, wallet, walletValid, intakeOn, onPick, onUnlock }) {
  const [open, setOpen] = useState(false)
  const [amount, setAmount] = useState('')
  const [at, setAt] = useState('')
  const [span, setSpan] = useState(12)
  const [busy, setBusy] = useState(false)
  // { asked, result } or { asked, error }: kept with what was searched.
  const [outcome, setOutcome] = useState(null)
  // The demo code, asked for here when the search finds the site locked, so
  // nothing typed into the form is lost.
  const [code, setCode] = useState('')
  const [codeError, setCodeError] = useState('')
  const codeRef = useRef(null)
  const goRef = useRef(null)
  // A search answers for one wallet: another wallet, chain or asset clears it.
  useEffect(() => { setOutcome(null) }, [chain, asset, wallet])

  const amountOk = AMOUNT_RE.test(amount) && Number(amount) > 0
  const centre = fromIst(at)
  const from = centre && new Date(centre.getTime() - span * HOUR)
  const to = centre && new Date(centre.getTime() + span * HOUR)
  const ready = walletValid && amountOk && centre
  const missing = !walletValid ? 'Enter the wallet the victim paid above first.'
    : !amountOk ? 'Enter the exact amount: digits, with one decimal point.'
      : !centre ? 'Enter when the victim paid.' : ''

  async function search() {
    if (!ready || busy) return
    const asked = { amount, asset, from, to }
    setBusy(true)
    try {
      setOutcome({ asked, result: await searchPayments({ chain, asset, wallet, amount, from, to }) })
    } catch (error) {
      setOutcome({ asked, error })
      if (error.status === 403) setTimeout(() => codeRef.current?.focus())
    } finally {
      setBusy(false)
    }
  }

  /** Unlock live tracing with the code typed here, then search again: one press. */
  async function unlock() {
    const typed = code.trim()
    if (!typed || busy) return
    setCodeError('')
    try {
      await unlockLive(typed)
    } catch (err) {
      setCodeError(err.message)
      return
    }
    setCode('')
    onUnlock?.()
    goRef.current?.focus()
    search()
  }

  // Enter in any field (a window choice too) searches, or unlocks in the code
  // box: it never submits the trace form around it, which would start a trace.
  const onKeyDown = (e) => {
    if (e.key !== 'Enter' || e.target.tagName !== 'INPUT') return
    e.preventDefault()
    if (e.target === codeRef.current) unlock()
    else search()
  }

  const { asked, result, error } = outcome ?? {}
  const sought = asked && `exactly ${asked.amount} ${asked.asset}`
  const matches = result?.matches ?? []
  return (
    <div className="nh">
      <button type="button" className="nt-toggle" aria-expanded={open} aria-controls="no-hash" onClick={() => setOpen((v) => !v)}>
        <SearchIcon />I don't have the payment hash
      </button>
      {open && (
        <div id="no-hash" className="nh-panel">
          {!intakeOn ? (
            <p className="note">
              Tracing from a payment hash is off on this site, so a payment found by search cannot start the trace.
              Start it from the wallet instead: the trace then follows the wallet's whole recent history.
            </p>
          ) : (
            <fieldset className="nt-group" onKeyDown={onKeyDown}>
              <legend className="nt-k">Search the wallet for the payment</legend>
              <p className="nh-what">
                <span>{chainName} · {asset}</span>
                <span className="mono nh-wallet">{walletValid ? wallet : 'no wallet entered yet'}</span>
                <span className="nt-hint">the chain, asset and wallet above</span>
              </p>
              <div className="nt-pair">
                <div className="nt-field">
                  <label className="nt-k" htmlFor="nh-amount">Exact amount paid</label>
                  <input id="nh-amount" className="fld mono" value={amount} onChange={(e) => setAmount(e.target.value.trim())}
                    inputMode="decimal" spellCheck={false} autoComplete="off" placeholder={`e.g. 1500.25 ${asset}`}
                    aria-invalid={amount !== '' && !amountOk} />
                </div>
                <div className="nt-field">
                  <label className="nt-k" htmlFor="nh-at">When the victim paid, in IST</label>
                  <input id="nh-at" type="datetime-local" className="fld mono" value={at} onChange={(e) => setAt(e.target.value)} />
                </div>
              </div>
              <fieldset className="nt-field">
                <legend className="nt-k">Search either side of that time</legend>
                <div className="nt-seg">
                  {SPANS.map(([h, short, long]) => (
                    <label key={h}>
                      <input type="radio" name="nh-span" checked={span === h} onChange={() => setSpan(h)} aria-label={`${long} either side`} />± {short}
                    </label>
                  ))}
                </div>
                {from && <span className="nt-hint">Searches {ist(from.toISOString())} to {ist(to.toISOString())} IST</span>}
              </fieldset>
              <div className="nh-go">
                {/* aria-disabled while it searches, not disabled: the keyboard stays here for the answer. */}
                <button type="button" ref={goRef} onClick={search} disabled={!ready} aria-disabled={busy || undefined}
                  aria-describedby={missing ? 'nh-missing' : undefined}>
                  {busy ? 'Searching…' : 'Search the wallet'}
                </button>
                {missing && <span id="nh-missing" className="nt-hint">{missing}</span>}
              </div>
              {/* Always in the page, so screen readers hear the answer land; hidden to the eye while empty. */}
              <div role="status" className={`nh-said${outcome ? '' : ' visually-hidden'}`}>
                {error?.status === 403 && <p>Searching a wallet needs the demo code on this site. {error.message} Enter it below to search again.</p>}
                {error && error.status !== 403 && <p>{failure(error)}</p>}
                {result && matches.length > 0 && <p>{plural(matches.length, 'transfer')} of {sought} reached this wallet in the window.</p>}
                {result && matches.length === 0 && (
                  <p>
                    {result.complete
                      ? `No transfer of ${sought} reached this wallet between ${ist(asked.from.toISOString())} and ${ist(asked.to.toISOString())} IST.`
                      : `No transfer of ${sought} was found in what was read.`}
                    {' '}Check the amount to its last decimal and the time, or widen the window. Or start the trace from the wallet without a hash: it follows the wallet's whole recent history.
                  </p>
                )}
                {result?.more_matches && <p>More transfers match than are shown: narrow the window to find the victim's.</p>}
                {result && !result.complete && <p>This wallet is busy: the read did not reach back to the start of the window, so a payment there may be missed.</p>}
              </div>
              {error?.status === 403 && (
                <div className="nh-code">
                  <div className="nt-field">
                    <label className="nt-k" htmlFor="nh-code">Access code</label>
                    <input id="nh-code" ref={codeRef} type="password" className="fld" value={code} onChange={(e) => setCode(e.target.value)}
                      autoComplete="off" spellCheck={false} aria-invalid={Boolean(codeError)} aria-describedby={codeError ? 'nh-code-error' : undefined} />
                  </div>
                  <button type="button" onClick={unlock} disabled={!code.trim()}>Unlock and search again</button>
                  {codeError && <p id="nh-code-error" className="banner warn" role="alert">{codeError}</p>}
                </div>
              )}
              {matches.length > 0 && (
                <ul className="nh-matches" aria-label="Payments that match exactly">
                  {matches.map((m) => {
                    const short = middle(m.tx_hash, 8, 8)
                    const sender = plain(m.from)
                    return (
                      <li key={m.tx_hash} className="nh-match">
                        <span className="nh-when">{ist(m.timestamp)} IST<span className="nt-hint mono">{when(m.timestamp)} UTC</span></span>
                        <span className="mono">{m.amount} {plain(m.asset)}</span>
                        <span className="nt-hint">from <span className="mono" title={sender}>{middle(sender, 10, 8)}</span></span>
                        <span className="mono nt-hint" title={m.tx_hash}>{short}</span>
                        <button type="button" aria-label={`Use this payment ${short}`} onClick={() => { setOpen(false); onPick(m.tx_hash) }}>Use this payment</button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </fieldset>
          )}
        </div>
      )}
    </div>
  )
}

const SearchIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
    <circle cx="5" cy="5" r="3.5" /><path d="M7.6 7.6L10.5 10.5" />
  </svg>
)
