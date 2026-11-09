import { Link } from 'react-router-dom'
import { Icon, OfficialLinks, usePageTitle } from '../parts.jsx'

// C1: the official ways to report come first, then three next steps.
const STEPS = [
  { to: '/right-now', icon: 'steps', title: 'What to do right now', sub: "three do's and three don'ts, two minutes" },
  { to: '/report', icon: 'search', title: 'Find your payment', sub: 'and build your complaint · coming soon' },
  { to: '/my-case', icon: 'case', title: 'Track my complaint', sub: 'with your NCRP number · coming soon' },
]

export default function Home() {
  usePageTitle()
  return (
    <div className="home">
      <section className="hero" aria-labelledby="hero-title">
        <h1 id="hero-title">Lost money? The first hours matter most.</h1>
        <p className="lede">
          Report it now, and keep everything the scammers sent you. This guide is free, and no one
          here will ever ask you for money.
        </p>
        <OfficialLinks />
      </section>
      <section className="steps" aria-labelledby="steps-title">
        <h2 id="steps-title" className="eyebrow">Start here</h2>
        <ul className="rows">
          {STEPS.map(({ to, icon, title, sub }) => (
            <li key={to}>
              <Link className="row" to={to}>
                <span className="row-icon"><Icon name={icon} size={18} /></span>
                <span className="row-text"><span className="row-title">{title}</span>
                  <span className="row-sub">{sub}</span></span>
                <Icon name="next" size={14} />
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
