import { Link } from 'react-router-dom'
import { Icon, usePageTitle } from '../parts.jsx'

// C2: three things to do and three not to do, in plain words.
const DO = [
  ['Call 1930 now, or report online', 'The sooner you report, the better the chance the money can be frozen.'],
  ['Keep the evidence', 'Screenshots, chats, the app or website name, UPI IDs, wallet addresses and phone numbers.'],
  ['Find your payment hash', "It proves exactly which payment was yours. Your wallet or exchange app shows it in the payment's details, sometimes as a TxID."],
]
const DONT = [
  ["Don't send more money", 'A "tax" or "fee" to unlock your withdrawal is part of the scam.'],
  ['Don\'t pay a "recovery agent"', 'Anyone who contacts you offering to get your money back for a fee is running a second scam. Police never charge.'],
  ["Don't delete the chats or the app", 'They are evidence. Keep them, even if the app stops working.'],
]

function Items({ id, title, items, mark }) {
  return (
    <section className={id}>
      <h2 id={`${id}-title`}>{title}</h2>
      <ol className="items" aria-labelledby={`${id}-title`}>
        {items.map(([head, text], i) => (
          <li className="item" key={head}>
            <span className="mark" aria-hidden="true">{mark ? <Icon name={mark} size={12} /> : i + 1}</span>
            <span><strong className="item-title">{head}</strong><span className="item-text">{text}</span></span>
          </li>
        ))}
      </ol>
    </section>
  )
}

export default function RightNow() {
  usePageTitle('Right now')
  return (
    <>
      <div className="page-head">
        <Link to="/" className="back" aria-label="Back to home"><Icon name="back" /></Link>
        <div><p className="eyebrow">Before anything else</p><h1>Right now</h1></div>
      </div>
      <div className="dodont">
        <Items id="do" title="Do" items={DO} />
        <Items id="dont" title="Don't" items={DONT} mark="cross" />
      </div>
      <div className="next">
        <p>Next: find the exact payment you made.</p>
        <Link className="btn btn-go" to="/report">Find your payment<Icon name="arrow" /></Link>
      </div>
    </>
  )
}
