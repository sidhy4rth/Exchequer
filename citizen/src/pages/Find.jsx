import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { NETWORK_KEYS, amountText, checkPayment, istTime, refusal } from '../api.js'
import { addToPack } from '../draft.js'
import { checkHash } from '../hash.js'
import { Icon, ReportSteps, usePageTitle } from '../parts.jsx'

// C3: where the transaction hash is, in words and a sketch of the screens,
// and a box that checks its shape on the device. C4: then, if the citizen
// asks, that one payment read from the blockchain (GET /api/payment): who
// paid whom, how much and when, and nothing after it.
const GUIDES = {
  exchange: ['Exchange app', [
    ['Open the withdrawal history', 'Look under Assets, Wallet or History, then pick Withdrawals.'],
    ['Open the payment', 'Pick the one with the amount and date you sent.'],
    ['Copy the hash', 'Copy the long code called Transaction ID, TxID or Hash. "Internal transfer" means '
      + 'it never left the exchange: note its transfer ID instead.'],
  ]],
  wallet: ['Wallet app', [
    ['Open the coin you sent', 'For example USDT, then its list of payments.'],
    ['Open the payment', 'Pick the one sent out, with the amount and date you paid.'],
    ['Copy the hash', 'In its details, copy the Transaction ID or Hash. If you see only "View on block '
      + 'explorer", open it: the hash is the long code at the top.'],
  ]],
  browser: ['Browser wallet', [
    ['Open Activity', "Click the wallet's icon in your browser, then its Activity or History tab."],
    ['Open the payment', 'Pick the one with the amount and date you paid.'],
    ['Copy the hash', 'Use "Copy transaction ID", or open it on the block explorer and copy the long code.'],
  ]],
}

const or = (items) => new Intl.ListFormat('en', { type: 'disjunction' }).format(items)
const REASONS = {
  empty: 'Paste the hash in the box first.',
  address: 'This looks like a wallet address, not a payment. Open the payment itself and copy its hash.',
  chars: 'On Tron, Ethereum and the other networks this site checks, a hash has only the digits 0 to 9 and '
    + 'the letters a to f, and this has other characters. Copy just the long code, without the words or '
    + 'link around it. An order ID or a UPI reference is a different number.',
  length: ({ length }) => `This has ${length} characters, and a hash on those networks has 64 (not `
    + 'counting a 0x at the start). Check that you copied all of it.',
}
// The check knows only the networks the site traces; a real hash from any
// other one can have another shape, and must not be called wrong.
const ELSEWHERE = 'If the payment was on another network, such as Bitcoin or Solana, its hash can look different: '
  + 'keep the hash as you copied it.'

function Verdict(result) {
  if (result.reason === 'empty') return <p>{REASONS.empty}</p>
  if (!result.ok) {
    const reason = REASONS[result.reason]
    return (<>
      <p className="verdict bad"><Icon name="cross" />{result.reason === 'address'
        ? 'This does not look like a transaction hash.' : 'This is not the shape of a Tron or Ethereum-style hash.'}</p>
      <p>{typeof reason === 'function' ? reason(result) : reason}</p>
      {result.reason !== 'address' && <p>{ELSEWHERE}</p>}
    </>)
  }
  return (<>
    <p className="verdict ok"><Icon name="check" />This has the shape of a transaction hash.</p>
    {result.extracted && <p>We found it inside the words or link you pasted:</p>}
    <code className="hash">{result.hash}</code>
    <p>On the networks this site checks, it could be a payment on {or(result.networks)}. A hash from another
      network, such as Bitcoin, can look the same. The network your app showed beside the payment, such as
      TRC20 (Tron), ERC20 (Ethereum) or BEP20 (BNB Smart Chain), says which.</p>
    <p>If you copied it from the payment's details, keep it with your evidence, and give it when you
      report on 1930 or at cybercrime.gov.in.</p>
    <p>A private key looks the same. If you copied this from a "private key" or "export" screen instead,
      do not share it with anyone.</p>
  </>)
}

/** C4: the citizen's own payment, as the blockchain has it, to confirm or not. */
function Payment({ p, onNo }) {
  const navigate = useNavigate()
  // Focus moves here, so a screen reader reads what was found and the question.
  const head = useRef(null)
  useEffect(() => head.current?.focus(), [])
  return (
    <section className="found" aria-labelledby="found-title">
      <h3 id="found-title" ref={head} tabIndex={-1} className="verdict ok"><Icon name="check" />Found on the blockchain</h3>
      {!p.succeeded && <p className="err">This payment failed on the blockchain: the money did not move.</p>}
      <p className="found-amount"><span className="amt">{amountText(p.amount)}</span> <span>{p.token}</span></p>
      <p>{istTime(p.time)} · {p.network}</p>
      <div className="ends">
        <div className="end"><span className="end-name">From your wallet</span><code>{p.from}</code></div>
        <div className="end to"><span className="end-name">The wallet you paid</span><code>{p.to}</code></div>
      </div>
      <div className="confirm" role="group" aria-labelledby="mine-title">
        <p id="mine-title">Is this your payment?</p>
        <button type="button" className="btn btn-go" onClick={() => { addToPack(p); navigate('/report/pack') }}>
          Yes, it's mine</button>
        <button type="button" className="btn btn-line" onClick={onNo}>No, look again</button>
      </div>
      <p className="hint">We only show your own payment. Where the money went next is for the investigating
        officer, so the people who took it are not warned.</p>
    </section>
  )
}

