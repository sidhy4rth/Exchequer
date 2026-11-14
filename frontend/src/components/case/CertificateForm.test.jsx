import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CertificateForm from './CertificateForm'

// The draft s.63(4) certificate (backend certificates.py), on the Evidence tab
// under the exhibits: pick exhibits, type the source device, get the PDF. Part B
// is the expert's; what is typed goes into the PDF and is kept nowhere.
const ROWS = [
  { exhibit_id: 'e1', label: "Accused's phone", kind_label: 'Phone extraction', sha256: '9f'.repeat(32) },
  { exhibit_id: 'e2', label: 'Laptop SSD', kind_label: 'Disk image', sha256: 'ab'.repeat(32) },
]

function api(reply) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    calls.push({ url: String(url), body: JSON.parse(init.body) })
    return reply()
  }))
  return calls
}
const pdf = () => new Response('%PDF-1.7 draft', { status: 200, headers: { 'Content-Type': 'application/pdf' } })

afterEach(() => { vi.unstubAllGlobals(); delete URL.createObjectURL; delete URL.revokeObjectURL })

describe('the draft s.63(4) certificate', () => {
  it('sends the chosen exhibits and the typed device, and downloads the PDF', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:certificate')
    URL.revokeObjectURL = vi.fn()
    const calls = api(pdf)
    const user = userEvent.setup()
    render(<CertificateForm caseId="case-1" exhibits={ROWS} />)
    await user.click(screen.getByRole('button', { name: 'Draft the s.63(4) certificate' }))
    await user.click(screen.getByLabelText(/Laptop SSD/))
    await user.selectOptions(screen.getByLabelText('Kind of device'), 'Computer / Storage Media')
    await user.type(screen.getByLabelText('Make and model'), 'Samsung 980 Pro')
    await user.type(screen.getByLabelText('Serial number'), 'S5GXNF0R')
    await user.click(screen.getByLabelText('Maintained'))
    await user.click(screen.getByRole('button', { name: 'Download the draft (PDF)' }))
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
    expect(calls[0].url).toMatch(/\/trace\/case-1\/certificate$/)
    expect(calls[0].body).toMatchObject({ exhibit_ids: ['e2'], device: 'Computer / Storage Media', make_model: 'Samsung 980 Pro',
      serial: 'S5GXNF0R', control: ['Maintained'] })
    expect(await screen.findByRole('status')).toHaveTextContent('check every value in bold before anyone signs')
  })

  it('waits for an exhibit, and asks for the other kind of device only when Other is picked', async () => {
    api(pdf)
    const user = userEvent.setup()
    render(<CertificateForm caseId="case-1" exhibits={ROWS} />)
    await user.click(screen.getByRole('button', { name: 'Draft the s.63(4) certificate' }))
    expect(screen.getByRole('button', { name: 'Download the draft (PDF)' })).toBeDisabled()
    expect(screen.queryByLabelText('Other kind of device')).toBeNull()
    await user.selectOptions(screen.getByLabelText('Kind of device'), 'Other')
    expect(screen.getByLabelText('Other kind of device')).toBeInTheDocument()
    await user.click(screen.getByLabelText(/Accused's phone/))
    expect(screen.getByRole('button', { name: 'Download the draft (PDF)' })).toBeEnabled()
  })

  it('says Part B is the expert\'s and that nothing typed is kept', async () => {
    const user = userEvent.setup()
    render(<CertificateForm caseId="case-1" exhibits={ROWS} />)
    await user.click(screen.getByRole('button', { name: 'Draft the s.63(4) certificate' }))
    expect(screen.getByText(/Part B is left blank for the expert/)).toBeInTheDocument()
    expect(screen.getByText(/kept nowhere/)).toBeInTheDocument()
  })

  it('says what the server refused', async () => {
    api(() => new Response(JSON.stringify({ detail: 'No exhibit e1 in this case that you can read.' }), { status: 400 }))
    const user = userEvent.setup()
    render(<CertificateForm caseId="case-1" exhibits={ROWS} />)
    await user.click(screen.getByRole('button', { name: 'Draft the s.63(4) certificate' }))
    await user.click(screen.getByLabelText(/Accused's phone/))
    await user.click(screen.getByRole('button', { name: 'Download the draft (PDF)' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('No exhibit e1')
  })

  it('with no exhibits, still offers the certificate for the case\'s own report', async () => {
    const user = userEvent.setup()
    render(<CertificateForm caseId="case-1" exhibits={[]} />)
    await user.click(screen.getByRole('button', { name: 'Draft the s.63(4) certificate' }))
    expect(screen.getByLabelText(/Forensic files from the register/)).toBeDisabled()
    expect(screen.getByLabelText(/Exchequer's report of this case/)).toBeChecked()
  })

  it('sends the report file itself, as base64, and downloads the certificate for it', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:report-certificate')
    URL.revokeObjectURL = vi.fn()
    const calls = api(pdf)
    const user = userEvent.setup()
    render(<CertificateForm caseId="case-1" exhibits={ROWS} />)
    await user.click(screen.getByRole('button', { name: 'Draft the s.63(4) certificate' }))
    await user.click(screen.getByLabelText(/Exchequer's report of this case/))
    expect(screen.getByRole('button', { name: 'Download the draft (PDF)' })).toBeDisabled()
    await user.upload(screen.getByLabelText(/The report file you will produce/), new File(['SEALED REPORT'], 'exchequer-case-1.txt'))
    await user.selectOptions(screen.getByLabelText('Kind of device'), 'Server')
    await user.click(screen.getByRole('button', { name: 'Download the draft (PDF)' }))
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
    expect(calls[0].url).toMatch(/\/trace\/case-1\/report-certificate$/)
    expect(calls[0].body).toMatchObject({ file_name: 'exchequer-case-1.txt', device: 'Server', report_b64: btoa('SEALED REPORT') })
    expect(calls[0].body.exhibit_ids).toBeUndefined()
    expect(await screen.findByRole('status')).toHaveTextContent('exchequer-case-1.txt')
  })
})
