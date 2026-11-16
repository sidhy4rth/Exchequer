import { useEffect, useState } from 'react'
import { fetchSopSummaryOffered } from '../api'
import { NCRP_HELPLINE, NCRP_PORTAL_URL } from '../ncrp'
import './NcrpPortalLinks.css'

// Feature 8: beside an NCRP number, the portal and the helpline such numbers
// come from (sources in ncrp.js). Behind EXCHEQUER_SOP_SUMMARY, as the rest
// of feature 8's officer pages: GET /sop-summary answers 404 with it off, and
// then nothing shows. It takes no number, so nothing about the complaint can
// reach either link or the government site.
export default function NcrpPortalLinks() {
  const [offered, setOffered] = useState(false)
  useEffect(() => {
    let live = true
    fetchSopSummaryOffered().then((d) => live && setOffered(Boolean(d?.enabled))).catch(() => {})
    return () => { live = false }
  }, [])
  if (!offered) return null
  return (
    <p className="ncrp-links note">
      <a href={NCRP_PORTAL_URL} target="_blank" rel="noopener noreferrer">
        National Cybercrime Reporting Portal, cybercrime.gov.in (opens the government site in a new tab)
      </a>
      <a href={`tel:${NCRP_HELPLINE}`}>Call {NCRP_HELPLINE}, the National Helpline for cyber financial fraud</a>
    </p>
  )
}
