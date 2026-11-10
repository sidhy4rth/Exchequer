import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import OpenRequests from './OpenRequests'

// The home page's open requests include urgent letters still waiting on a
// second officer's sign-off, so the caption must not say only "drafted, sent".
describe('the open requests card', () => {
  it('names the sign-off states it lists in its caption', async () => {
    const rows = [
      { request_id: 'r1', case_id: 'c1', recipient: 'Binance', status: 'awaiting_signoff', days_waiting: null },
      { request_id: 'r2', case_id: 'c1', recipient: 'Tether', status: 'sent', days_waiting: 2 },
    ]
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ count: 2, requests: rows }))))
    render(<MemoryRouter><OpenRequests /></MemoryRouter>)
    expect(await screen.findByText('Binance')).toBeInTheDocument()
    expect(screen.getByText(/· this browser only$/)).toHaveTextContent('waiting on a sign-off or a reply · this browser only')
  })
})
