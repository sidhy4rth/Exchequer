import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import TraceForm, { parseHashes } from './TraceForm'
import { stubFetch } from '../test/setup'

const health = {
  status: 'ok',
  default_chain: 'ethereum',
  chains: {
    ethereum: { key: 'ethereum', name: 'Ethereum', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }] },
    tron: { key: 'tron', name: 'Tron', ready: true, address_family: 'tron', assets: [{ symbol: 'USDT' }] },
  },
}
const ADDR = '0x' + 'ab'.repeat(20)
const HASH = '0x' + 'cd'.repeat(32)

function Landed() {
  const { pathname, search, state } = useLocation()
  return <p data-testid="landed" data-ncrp={state?.ncrpAck ?? ''} data-victim={state?.victimAddress ?? ''} data-started={String(state?.startedHere === true)}>{pathname + search}</p>
}

async function renderForm({ payments, demos = [], chains = health }) {
  stubFetch({ '/trace/intake': { body: { payments, lookup_limit: 1000 } }, '/demos/recorded': { body: { demos } } })
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<TraceForm health={chains} />} />
        <Route path="/trace/:address" element={<Landed />} />
        <Route path="/demo/:n" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByLabelText('Wallet the victim paid')
}

// The form was the console's until the Console became a page of its own;
// these followed it to the new trace page.
describe('the trace form', () => {
  const recordings = [{ demo: 6, recorded_at: '2026-10-14T16:44:03+00:00', address: '0x00000000072d54638c2c2a3da3f715360269eea1', exchange: 'Binance', confidence: 0.875 }]

  it('flags a malformed address and does not start a trace', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: false })
    const field = screen.getByLabelText('Wallet the victim paid')
    await user.type(field, '0x1234')
    await user.keyboard('{Enter}')
    await user.tab()
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: /^start trace$/i })).toBeDisabled()
    expect(screen.queryByTestId('landed')).not.toBeInTheDocument()
  })

  it('opens a shareable trace URL for a valid address', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: false })
    await user.type(screen.getByLabelText('Wallet the victim paid'), `  ${ADDR} {Enter}`)
    expect(screen.getByTestId('landed')).toHaveTextContent(
      `/trace/${ADDR}?chain=ethereum&asset=ETH&depth=4&direction=outgoing`)
  })

  it('holds a Tron address to the Tron format, not the EVM one', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: false })
    await user.click(screen.getByRole('radio', { name: 'Tron' }))
    const field = screen.getByLabelText('Wallet the victim paid')
    await user.type(field, ADDR)
    await user.tab()
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: /^start trace$/i })).toBeDisabled()
  })

  it('offers the recording of a loaded demo, and drops it once the form is edited', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: false, demos: recordings })
    await user.selectOptions(screen.getByLabelText('Load a verified example'), '06')
    const link = await screen.findByRole('link', { name: /open as recorded/i })
    expect(link).toHaveTextContent('2026-10-14')
    await user.type(screen.getByLabelText('Wallet the victim paid'), 'f')
    expect(screen.queryByRole('link', { name: /open as recorded/i })).not.toBeInTheDocument()
  })

  it('opens the recording without starting a trace', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: false, demos: recordings })
    await user.selectOptions(screen.getByLabelText('Load a verified example'), '06')
    await user.click(await screen.findByRole('link', { name: /open as recorded/i }))
    expect(screen.getByTestId('landed')).toHaveTextContent('/demo/6')
  })

  it('offers no recording for a demo that has none', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: false, demos: recordings })
    await user.selectOptions(screen.getByLabelText('Load a verified example'), '01')
    expect(screen.queryByRole('link', { name: /open as recorded/i })).not.toBeInTheDocument()
  })
})

