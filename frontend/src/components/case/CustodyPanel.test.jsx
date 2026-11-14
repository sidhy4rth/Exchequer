import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import CustodyPanel, { canApprove, parseSigners, proposers } from './CustodyPanel'

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

  it('clears the chosen signer once the approval is recorded, and gives the keyboard to the movement', async () => {
    // Three of four, so a signer is still left to choose after this approval.
    const wallet = { ...WALLET, threshold: 3, signer_count: 4, signers: [...SIGNERS, { name: 'SI Das', role: '', unit: '' }] }
    let approvals = MOVE.approvals
    const calls = api({
      ...NO_ASSETS,
      'GET /trace/c1/custody': () => ({ body: { enabled: true, wallets: [{ ...wallet, movements: [{ ...MOVE, threshold: 3, approvals }] }], chains: { tron: 'Tron' } } }),
      'POST /custody/movements/m1/approve': (b) => {
        approvals = [...approvals, { signer: b.signer, at: '2026-11-14T06:00:00Z', recorded_by: 'officer-2' }]
        return { body: { ...MOVE, approvals } }
      },
    })
    const user = userEvent.setup()
    open()
    await user.selectOptions(await screen.findByLabelText('Signer who approved'), 'SI Pal')
    await user.click(screen.getByRole('button', { name: 'Record approval' }))
    const move = screen.getByRole('group', { name: 'release of 635 USDT' })
    await waitFor(() => expect(within(move).getByText(/approved by SI Iyer, SI Pal \(2 of 3\)/)).toBeInTheDocument())
    expect(screen.getByLabelText('Signer who approved')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Record approval' })).toBeDisabled()
    expect(move).toHaveFocus()
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it('offers an asset-register row added after the panel loaded, when the form opens', async () => {
    let assets = []
    api({
      'GET /trace/c1/assets': () => ({ body: { assets } }),
      'GET /trace/c1/custody': { body: { enabled: true, wallets: [], chains: { tron: 'Tron' } } },
    })
    const user = userEvent.setup()
    open()
    const button = await screen.findByRole('button', { name: 'Record a custody wallet' })
    assets = [{ asset_id: 'a1', case_id: 'c1', holder: 'custody', asset: 'USDT', amount: '635.000000' }]
    await user.click(button)
    expect(await screen.findByRole('checkbox', { name: /Holds 635.000000 USDT from the asset register/ })).toBeInTheDocument()
  })

  it('says a deposit needs no signatures rather than counting approvals it does not need', async () => {
    const deposit = { ...MOVE, kind: 'deposit', destination: '', order_ref: '', approvals: [], status: 'confirmed', tx_hash: 'ab'.repeat(32) }
    api({ ...NO_ASSETS, 'GET /trace/c1/custody': { body: { enabled: true, wallets: [{ ...WALLET, movements: [deposit] }], chains: { tron: 'Tron' } } } })
    open()
    const move = await screen.findByRole('group', { name: 'deposit of 635 USDT' })
    expect(within(move).getByText(/a deposit into the wallet needs no signatures/)).toBeInTheDocument()
    expect(within(move).queryByText(/nobody yet/)).not.toBeInTheDocument()
  })

  it('shows the reason a cancelled movement was given', async () => {
    const cancelled = { ...MOVE, status: 'cancelled', history: [{ at: 't1', by: 'officer-1', status: 'proposed' }, { at: 't2', by: 'officer-1', reason: 'Order stayed on appeal', status: 'cancelled' }] }
    api({ ...NO_ASSETS, 'GET /trace/c1/custody': { body: { enabled: true, wallets: [{ ...WALLET, movements: [cancelled] }], chains: { tron: 'Tron' } } } })
    open()
    const move = await screen.findByRole('group', { name: 'release of 635 USDT' })
    expect(within(move).getByText('Cancelled: Order stayed on appeal')).toBeInTheDocument()
  })

  it('offers the proposer from the signers, and someone else only where the scheme keeps proposing apart from signing', () => {
    expect(proposers(WALLET)).toEqual({ signers: ['Insp. Rao', 'SI Iyer', 'SI Pal'], other: true })
    expect(proposers({ ...WALLET, proposer_may_sign: true })).toEqual({ signers: ['Insp. Rao', 'SI Iyer', 'SI Pal'], other: false })
    // 3 of 3 where a proposer may not sign: a signer proposing would leave two, so only someone else may.
    expect(proposers({ ...WALLET, threshold: 3 })).toEqual({ signers: [], other: true })
  })

  it('proposes with a signer chosen from the list, or the name typed for someone else', async () => {
    const calls = api({
      ...NO_ASSETS,
      'GET /trace/c1/custody': { body: { enabled: true, wallets: [{ ...WALLET, movements: [] }], chains: { tron: 'Tron' } } },
      'POST /custody/w1/movements': { status: 201, body: { movement_id: 'm2' } },
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Propose a deposit or release' }))
    let form = screen.getByRole('form', { name: 'Propose a movement' })
    expect(within(form).queryByLabelText("Proposer's name")).toBeNull()
    await user.selectOptions(within(form).getByLabelText('Proposed by'), 'SI Iyer')
    await user.type(within(form).getByLabelText('Asset'), 'USDT')
    await user.type(within(form).getByLabelText('Amount'), '5')
    await user.click(within(form).getByRole('button', { name: 'Propose' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST').body).toMatchObject({ kind: 'deposit', proposed_by: 'SI Iyer', asset: 'USDT', amount: '5' })
    expect(calls.find((c) => c.method === 'POST').body).not.toHaveProperty('proposer')

    await user.click(await screen.findByRole('button', { name: 'Propose a deposit or release' }))
    form = screen.getByRole('form', { name: 'Propose a movement' })
    await user.selectOptions(within(form).getByLabelText('Proposed by'), 'Someone else, not a signer')
    await user.type(within(form).getByLabelText("Proposer's name"), 'Constable Das')
    await user.click(within(form).getByRole('button', { name: 'Propose' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toHaveLength(2))
    expect(calls.filter((c) => c.method === 'POST')[1].body.proposed_by).toBe('Constable Das')
  })

  it('parses signer lines, dropping blank ones and keeping commas inside a unit', () => {
    expect(parseSigners('A, B, Cyber Cell, North\n\n  \nC')).toEqual([
      { name: 'A', role: 'B', unit: 'Cyber Cell, North' }, { name: 'C', role: '', unit: '' }])
  })
})
