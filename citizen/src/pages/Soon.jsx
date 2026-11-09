import { Link } from 'react-router-dom'
import { Icon, OfficialLinks, usePageTitle } from '../parts.jsx'

/** A page whose part of the site is not built yet, with the official ways to report meanwhile. */
export function ComingSoon({ title, children }) {
  usePageTitle(title)
  return (
    <div className="soon">
      <p className="tag">Coming soon</p>
      <h1>{title}</h1>
      <p>{children}</p>
      <p>Meanwhile, report to the National Cyber Crime Helpline on 1930 or on the National Cyber Crime
        Reporting Portal:</p>
      <OfficialLinks />
      <Link className="more" to="/right-now">What to do right now<Icon name="arrow" /></Link>
    </div>
  )
}

export function NotFound() {
  usePageTitle('Page not found')
  return (
    <div className="soon">
      <h1>Page not found</h1>
      <p>There is nothing at this address.</p>
      <Link className="more" to="/">Go to the home page<Icon name="arrow" /></Link>
    </div>
  )
}
