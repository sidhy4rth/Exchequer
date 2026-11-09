import { useEffect } from 'react'

// Line icons on a 16px grid, drawn in the text colour. Decorative only: every
// icon sits beside words that say the same thing.
export const PATHS = {
  phone: 'M3 2h3l1.5 3.5-2 1.2a8 8 0 0 0 3.8 3.8l1.2-2L14 10v3a1 1 0 0 1-1 1A11 11 0 0 1 2 3a1 1 0 0 1 1-1z',
  out: 'M5 11l6-6M6 5h5v5',
  next: 'M6 3l5 5-5 5',
  back: 'M10 3L5 8l5 5',
  arrow: 'M2 8h11M9 4l4 4-4 4',
  ban: 'M8 1.8a6.2 6.2 0 1 0 0 12.4A6.2 6.2 0 0 0 8 1.8zM4 12L12 4',
  cross: 'M5 5l6 6M11 5l-6 6',
  home: 'M2 7.5L8 2.5l6 5V14H2zM6.5 14v-4h3v4',
  report: 'M2.5 2.5h8l3 3v8h-11zM8 6.5v4M6 8.5h4',
  case: 'M3 3h10v10H3zM5.5 8l1.8 1.8 3.4-3.6',
  learn: 'M2 4l6-2.5L14 4 8 6.5zM4.5 5.3V10c1.8 1.7 5.2 1.7 7 0V5.3',
  steps: 'M3 4h10M3 8h10M3 12h5M10.5 11.5l1.5 1.5 3-3',
  search: 'M7 2a5 5 0 1 0 0 10A5 5 0 0 0 7 2zM10.6 10.6L14.5 14.5',
}

export function Icon({ name, size = 16 }) {
  return (
    <svg aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 16 16"
      fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[name]} />
    </svg>
  )
}

export function usePageTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} · Exchequer for citizens` : 'Exchequer for citizens'
  }, [title])
}

/** The National Cyber Crime Reporting Portal, opened in a new tab. */
export function PortalLink({ className, children }) {
  return (
    <a className={className} href="https://cybercrime.gov.in" target="_blank" rel="noopener noreferrer">
      {children}<Icon name="out" size={14} /><span className="sr-only"> (opens in a new tab)</span>
    </a>
  )
}

/** The two official ways to report: the 1930 helpline and the portal. */
export function OfficialLinks() {
  return (
    <div className="official">
      <a className="btn btn-call" href="tel:1930"><Icon name="phone" size={18} />Call 1930</a>
      <PortalLink className="btn btn-line">Report at cybercrime.gov.in</PortalLink>
    </div>
  )
}
