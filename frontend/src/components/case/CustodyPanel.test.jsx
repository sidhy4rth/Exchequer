import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import CustodyPanel, { canApprove, parseSigners } from './CustodyPanel'

// Custody wallets on the Letters tab (backend custody.py, custody_log.py): the
// case's multisig wallets, their signers by name, and the signing log. Hidden
// while the server's flag is off; never asks for a key.
const ADDRESS = 'TXgo8gtf6bPQURfHftYWPRv1QPuLQaBBVU' // the custody address the asset-register tests use
const SIGNERS = [{ name: 'Insp. Rao', role: 'Inspector', unit: 'Cyber Cell' }, { name: 'SI Iyer', role: '', unit: '' }, { name: 'SI Pal', role: '', unit: '' }]
const MOVE = {
  movement_id: 'm1', wallet_id: 'w1', kind: 'release', asset: 'USDT', amount: '635', destination: 'TA6SbszfFYC7NYt48viCM9LMD5F5E1Gbi8',
  order_ref: 'Order of 13 Nov', proposed_by: 'Insp. Rao', status: 'proposed', approvals: [{ signer: 'SI Iyer', at: '2026-11-14T05:00:00Z', recorded_by: 'officer-1' }],
  approvals_needed: 1, threshold: 2, tx_hash: '', history: [],
}
const WALLET = {
  wallet_id: 'w1', case_id: 'c1', chain: 'tron', chain_name: 'Tron', address: ADDRESS, scheme: 'Tron multi-sign permission',
  threshold: 2, signer_count: 3, signers: SIGNERS, proposer_may_sign: false, set_up_by: 'Insp. Rao', set_up_on: '2026-11-10',
  asset_ids: [], notes: '', history: [], movements: [MOVE],
}

function api(routes) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const [path] = String(url).replace(/^\/api/, '').split('?')
    let body = init.body
    try { body = JSON.parse(body) } catch { /* none */ }
    calls.push({ method, path, body })
    const hit = routes[`${method} ${path}`]
    if (!hit) return new Response(JSON.stringify({ detail: 'not stubbed' }), { status: 404 })
    const { status = 200, body: out } = typeof hit === 'function' ? hit(body) : hit
    return new Response(JSON.stringify(out), { status })
  }))
  return calls
}

const NO_ASSETS = { 'GET /trace/c1/assets': { body: { assets: [] } } }
const open = () => render(<CustodyPanel result={{ case_id: 'c1' }} />)

describe('the custody wallets panel', () => {
  it('shows nothing while the server has the feature switched off', async () => {
    const calls = api({ ...NO_ASSETS, 'GET /trace/c1/custody': { body: { enabled: false, wallets: [] } } })
    const { container } = open()
    await waitFor(() => expect(calls.some((c) => c.path === '/trace/c1/custody')).toBe(true))
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the wallet, its threshold, its signers by name and the signing log', async () => {
    api({ ...NO_ASSETS, 'GET /trace/c1/custody': { body: { enabled: true, wallets: [WALLET], chains: { tron: 'Tron' } } } })
    open()
    expect(await screen.findByText('2 of 3 signers')).toBeInTheDocument()
    expect(screen.getByText(/Insp. Rao, Inspector, Cyber Cell · SI Iyer · SI Pal/)).toBeInTheDocument()
    const move = screen.getByLabelText('release of 635 USDT')
    expect(within(move).getByText('Proposed')).toBeInTheDocument()
    expect(within(move).getByText(/approved by SI Iyer \(1 of 2\)/)).toBeInTheDocument()
  })

  it('offers only signers who may still approve: never twice, never the proposer unless allowed', () => {
    expect(canApprove(WALLET, MOVE)).toEqual(['SI Pal'])
    expect(canApprove({ ...WALLET, proposer_may_sign: true }, MOVE)).toEqual(['Insp. Rao', 'SI Pal'])
  })

  it('records an approval by the signer chosen', async () => {
    const calls = api({
      ...NO_ASSETS,
      'GET /trace/c1/custody': { body: { enabled: true, wallets: [WALLET], chains: { tron: 'Tron' } } },
      'POST /custody/movements/m1/approve': { body: { ...MOVE, status: 'approved' } },
    })
    const user = userEvent.setup()
    open()
    await user.selectOptions(await screen.findByLabelText('Signer who approved'), 'SI Pal')
    await user.click(screen.getByRole('button', { name: 'Record approval' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST').body).toEqual({ signer: 'SI Pal' })
  })

  it('records a wallet with its signers parsed from one line each, and shows a refusal', async () => {
    const calls = api({
      ...NO_ASSETS,
      'GET /trace/c1/custody': { body: { enabled: true, wallets: [], chains: { tron: 'Tron', ethereum: 'Ethereum Mainnet' } } },
      'POST /trace/c1/custody': { status: 400, body: { detail: 'The threshold (4) is more than the number of signers (2).' } },
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Record a custody wallet' }))
    const form = screen.getByRole('form', { name: 'Record a custody wallet' })
    await user.type(within(form).getByLabelText(/Signers, one per line/), 'Insp. Rao, Inspector, Cyber Cell{enter}SI Iyer')
    await user.clear(within(form).getByLabelText('Threshold (m)'))
    await user.type(within(form).getByLabelText('Threshold (m)'), '4')
    await user.click(within(form).getByRole('button', { name: 'Record the wallet' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('more than the number of signers')
    expect(calls.find((c) => c.method === 'POST').body.signers).toEqual([
      { name: 'Insp. Rao', role: 'Inspector', unit: 'Cyber Cell' }, { name: 'SI Iyer', role: '', unit: '' }])
  })

  it('parses signer lines, dropping blank ones and keeping commas inside a unit', () => {
    expect(parseSigners('A, B, Cyber Cell, North\n\n  \nC')).toEqual([
      { name: 'A', role: 'B', unit: 'Cyber Cell, North' }, { name: 'C', role: '', unit: '' }])
  })
})
