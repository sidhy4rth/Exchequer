import { useState } from 'react'
import { Link } from 'react-router-dom'
import { checkHash } from '../hash.js'
import { Icon, ReportSteps, usePageTitle } from '../parts.jsx'

// C3: where the transaction hash is, in words and a sketch of the screens,
// and a box that checks its shape on the device. Confirming the payment on
// the blockchain comes later.
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
  chars: 'A hash has only the digits 0 to 9 and the letters a to f, and this has other characters. Copy '
    + 'just the long code, without the words or link around it. An order ID or a UPI reference is a '
    + 'different number.',
  length: ({ length }) => `This has ${length} characters, and a hash has 64 (not counting a 0x at the `
    + 'start). Check that you copied all of it.',
}

function Verdict(result) {
  if (result.reason === 'empty') return <p>{REASONS.empty}</p>
  if (!result.ok) {
    const reason = REASONS[result.reason]
    return (<>
      <p className="verdict bad"><Icon name="cross" />This does not look like a transaction hash.</p>
      <p>{typeof reason === 'function' ? reason(result) : reason}</p>
    </>)
  }
  return (<>
    <p className="verdict ok"><Icon name="check" />This has the shape of a transaction hash.</p>
    {result.extracted && <p>We found it inside the words or link you pasted:</p>}
    <code className="hash">{result.hash}</code>
    <p>It could be a payment on {or(result.networks)}. The network your app showed beside the payment,
      such as TRC20 (Tron), ERC20 (Ethereum) or BEP20 (BNB Smart Chain), says which.</p>
    <p>If you copied it from the payment's details, keep it with your evidence, and give it when you
      report on 1930 or at cybercrime.gov.in.</p>
    <p>A private key looks the same. If you copied this from a "private key" or "export" screen instead,
      do not share it with anyone.</p>
  </>)
}

function HashCheck() {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  return (
    <section className="card check" aria-labelledby="check-title">
      <h2 id="check-title">Check the hash</h2>
      <form className="check-form" onSubmit={(e) => { e.preventDefault(); setResult(checkHash(text)) }}>
        <label htmlFor="hash">Paste it here</label>
        <textarea id="hash" rows={3} value={text} spellCheck={false} autoCapitalize="off" autoComplete="off"
          autoCorrect="off" aria-describedby="hash-hint key-note check-note"
          aria-invalid={(result?.ok === false && result.reason !== 'empty') || undefined}
          onChange={(e) => { setText(e.target.value); setResult(null) }} />
        <p className="hint" id="key-note">A transaction hash is safe to share. A private key or a seed phrase
          is not: never paste one here or give it to anyone, because whoever has it can take what is left in
          the wallet.</p>
        <button className="btn btn-go" type="submit">Check this hash<Icon name="arrow" /></button>
      </form>
      <div className="result" role="status">{result && <Verdict {...result} />}</div>
      <p className="hint" id="check-note">This check runs on your device and sends nothing. It looks only at
        the shape of the hash. Confirming the payment on the blockchain will be switched on later.</p>
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
  return (
    <>
      <div className="page-head">
        <Link to="/" className="back" aria-label="Back to home"><Icon name="back" /></Link>
        <div><p className="eyebrow">Report</p><h1>Find your payment</h1></div>
      </div>
      <ReportSteps at={0} />
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
        <HashCheck />
      </div>
      <Link className="more" to="/report/pack">Next: your complaint pack<Icon name="arrow" /></Link>
    </>
  )
}
