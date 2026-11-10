import { useEffect, useRef } from 'react'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { Icon, PortalLink } from './parts.jsx'
import Home from './pages/Home.jsx'
import Find from './pages/Find.jsx'
import Learn from './pages/Learn.jsx'
import Pack from './pages/Pack.jsx'
import RightNow from './pages/RightNow.jsx'
import { ComingSoon, NotFound } from './pages/Soon.jsx'

// One nav for both sizes: a bottom tab bar on a phone, pills in the header
// on a laptop (styles.css). `also` keeps a tab lit on the pages under it.
const TABS = [
  { to: '/', label: 'Home', icon: 'home', also: ['/right-now'] },
  { to: '/report', label: 'Report', icon: 'report', also: ['/report/pack'] },
  { to: '/my-case', label: 'My case', icon: 'case' },
  { to: '/learn', label: 'Learn', icon: 'learn' },
]

function Tab({ to, label, icon, also = [] }) {
  const { pathname } = useLocation()
  const lit = pathname === to || also.includes(pathname)
  return (
    <Link to={to} className={lit ? 'tab is-on' : 'tab'} aria-current={pathname === to ? 'page' : undefined}>
      <Icon name={icon} size={18} />{label}
    </Link>
  )
}

function Layout({ children }) {
  const { pathname } = useLocation()
  const main = useRef(null)
  const shown = useRef(pathname)
  // After a move between pages, start at the top and put focus on the new
  // page, so a screen reader reads it instead of staying on the old link.
  useEffect(() => {
    if (shown.current === pathname) return
    shown.current = pathname
    document.documentElement.scrollTop = 0
    main.current?.focus({ preventScroll: true })
  }, [pathname])

  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <header className="top">
        <Link to="/" className="brand"><span className="brand-name">Exchequer</span>
          <span className="brand-tag">for citizens</span></Link>
        <nav aria-label="Main" className="tabs">{TABS.map((tab) => <Tab key={tab.to} {...tab} />)}</nav>
        <a className="call" href="tel:1930"><Icon name="phone" size={14} /><span className="sr-only">Call </span>1930</a>
      </header>
      <main id="main" ref={main} tabIndex={-1}>{children}</main>
      <footer className="foot">
        <ul className="safety" role="list" aria-label="Stay safe">
          <li><Icon name="ban" />Police never charge a fee to recover money.</li>
          <li><Icon name="ban" />We never ask for your seed phrase or private key.</li>
        </ul>
        <p className="note">
          Exchequer is not a government or police site. It helps you prepare a complaint. To report a
          crime, call the National Cyber Crime Helpline on <a href="tel:1930">1930</a> or use the
          National Cyber Crime Reporting Portal, <PortalLink>cybercrime.gov.in</PortalLink>.
        </p>
      </footer>
    </div>
  )
}

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/right-now" element={<RightNow />} />
        <Route path="/report" element={<Find />} />
        <Route path="/report/pack" element={<Pack />} />
        <Route path="/my-case" element={
          <ComingSoon title="Track my complaint">
            Here you will sign in with your NCRP number to follow your complaint and read messages
            from your officer. This part is not switched on yet.
          </ComingSoon>} />
        <Route path="/learn" element={<Learn />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  )
}
