import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import StatementPanel from './StatementPanel'

// A statement read in the browser and lined up with the case (backend
// statement_imports.py). Every row is synthetic: made-up narrations, a test
// account number no bank issues, a reference shaped like an NEFT UTR.
const ACCOUNT = '9999000011112222'
const CSV = [
  'Account Number,' + ACCOUNT,
  'Txn Date,Description,Ref No./Cheque No.,Withdrawal Amt.(INR),Deposit Amt.(INR),Closing Balance',
  `12/03/2026,NEFT/SBINN26071000001/TEST PAYEE/A/C ${ACCOUNT},,"2,50,000.00",,"1,00,000.00"`,
  '13/03/2026,UPI/607200000001/COINDCX TEST,,"15,000.00",,"85,000.00"',
  '14/03/2026,TEST GROCERY STORE,,500.00,,"84,500.00"',
].join('\n')

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

const ON = { body: { enabled: true, imports: [], exchange_names: ['Binance', 'CoinDCX'] } }
const file = () => new File([CSV], 'statement.csv', { type: 'text/csv' })

describe('the statement panel', () => {
  it('shows nothing while the server has the feature off', async () => {
    const calls = api({ 'GET /trace/c1/statements': { body: { enabled: false, imports: [], exchange_names: [] } } })
    const { container } = render(<StatementPanel result={{ case_id: 'c1' }} />)
    await waitFor(() => expect(calls.length).toBe(1))
    expect(container.innerHTML).toBe('')
  })

  it('reads the file in the browser, finds the rows, and sends only the ticked ones when saved', async () => {
    const calls = api({
      'GET /trace/c1/statements': ON,
      'POST /trace/c1/statements': { status: 201, body: { import_id: 's1' } },
    })
    render(<StatementPanel result={{ case_id: 'c1', intake: { mode: 'address', payments: [] } }} />)
    const input = await screen.findByLabelText('CSV file')
    await userEvent.upload(input, file())

    const rows = await screen.findByRole('list', { name: 'Rows worth a look' })
    expect(within(rows).getAllByRole('listitem')).toHaveLength(2) // the grocery row is not a lead
    expect(rows.textContent).toContain('Names an exchange: CoinDCX')
    expect(rows.textContent).toContain('NEFT SBINN26071000001')
    expect(calls.filter((c) => c.method === 'POST')).toEqual([]) // nothing sent on reading

    // The rupees from the complaint make the first row an amount-and-date match.
    await userEvent.type(screen.getByLabelText('Rupees paid, from the complaint'), '2,50,000')
    await userEvent.type(screen.getByLabelText('On'), '2026-03-12')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(rows.textContent).toContain('Amount and date match a payment')

    await userEvent.click(within(rows).getAllByRole('checkbox')[1]) // untick the CoinDCX row
    await userEvent.click(screen.getByRole('button', { name: 'Save 1 ticked row to the case' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const sent = calls.find((c) => c.method === 'POST').body
    expect(sent).toMatchObject({ source: 'bank', currency: 'INR' })
    expect(sent.rows).toEqual([{
      date: '2026-03-12', time: '', direction: 'debit', amount: '250000.00', reference: 'SBINN26071000001',
      narration: `NEFT/SBINN26071000001/TEST PAYEE/A/C ${ACCOUNT}`, counterparty: '', reasons: ['amount_date', 'utr'], exchange: '',
    }])
  })

  it('lists the rows already saved to the case', async () => {
    api({ 'GET /trace/c1/statements': { body: { ...ON.body, imports: [{
      import_id: 's1', title: 'Victim statement (test)', source_label: 'Bank statement', currency: 'INR', row_count: 1,
      created_at: '2026-11-14T10:00:00Z', rows: [{ date: '2026-03-12', time: '', direction: 'debit', amount: '250000',
        reference: 'SBINN26071000001', narration: 'TEST', counterparty: '', reasons: ['utr'], exchange: '' }],
    }] } } })
    render(<StatementPanel result={{ case_id: 'c1' }} />)
    expect(await screen.findByText(/Victim statement \(test\) · 1 row · INR/)).toBeTruthy()
  })
})