describe('payment hashes on the trace form (R1)', () => {
  it('are not offered when the backend has them switched off', async () => {
    await renderForm({ payments: false })
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.queryByLabelText(/payment hashes/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Victim's payments/ })).not.toBeInTheDocument()
  })

  it('go into the trace URL; the NCRP number does not', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: true })
    await user.type(screen.getByLabelText('Wallet the victim paid'), ADDR)
    await user.click(await screen.findByRole('button', { name: /Victim's payments/ }))
    await user.type(await screen.findByLabelText(/payment hashes/i), HASH)
    await user.type(screen.getByLabelText(/NCRP acknowledgement/i), '31911250012345')
    await user.click(screen.getByRole('button', { name: /^start trace$/i }))
    const landed = screen.getByTestId('landed')
    expect(landed).toHaveTextContent(`/trace/${ADDR}?chain=ethereum&asset=ETH&depth=4&direction=outgoing&pay=${HASH}`)
    expect(landed.textContent).not.toContain('31911250012345')
    expect(landed).toHaveAttribute('data-ncrp', '31911250012345')
    // The trace page runs a trace started here at once; a pasted link asks first (3-5).
    expect(landed).toHaveAttribute('data-started', 'true')
  })

  it('refuse a malformed hash and keep the button disabled', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: true })
    await user.type(screen.getByLabelText('Wallet the victim paid'), ADDR)
    await user.click(await screen.findByRole('button', { name: /Victim's payments/ }))
    await user.type(await screen.findByLabelText(/payment hashes/i), '0x1234')
    expect(screen.getByText(/Not a valid Ethereum transaction hash/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^start trace$/i })).toBeDisabled()
  })

  it('are only offered for a trace of where the money went', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: true })
    await user.click(await screen.findByRole('button', { name: /Victim's payments/ }))
    await screen.findByLabelText(/payment hashes/i)
    await user.click(screen.getByRole('button', { name: /who paid in/i }))
    expect(screen.queryByLabelText(/payment hashes/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Victim's payments/ })).not.toBeInTheDocument()
  })
})

describe('only an open payments panel is sent (5-6, 5-5, 5-3)', () => {
  const VICTIM = '0x' + '11'.repeat(20)

  async function withPayment(user, hash = HASH) {
    await renderForm({ payments: true })
    await user.type(screen.getByLabelText('Wallet the victim paid'), ADDR)
    await user.click(await screen.findByRole('button', { name: /Victim's payments/ }))
    await user.type(await screen.findByLabelText(/payment hashes/i), hash)
  }

  it('collapsing the payments panel stops sending the hashes', async () => {
    const user = userEvent.setup()
    await withPayment(user)
    await user.type(screen.getByLabelText(/NCRP acknowledgement/i), '31911250012345')
    await user.click(screen.getByRole('button', { name: /Victim's payments/ }))
    await user.click(screen.getByRole('button', { name: /^start trace$/i }))
    const landed = screen.getByTestId('landed')
    expect(landed.textContent).not.toContain('pay=')
    expect(landed).toHaveAttribute('data-ncrp', '')
  })

  it('a bad hash in a collapsed panel does not disable Trace', async () => {
    const user = userEvent.setup()
    await withPayment(user, '0x1234')
    expect(screen.getByRole('button', { name: /^start trace$/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /Victim's payments/ }))
    expect(screen.queryByText(/Not a valid Ethereum transaction hash/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^start trace$/i })).toBeEnabled()
  })

  it('the pill counts hashes that will not be sent, and an open panel says how many are attached', async () => {
    const user = userEvent.setup()
    await withPayment(user)
    expect(screen.getByRole('status')).toHaveTextContent('1 payment · read on the chain when the trace starts')
    await user.click(screen.getByRole('button', { name: /Victim's payments/ }))
    expect(screen.getByRole('button', { name: /Victim's payments/ })).toHaveTextContent("Victim's payments · 1 entered, not sent")
    expect(screen.queryByText(/read on the chain/)).not.toBeInTheDocument()
  })

  it('an NCRP number that is not 10 to 20 digits shows a warning and disables Trace', async () => {
    const user = userEvent.setup()
    await withPayment(user)
    await user.type(screen.getByLabelText(/NCRP acknowledgement/i), 'FIR 12')
    expect(screen.getByText(/An NCRP acknowledgement number is 10 to 20 digits/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^start trace$/i })).toBeDisabled()
  })

  it("the victim's wallet travels in the navigation state, never the URL", async () => {
    const user = userEvent.setup()
    await withPayment(user)
    await user.type(screen.getByLabelText(/Victim's own wallet/i), VICTIM)
    await user.click(screen.getByRole('button', { name: /^start trace$/i }))
    const landed = screen.getByTestId('landed')
    expect(landed.textContent).not.toContain(VICTIM)
    expect(landed).toHaveAttribute('data-victim', VICTIM)
  })

  it("refuses a victim's wallet that is malformed or is the reported wallet", async () => {
    const user = userEvent.setup()
    await withPayment(user)
    const box = screen.getByLabelText(/Victim's own wallet/i)
    await user.type(box, '0x12')
    expect(screen.getByText(/The victim's wallet is not a valid Ethereum address/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^start trace$/i })).toBeDisabled()
    await user.clear(box)
    await user.type(box, ADDR.toUpperCase().replace('0X', '0x'))
    expect(screen.getByText(/The victim's wallet is the reported wallet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^start trace$/i })).toBeDisabled()
  })
})

// The New trace page (Glass): chips for chain and asset, a 1-4 hop
// segmented control, the direction in words, the NCRP number masked, and
// what happens next beside the form.
describe('the new trace page form', () => {
  const five = {
    status: 'ok',
    default_chain: 'ethereum',
    chains: {
      ethereum: { ...health.chains.ethereum, assets: [{ symbol: 'ETH' }, { symbol: 'USDT' }] },
      bsc: { key: 'bsc', name: 'BNB Smart Chain', ready: true, address_family: 'evm', assets: [{ symbol: 'BNB' }] },
      polygon: { key: 'polygon', name: 'Polygon PoS', ready: false, address_family: 'evm', assets: [{ symbol: 'POL' }] },
      arbitrum: { key: 'arbitrum', name: 'Arbitrum One', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }] },
      tron: health.chains.tron,
    },
  }

  it('offers each chain as a chip, Tron first, and says why one that is off cannot be picked', async () => {
    await renderForm({ payments: false, chains: five })
    const chains = within(screen.getByRole('radiogroup', { name: 'Blockchain' })).getAllByRole('radio')
    expect(chains.map((c) => c.labels[0].textContent)).toEqual(['Tron', 'Ethereum', 'BNB Chain', 'Polygon off', 'Arbitrum'])
    expect(screen.getByRole('radio', { name: /^Polygon/ })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'Ethereum' })).toBeChecked()
    expect(screen.getByText(/Polygon is off on this site/)).toBeInTheDocument()
  })

  it('starts on the first chain that is on when the site\'s default is off', async () => {
    // Tron's assets in the backend's own order: the native coin first.
    const tron = { ...five.chains.tron, assets: [{ symbol: 'TRX' }, { symbol: 'USDT' }] }
    const tronOnly = { ...five, chains: { ...five.chains, ethereum: { ...five.chains.ethereum, ready: false }, tron } }
    await renderForm({ payments: false, chains: tronOnly })
    expect(screen.getByRole('radio', { name: 'Tron' })).toBeChecked()
    // The money in a complaint on Tron is almost always USDT, not TRX.
    expect(screen.getByRole('radio', { name: 'USDT' })).toBeChecked()
  })

  it('starts a site whose default is Tron on USDT, not TRX', async () => {
    const tron = { ...five.chains.tron, assets: [{ symbol: 'TRX' }, { symbol: 'USDT' }] }
    await renderForm({ payments: false, chains: { ...five, default_chain: 'tron', chains: { ...five.chains, tron } } })
    expect(screen.getByRole('radio', { name: 'Tron' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'USDT' })).toBeChecked()
  })

  it('offers the chosen chain\'s assets as chips, and a new chain starts on its first asset', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: false, chains: five })
    const assets = () => within(screen.getByRole('radiogroup', { name: 'Asset' })).getAllByRole('radio').map((r) => r.value)
    expect(assets()).toEqual(['ETH', 'USDT'])
    await user.click(screen.getByRole('radio', { name: 'USDT' }))
    await user.click(screen.getByRole('radio', { name: 'BNB Chain' }))
    expect(assets()).toEqual(['BNB'])
    expect(screen.getByRole('radio', { name: 'BNB' })).toBeChecked()
    await user.type(screen.getByLabelText('Wallet the victim paid'), `${ADDR}{Enter}`)
    expect(screen.getByTestId('landed')).toHaveTextContent(`/trace/${ADDR}?chain=bsc&asset=BNB&depth=4`)
  })

  it('follows 1 to 4 hops, 4 unless chosen, and sends the choice', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: false })
    const hops = within(screen.getByRole('group', { name: 'How far to follow' })).getAllByRole('radio')
    expect(hops.map((h) => h.value)).toEqual(['1', '2', '3', '4'])
    expect(screen.getByRole('radio', { name: '4 hops' })).toBeChecked()
    await user.click(screen.getByRole('radio', { name: '2 hops' }))
    await user.type(screen.getByLabelText('Wallet the victim paid'), `${ADDR}{Enter}`)
    expect(screen.getByTestId('landed')).toHaveTextContent('depth=2&direction=outgoing')
  })

  it('says the direction in words and can turn it round', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: false })
    expect(screen.getByText('Direction:').parentElement).toHaveTextContent('Direction: where the money went')
    await user.click(screen.getByRole('button', { name: /who paid in/i }))
    expect(screen.getByText('Direction:').parentElement).toHaveTextContent('Direction: who paid in')
    await user.type(screen.getByLabelText('Wallet the victim paid'), ADDR)
    await user.click(screen.getByRole('button', { name: /^start trace back$/i }))
    expect(screen.getByTestId('landed')).toHaveTextContent('direction=incoming')
  })

  it('loads a verified example into the chips, the hops and the direction', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: false })
    await user.selectOptions(screen.getByLabelText('Load a verified example'), '04')
    expect(screen.getByRole('radio', { name: '1 hop' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Ethereum' })).toBeChecked()
    expect(screen.getByText('Direction:').parentElement).toHaveTextContent('who paid in')
  })

  it('counts the payments as they are pasted', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: true })
    await user.click(await screen.findByRole('button', { name: /Victim's payments/ }))
    const box = await screen.findByLabelText("The victim's payment hashes, one per line")
    await user.type(box, `${HASH}\n${'0x' + 'ef'.repeat(32)}`)
    expect(screen.getByRole('status')).toHaveTextContent('2 payments · read on the chain when the trace starts')
  })

  it('masks the NCRP number until asked, and says it never goes in links or logs', async () => {
    const user = userEvent.setup()
    await renderForm({ payments: true })
    await user.click(await screen.findByRole('button', { name: /Victim's payments/ }))
    await user.type(await screen.findByLabelText(/payment hashes/i), HASH)
    const ncrp = screen.getByLabelText('NCRP acknowledgement')
    expect(ncrp).toHaveAccessibleDescription(/never in links or logs/)
    // Masked by the stylesheet, not type=password: a browser would offer to save it.
    expect(ncrp).toHaveAttribute('type', 'text')
    expect(ncrp).toHaveClass('masked')
    const reveal = screen.getByRole('button', { name: 'Show the NCRP number' })
    expect(reveal).toHaveAttribute('aria-pressed', 'false')
    await user.click(reveal)
    expect(ncrp).not.toHaveClass('masked')
    expect(reveal).toHaveAttribute('aria-pressed', 'true')
  })

  it('says what happens next, in four steps', async () => {
    await renderForm({ payments: false })
    const next = screen.getByRole('region', { name: 'What happens next' })
    expect(within(next).getAllByRole('listitem')).toHaveLength(4)
    expect(next).toHaveTextContent('Find the payment on the chain')
    expect(next).toHaveTextContent('Show where it is now')
  })
})

describe('parseHashes', () => {
  it('splits on lines, commas and spaces, and drops repeats', () => {
    expect(parseHashes(` a\nb, c  a \n`)).toEqual(['a', 'b', 'c'])
  })
})
