import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import NcrpPortalLinks from './NcrpPortalLinks'
import { NCRP_HELPLINE, NCRP_PORTAL_URL } from '../ncrp'
import { stubFetch } from '../test/setup'

// Feature 8: the portal and 1930 links beside an NCRP number, only with
// EXCHEQUER_SOP_SUMMARY on (GET /sop-summary), and never carrying the number.

afterEach(() => vi.unstubAllGlobals())

describe('the NCRP portal and 1930 links', () => {
  it('shows nothing with the flag off, and asks only whether it is on', async () => {
    const fetch = stubFetch({})
    const { container } = render(<NcrpPortalLinks />)
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    expect(String(fetch.mock.calls[0][0])).toMatch(/\/sop-summary$/)
    expect(container).toBeEmptyDOMElement()
  })

  it('links the portal home page in a new tab, saying so, and the 1930 helpline', async () => {
    stubFetch({ '/sop-summary': { body: { enabled: true } } })
    render(<NcrpPortalLinks />)
    const portal = await screen.findByRole('link', { name: /National Cybercrime Reporting Portal, cybercrime\.gov\.in \(opens the government site in a new tab\)/ })
    expect(portal).toHaveAttribute('href', 'https://cybercrime.gov.in/')
    expect(portal).toHaveAttribute('target', '_blank')
    expect(portal).toHaveAttribute('rel', 'noopener noreferrer')
    const helpline = screen.getByRole('link', { name: /^Call 1930, the National Helpline/ })
    expect(helpline).toHaveAttribute('href', 'tel:1930')
  })

  it('uses the sourced values only', () => {
    expect(NCRP_PORTAL_URL).toBe('https://cybercrime.gov.in/')
    expect(NCRP_HELPLINE).toBe('1930')
  })
})
