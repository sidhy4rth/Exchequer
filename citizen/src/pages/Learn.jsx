import { Link } from 'react-router-dom'
import { Icon, usePageTitle } from '../parts.jsx'

// C8: five common crypto scams in India, their warning signs and what to do.
const SCAMS = [
  { icon: 'trend', title: 'Trading apps that "cannot lose"',
    signs: ['"guaranteed" or very high returns', 'an app shared in a WhatsApp or Telegram group',
      'profits you can see but cannot withdraw', 'a "tax" or fee before you can withdraw'],
    todo: 'Pay nothing more, not even a fee to withdraw. Keep the screenshots and report it.' },
  { icon: 'case', title: 'Paid tasks, then deposits',
    signs: ['paid a little to like videos or rate hotels', 'moved to a Telegram group with a "mentor"',
      'a "VIP" task that needs a USDT deposit', 'earnings locked until you pay in more'],
    todo: 'A real job never asks you to pay to work. Stop at the first request for a deposit.' },
  { icon: 'heart', title: 'A friend online who turns to investing',
    signs: ['met online, or after a "wrong number" message', 'never meets you in person',
      'shows off profits on a trading app', 'pushes you to invest more, or to borrow'],
    todo: 'Never invest through someone you have only met online, however close you feel.' },
  { icon: 'shield', title: 'Fake customer care and "recovery agents"',
    signs: ['a "helpline" number from a search or a post', 'asks you to install a screen-sharing app',
      'asks for your seed phrase, OTP or PIN', 'offers recovery for a fee after a scam'],
    todo: 'Contact a company only through its own app or website. Never pay anyone to recover money.' },
  { icon: 'phone', title: 'Fake police, customs or courier calls ("digital arrest")',
    signs: ['a parcel in your name said to hold drugs', 'a video call from someone in uniform',
      'told to stay on the call and tell no one', 'asked to move money to "clear your name"'],
    todo: 'Real officers never arrest anyone over a video call or ask for money. Hang up and call 1930.' },
]

export default function Learn() {
  usePageTitle('Know the scams')
  return (
    <>
      <div className="title">
        <h1>Know the scams</h1>
        <p className="eyebrow">Five common scams, and the warning signs before you pay</p>
      </div>
      <div className="scams">
        {SCAMS.map(({ icon, title, signs, todo }, i) => (
          <article className="card" key={title} aria-labelledby={`scam-${i}`}>
            <div className="card-head">
              <span className="row-icon"><Icon name={icon} size={18} /></span>
              <h2 id={`scam-${i}`}>{title}</h2>
            </div>
            <ul className="chips" role="list" aria-label="Warning signs">
              {signs.map((sign) => <li key={sign}>{sign}</li>)}
            </ul>
            <p className="todo"><strong>What to do:</strong> {todo}</p>
          </article>
        ))}
        <section className="card paid" aria-labelledby="paid-title">
          <h2 id="paid-title">Already paid?</h2>
          <p className="todo">The first hours matter most.</p>
          <Link className="btn btn-go" to="/right-now">What to do right now<Icon name="arrow" /></Link>
        </section>
      </div>
    </>
  )
}
