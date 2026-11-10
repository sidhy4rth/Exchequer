import { Link } from 'react-router-dom'
import { Icon, usePageTitle } from '../parts.jsx'

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
