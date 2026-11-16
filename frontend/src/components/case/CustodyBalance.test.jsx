import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import CustodyBalance, { tally } from './CustodyBalance'

// Custody balance check on the Letters tab (backend custody_balance.py): each custody address's
// balance on chain beside the register, said in words. Hidden while the server's flag is off.
const ADDRESS = 'TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU' // the custody address the asset-register tests use
const EVIDENCE = { provider: 'trongrid', request: `GET https://api.trongrid.io/v1/accounts/${ADDRESS}?`, retrieved_at: '2026-11-16T06:00:00Z', sha256: 'c'.repeat(64), bytes: 120, from_cache: false }
const MISMATCH = {
  chain: 'tron', chain_name: 'Tron', address: ADDRESS, asset: 'USDT', asset_ids: ['a1'], wallet_id: null, status: 'mismatch',
  register_amount: '635', chain_amount: '600', difference: '-35', provider: 'trongrid', read_at: '2026-11-16T06:00:00Z',
  reason: 'Mismatch: the chain shows 600 USDT, 35 USDT less than the 635 USDT the register records as held here.', evidence: [EVIDENCE],
}
const CHECK = { check_id: 'k1', case_id: 'c1', checked_at: '2026-11-16T06:00:00Z', checked_by: 'officer-1', results: [MISMATCH], counts: { match: 0, mismatch: 1, unchecked: 0 } }

function api(routes) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const [path] = String(url).replace(/^\/api/, '').split('?')
    calls.push({ method, path })
    const hit = routes[`${method} ${path}`]
    if (!hit) return new Response(JSON.stringify({ detail: 'not stubbed' }), { status: 404 })
    return new Response(JSON.stringify(hit.body), { status: hit.status ?? 200 })
  }))
  return calls
}
const open = () => render(<CustodyBalance result={{ case_id: 'c1' }} />)

describe('the custody balance check', () => {
  it('shows nothing while the server has the check switched off', async () => {
    const calls = api({ 'GET /trace/c1/custody-balance': { body: { enabled: false, check: null } } })
    const { container } = open()
    await waitFor(() => expect(calls.length).toBe(1))
    expect(container).toBeEmptyDOMElement()
  })

  it('says a mismatch in words, with both amounts and the provider evidence', async () => {
    api({ 'GET /trace/c1/custody-balance': { body: { enabled: true, check: CHECK } } })
    open()
    const row = await screen.findByRole('group', { name: `USDT at ${ADDRESS}: Mismatch` })
    expect(within(row).getByText('Mismatch')).toBeInTheDocument()
    expect(within(row).getByText('635 USDT')).toBeInTheDocument()
    expect(within(row).getByText('600 USDT')).toBeInTheDocument()
    expect(within(row).getByText(/35 USDT less than the 635 USDT/)).toBeInTheDocument()
    expect(within(row).getByText('c'.repeat(64))).toBeInTheDocument()
    expect(screen.getByText('Custody balances · 1 mismatch')).toBeInTheDocument()
  })

  it('runs a check on request and shows a refusal from the server', async () => {
    const calls = api({
      'GET /trace/c1/custody-balance': { body: { enabled: true, check: null, can_check: true, check_note: '' } },
      'POST /trace/c1/custody-balance': { status: 403, body: { detail: 'Sign in as an officer to record or change a custody wallet or its signing log.' } },
    })
    open()
    await userEvent.click(await screen.findByRole('button', { name: 'Check balances on chain now' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Sign in as an officer')
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(['GET /trace/c1/custody-balance', 'POST /trace/c1/custody-balance'])
  })

  it('offers no button to a caller the server would refuse, and says why', async () => {
    const calls = api({ 'GET /trace/c1/custody-balance': { body: { enabled: true, check: CHECK, can_check: false, check_note: 'Sign in as an officer to read the custody balances on chain.' } } })
    open()
    expect(await screen.findByText('Sign in as an officer to read the custody balances on chain.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Check balances on chain now' })).not.toBeInTheDocument()
    expect(screen.getByRole('group', { name: `USDT at ${ADDRESS}: Mismatch` })).toBeInTheDocument() // the last run still shows
    expect(calls.map((c) => c.method)).toEqual(['GET'])
  })

  it('counts results without the zeros', () => {
    expect(tally({ match: 2, mismatch: 0, unchecked: 1 })).toBe('2 match · 1 not checked')
    expect(tally({ match: 0, mismatch: 2, unchecked: 0 })).toBe('2 mismatches')
    expect(tally({})).toBe('nothing to check')
  })
})
