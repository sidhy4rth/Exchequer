import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CaseBundleButton from './CaseBundleButton'

// The case bundle (backend case_bundle.py): one zip of the case, with a
// manifest of hashes; a server without it answers 404 and no button shows.
const FILES = ['report.txt', 'report.pdf', 'exhibits.csv', 'MANIFEST.txt']

function serve(routes) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    const path = String(url).replace(/^\/api/, '')
    calls.push(path)
    const hit = routes[path]
    return hit ? hit() : new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 })
  }))
  return calls
}
const probe = () => new Response(JSON.stringify({ enabled: true, files: FILES }), { status: 200 })

afterEach(() => { vi.unstubAllGlobals(); delete URL.createObjectURL; delete URL.revokeObjectURL })

describe('the case bundle button', () => {
  it('downloads the zip for this case', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:bundle')
    URL.revokeObjectURL = vi.fn()
    const calls = serve({ '/case-bundle': probe, '/trace/case-1/bundle': () => new Response('PK', { status: 200 }) })
    const user = userEvent.setup()
    render(<CaseBundleButton caseId="case-1" />)
    await user.click(await screen.findByRole('button', { name: /Case bundle/ }))
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
    expect(calls).toEqual(['/case-bundle', '/trace/case-1/bundle'])
  })

  it('shows nothing where the server has bundles switched off', async () => {
    const calls = serve({})
    const { container } = render(<CaseBundleButton caseId="case-1" />)
    await waitFor(() => expect(calls).toEqual(['/case-bundle']))
    expect(container).toBeEmptyDOMElement()
  })

  it("says why when the server refuses another browser's case", async () => {
    serve({ '/case-bundle': probe, '/trace/case-1/bundle': () => new Response(JSON.stringify(
      { detail: 'Only the browser or unit that traced this case can download its bundle.' }), { status: 403 }) })
    const user = userEvent.setup()
    render(<CaseBundleButton caseId="case-1" />)
    await user.click(await screen.findByRole('button', { name: /Case bundle/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Only the browser or unit that traced this case')
  })

  it('after a 403, disables the button rather than inviting the same refusal again', async () => {
    const calls = serve({ '/case-bundle': probe, '/trace/case-1/bundle': () => new Response(JSON.stringify(
      { detail: 'Only the browser or unit that traced this case can download its bundle.' }), { status: 403 }) })
    const user = userEvent.setup()
    render(<CaseBundleButton caseId="case-1" />)
    await user.click(await screen.findByRole('button', { name: /Case bundle/ }))
    await screen.findByRole('alert')
    expect(screen.getByRole('button', { name: /Case bundle/ })).toBeDisabled()
    expect(calls.filter((c) => c.endsWith('/bundle'))).toHaveLength(1)
  })

  it('shows no button when the server already withheld this case\'s particulars from this browser', async () => {
    // GET /trace/{id} names what it withheld (case_privacy.py) only for a reader who did not trace the case,
    // and that reader's bundle is refused: nothing new is asked of the server to know it.
    const calls = serve({ '/case-bundle': probe })
    const { container } = render(<CaseBundleButton caseId="case-1" redacted={['intake.ncrp_ack']} />)
    await waitFor(() => expect(calls).toEqual(['/case-bundle']))
    await new Promise((r) => setTimeout(r, 0))
    expect(container).toBeEmptyDOMElement()
  })
})