function Lookup({ hash, networks, found, setFound, onNo }) {
  const [network, setNetwork] = useState(NETWORK_KEYS[networks[0]])
  const [alert, setAlert] = useState('')
  const [busy, setBusy] = useState(false)
  async function look(e) {
    e.preventDefault()
    setBusy(true)
    setAlert('')
    setFound(null)
    const res = await checkPayment(network, hash)
    setBusy(false)
    if (res.ok && res.data.payment) setFound(res.data.payment)
    else setAlert(refusal(res))
  }
  return (<>
    <form className="lookup" onSubmit={look}>
      <div className="field">
        <label htmlFor="network">Network</label>
        <select id="network" value={network} onChange={(e) => { setNetwork(e.target.value); setFound(null) }}>
          {networks.map((name) => <option key={name} value={NETWORK_KEYS[name]}>{name}</option>)}
        </select>
      </div>
      <button className="btn btn-go" type="submit" disabled={busy}>Check on the blockchain<Icon name="arrow" /></button>
    </form>
    {alert && <p className="err" role="alert">{alert}</p>}
    {found && <Payment p={found} onNo={onNo} />}
  </>)
}

function HashCheck({ found, setFound }) {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const box = useRef(null)
  return (
    <section className="card check" aria-labelledby="check-title">
      <h2 id="check-title">Check the hash</h2>
      <form className="check-form" onSubmit={(e) => { e.preventDefault(); setFound(null); setResult(checkHash(text)) }}>
        <label htmlFor="hash">Paste it here</label>
        <textarea id="hash" ref={box} rows={3} value={text} spellCheck={false} autoCapitalize="off" autoComplete="off"
          autoCorrect="off" aria-describedby="hash-hint key-note check-note"
          aria-invalid={(result?.ok === false && result.reason !== 'empty') || undefined}
          onChange={(e) => { setText(e.target.value); setResult(null); setFound(null) }} />
        <p className="hint" id="key-note">A transaction hash is safe to share. A private key or a seed phrase
          is not: never paste one here or give it to anyone, because whoever has it can take what is left in
          the wallet.</p>
        <button className="btn btn-go" type="submit">Check this hash<Icon name="arrow" /></button>
      </form>
      <div className="result" role="status">{result && <Verdict {...result} />}</div>
      {result?.ok && <Lookup key={result.hash} hash={result.hash} networks={result.networks} found={found}
        setFound={setFound} onNo={() => { setFound(null); box.current?.focus() }} />}
      <p className="hint" id="check-note">Checking the shape runs on your device and sends nothing. Check on the
        blockchain sends only the hash and the network, to look up that one payment.</p>
      <details className="fallback">
        <summary>Can't find it? Search by amount and date</summary>
        <p><span className="tag">Coming later</span> You will give the wallet you paid, the amount and the date,
          and we will look for that one payment only. Until then, note all three from your app or the chats,
          and give them when you report.</p>
      </details>
    </section>
  )
}

export default function Find() {
  usePageTitle('Find your payment')
  const [source, setSource] = useState('exchange')
  const [found, setFound] = useState(null)
  return (
    <>
      <div className="page-head">
        <Link to="/" className="back" aria-label="Back to home"><Icon name="back" /></Link>
        <div><p className="eyebrow">Report</p><h1>Find your payment</h1></div>
      </div>
      <ReportSteps at={found ? 1 : 0} />
      <div className="find">
        <section className="guide-part" aria-labelledby="guide-title">
          <h2 id="guide-title">Where to find the transaction hash</h2>
          <fieldset className="picks">
            <legend>Where did you send the money from?</legend>
            {Object.entries(GUIDES).map(([key, [label]]) => (
              <label className="pick" key={key}>
                <input type="radio" name="source" value={key} checked={source === key}
                  onChange={() => setSource(key)} /><span>{label}</span>
              </label>
            ))}
          </fieldset>
          <ol className="guide" role="list" aria-labelledby="guide-title">
            {GUIDES[source][1].map(([head, text], i) => (
              <li key={head}>
                <span className="sketch" aria-hidden="true">
                  {[0, 1, 2, 3].map((bar) => <i key={bar} className={bar === [0, 2, 3][i] ? 'lit' : undefined} />)}
                </span>
                <span><strong className="item-title">{head}</strong><span className="item-text">{text}</span></span>
              </li>
            ))}
          </ol>
          <p className="hint" id="hash-hint">It may be called Transaction ID, TxID or Hash: a long string of
            letters and numbers.</p>
        </section>
        <HashCheck found={found} setFound={setFound} />
      </div>
      <Link className="more" to="/report/pack">Next: your complaint pack<Icon name="arrow" /></Link>
    </>
  )
}
