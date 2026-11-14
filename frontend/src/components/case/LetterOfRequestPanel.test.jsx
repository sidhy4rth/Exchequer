import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import LetterOfRequestPanel, { reachedExchange } from './LetterOfRequestPanel'

// The letter of request on the Letters tab (backend letters_of_request.py): the
// officer's details go to the server in a POST body, and the draft comes back
// to read, download or copy. Nothing is kept here.
const CASE = { case_id: 'c1-abcdef12', exchange: 'Binance' }

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
    const { status = 200, text, body: out } = hit
    return new Response(text ?? JSON.stringify(out), { status })
  }))
  return calls
}

describe('the letter of request panel', () => {
  it('shows only for a stored case the server offers an exchange letter for', () => {
    const { container: none } = render(<LetterOfRequestPanel result={{ case_id: 'c1', exchange: null }} />)
    expect(none).toBeEmptyDOMElement()
    const { container: recorded } = render(<LetterOfRequestPanel result={{ exchange: 'Binance' }} offered />)
    expect(recorded).toBeEmptyDOMElement()
    const { container: noLetter } = render(<LetterOfRequestPanel result={CASE} offered={false} />)
    expect(noLetter).toBeEmptyDOMElement()
    render(<LetterOfRequestPanel result={CASE} offered />)
    expect(screen.getByText('Letter of request abroad')).toBeInTheDocument()
  })

  it('finds the exchange a follow-on trace reached after a swap', () => {
    expect(reachedExchange({ exchange: null, follow_ons: [{ result: { exchange: 'Bybit' } }] })).toBe('Bybit')
    expect(reachedExchange({ exchange: null, follow_ons: [] })).toBeNull()
  })

  it("sends the officer's details in the body and shows the draft", async () => {
    const calls = api({ 'POST /trace/c1-abcdef12/letter-of-request': { text: 'DRAFT — letter of request\nTo: The Competent Authority' } })
    const user = userEvent.setup()
    render(<LetterOfRequestPanel result={CASE} offered />)
    const form = screen.getByRole('form', { name: 'Letter of request details' })
    await user.selectOptions(within(form).getByLabelText('Basis'), 'reciprocity')
    await user.type(within(form).getByLabelText('Requested country'), 'Seychelles')
    await user.click(within(form).getByRole('button', { name: 'Draft the letter of request' }))
    expect(await screen.findByLabelText('The draft letter of request')).toHaveTextContent('DRAFT — letter of request')
    expect(calls[0].body).toEqual({ basis: 'reciprocity', country: 'Seychelles' })
    expect(screen.getByRole('button', { name: 'Download (.txt)' })).toBeInTheDocument()
  })

  it('asks for the treaty only when the basis is a treaty', async () => {
    const user = userEvent.setup()
    render(<LetterOfRequestPanel result={CASE} offered />)
    expect(screen.queryByLabelText('Treaty or convention')).toBeNull()
    await user.selectOptions(screen.getByLabelText('Basis'), 'treaty')
    expect(screen.getByLabelText('Treaty or convention')).toBeInTheDocument()
  })

  it("holds each field to the server's limit, so a long one is never refused without saying which", () => {
    render(<LetterOfRequestPanel result={CASE} offered />)
    // backend letters_of_request.FIELDS
    const limits = { 'Requested country': 80, Court: 200, 'Presiding officer': 120, 'FIR / case number': 120,
      'Investigating agency': 200, 'Offences and maximum penalties': 1500, Limitation: 500, 'What happened': 4000,
      "Exchange's registered office": 300, Urgency: 300, 'Liaison officer': 500 }
    for (const [label, max] of Object.entries(limits)) {
      expect(screen.getByLabelText(label)).toHaveAttribute('maxLength', String(max))
    }
  })

  it("shows the server's refusal, and a changed detail clears an old draft", async () => {
    api({ 'POST /trace/c1-abcdef12/letter-of-request': { status: 400, body: { detail: 'Name the treaty or convention the request is made under.' } } })
    const user = userEvent.setup()
    render(<LetterOfRequestPanel result={CASE} offered />)
    await user.click(screen.getByRole('button', { name: 'Draft the letter of request' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Name the treaty')
    api({ 'POST /trace/c1-abcdef12/letter-of-request': { text: 'DRAFT one' } })
    await user.click(screen.getByRole('button', { name: 'Draft the letter of request' }))
    await screen.findByLabelText('The draft letter of request')
    await user.type(screen.getByLabelText('Court'), 'C')
    await waitFor(() => expect(screen.queryByLabelText('The draft letter of request')).toBeNull())
  })

  it('keeps the keyboard on the panel: the draft takes focus, and a refusal leaves it on the button', async () => {
    api({ 'POST /trace/c1-abcdef12/letter-of-request': { status: 400, body: { detail: 'Name the treaty or convention the request is made under.' } } })
    const user = userEvent.setup()
    render(<LetterOfRequestPanel result={CASE} offered />)
    const button = screen.getByRole('button', { name: 'Draft the letter of request' })
    button.focus()
    await user.keyboard('{Enter}')
    await screen.findByRole('alert')
    expect(button).toHaveFocus() // not dropped to the page while the request ran
    api({ 'POST /trace/c1-abcdef12/letter-of-request': { text: 'DRAFT one' } })
    await user.keyboard('{Enter}')
    await waitFor(() => expect(screen.getByLabelText('The draft letter of request')).toHaveFocus())
  })
})
