import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import Citizen, { complaintText } from './Citizen'
import { stubFetch } from '../test/setup'

const health = { chains: {
  ethereum: { key: 'ethereum', name: 'Ethereum Mainnet', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }, { symbol: 'USDT' }] },
  tron: { key: 'tron', name: 'Tron', ready: true, address_family: 'tron', assets: [{ symbol: 'TRX' }, { symbol: 'USDT' }] },
} }

describe('citizen complaint', () => {
  it('writes a summary with every field the citizen gave, and the trace finding', () => {
    const text = complaintText({
      scamType: 'task', when: '2026-10-01', chain: 'tron', asset: 'USDT', amount: '1,250 USDT', amountInr: '1,05,000',
      scammerAddress: ' TXyz ', myAddress: '', txHashes: 'aa bb', contact: '@tasks_boss on Telegram', story: 'Paid to unlock\nthen more',
      name: 'A. Citizen', phone: '98xxxxxx01', email: '', city: 'Bengaluru',
    }, { name: 'Tron', assets: [{ symbol: 'TRX' }] }, { exchange: 'Binance', exchange_address: 'TBin', attribution_inferred: true, case_id: 'c-1' })
    expect(text).toContain('Complainant      : A. Citizen, Bengaluru')
    expect(text).toContain('Part-time job')
    expect(text).toContain('Paid to address  : TXyz')
    expect(text).toContain('  aa\n  bb')
    expect(text).toContain('Reached Binance at TBin (inferred deposit address; the exchange must confirm).')
    expect(text).toContain('Exchequer case reference: c-1')
  })

  it('checks the address against the chosen network and keeps the draft in this browser', async () => {
    stubFetch({ '/health': { body: health } })
    localStorage.removeItem('exchequer-citizen-draft')
    const user = userEvent.setup()
    render(<MemoryRouter><Citizen /></MemoryRouter>)
    await screen.findByRole('option', { name: 'Tron' })
    const field = screen.getByLabelText(/The address you sent it to/)
    await user.type(field, '0x1234')
    expect(screen.getByText(/should start with 0x followed by 40/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Follow the money' })).toBeDisabled()
    await user.selectOptions(screen.getByLabelText('Network'), 'tron')
    expect(screen.getByText(/A Tron address starts with T/)).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('exchequer-citizen-draft')).scammerAddress).toBe('0x1234')
  })
})
