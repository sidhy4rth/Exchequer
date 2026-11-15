import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import SopReminders from './SopReminders'

// SOP reminders under a bank hold (backend sop_reminders.py). The rows carry
// them only when EXCHEQUER_SOP_DEADLINES is on; without them nothing shows.
const NOTE = 'A reminder of what the SOP says, quoted from one copy. Not a deadline Exchequer enforces; check the current SOP and the law.'
const URL = 'https://www.zoroastrianbank.bank.in/download/SOP-NCRP.pdf'
const NINETY = {
  id: 'annex1-90-days', section: 'Annexure I, para 3', page: 34, date: '2027-01-30', date_label: 'Day 90 from the date seized recorded here',
  quote: 'the bank may remove the hold, after completion of 90 calendar days from the date of amount put on hold',
  hint: 'Reminder, per MHA SOP for NCRP-CFCFRMS Annexure I, para 3 (copy dated 11 Feb 2026): “the bank may remove the hold, after completion of 90 calendar days from the date of amount put on hold” (if conditions (a) to (d) of that paragraph are met).',
  source_url: URL, copy: 'copy dated 11 Feb 2026', reminder_only: true, note: NOTE,
}
const WEEK = {
  ...NINETY, id: 's6-1k-1-week', section: '§6.1(k)', page: 12, date: null, date_label: null,
  hint: 'Reminder, per MHA SOP for NCRP-CFCFRMS §6.1(k) (copy dated 11 Feb 2026): “… within 1 week of reporting.”',
}

describe('SOP reminders on a bank hold', () => {
  it('quotes each reminder with its section, copy and source, and says it is not enforced', () => {
    render(<SopReminders reminders={[NINETY, WEEK]} />)
    expect(screen.getByText(/SOP reminders, if this hold went through CFCFRMS · 2/)).toBeInTheDocument()
    expect(screen.getByText(NOTE)).toBeInTheDocument()
    expect(screen.getByText(/per MHA SOP for NCRP-CFCFRMS Annexure I, para 3 \(copy dated 11 Feb 2026\)/)).toBeInTheDocument()
    expect(screen.getByText(/Day 90 from the date seized recorded here: 30 Jan 2027/)).toBeInTheDocument()
    expect(screen.getAllByText(/Day 90/)).toHaveLength(1) // only the dated one shows a date
    const links = screen.getAllByRole('link')
    expect(links.map((a) => a.getAttribute('href'))).toEqual([URL, URL])
    expect(links[1]).toHaveTextContent('Source, PDF page 12')
  })

  it('shows nothing when the row carries no reminders (flag off, or not a bank hold)', () => {
    const { container: off } = render(<SopReminders reminders={undefined} />)
    expect(off).toBeEmptyDOMElement()
    const { container: none } = render(<SopReminders reminders={[]} />)
    expect(none).toBeEmptyDOMElement()
  })
})
