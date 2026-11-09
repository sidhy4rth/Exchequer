import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Tracing from './Tracing'

// The screen a live trace shows while it runs: four steps, mapped to the
// stages the backend reports (app/jobs.py, graph_builder.py, pipeline.py),
// the time so far, a bar that only moves forward, and Stop.

const ADDR = 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts'
const base = { address: ADDR, chain: 'tron', asset: 'USDT', elapsed: 1.9, onStop: () => {} }
const steps = () => within(screen.getByRole('list', { name: 'Steps' })).getAllByRole('listitem')
const current = () => steps().findIndex((li) => li.getAttribute('aria-current') === 'step')
const bar = () => Number(screen.getByRole('progressbar', { name: 'Trace progress' }).getAttribute('aria-valuenow'))

describe('the tracing screen', () => {
  it('names what is traced, and the four steps', () => {
    render(<Tracing {...base} payments progress={null} />)
    expect(screen.getByRole('heading', { level: 1, name: 'Following the money' })).toBeInTheDocument()
    expect(screen.getByText(`${ADDR} · tron USDT`)).toBeInTheDocument()
    expect(steps().map((li) => li.querySelector('.tracing-label').textContent))
      .toEqual(['Find the payment', 'Follow it hop by hop', 'Screen every wallet', 'Show where it is now'])
    expect(current()).toBe(0)
    expect(bar()).toBe(0)
    expect(screen.getByText('0:01.9')).toBeInTheDocument()
  })

  it('starts from the address when no payment was given', () => {
    render(<Tracing {...base} progress={{ stage: 'starting' }} />)
    expect(steps()[0]).toHaveTextContent('Start from the address')
  })

  it.each([
    [{ stage: 'starting' }, 0, 0],
    [{ stage: 'walking', hop: 1, max_depth: 4, level_size: 1, level_read: 0, addresses: 1 }, 1, 25],
    [{ stage: 'walking', hop: 2, max_depth: 4, level_size: 10, level_read: 5, addresses: 25 }, 1, 34],
    [{ stage: 'screening', addresses: 30 }, 2, 50],
    [{ stage: 'attributing' }, 3, 75],
    [{ stage: 'following_swap', follow_asset: 'TRX' }, 3, 75],
  ])('maps %o to step %i at %i%%', (progress, step, pct) => {
    render(<Tracing {...base} payments progress={progress} />)
    expect(current()).toBe(step)
    expect(bar()).toBe(pct)
    steps().forEach((li, i) => expect(li.classList.contains('done')).toBe(i < step))
  })

  // jobs.py merges each report into the job's progress, so the follow-on
  // walk after a swap reports walking, screening and attributing again with
  // follow_asset still set; the job ends on done or failed.
  it('stays on the last step through the walk that follows a swap, and never moves back', () => {
    const { rerender } = render(<Tracing {...base} payments progress={{ stage: 'attributing' }} />)
    const seen = []
    const lines = []
    for (const progress of [
      { stage: 'following_swap', follow_asset: 'TRX' },
      { stage: 'walking', follow_asset: 'TRX', hop: 1, max_depth: 2, level_size: 4, level_read: 2, addresses: 3 },
      { stage: 'screening', follow_asset: 'TRX', addresses: 9 },
      { stage: 'attributing', follow_asset: 'TRX' },
    ]) {
      rerender(<Tracing {...base} payments progress={progress} />)
      expect(current()).toBe(3)
      seen.push(bar())
      lines.push(document.querySelector('.progress-line').textContent)
    }
    expect(seen[0]).toBe(75)
    seen.forEach((pct, i) => expect(pct).toBeGreaterThanOrEqual(seen[i - 1] ?? 0))
    expect(lines[1]).toBe('In TRX after the swap · Hop 1 of 2 · 2 of 4 addresses read · 3 addresses so far')
  })

  it('ticks every step when the job is done, and holds its place when it fails', () => {
    const { rerender } = render(<Tracing {...base} progress={{ stage: 'walking', hop: 2, max_depth: 4, level_size: 1, level_read: 1 }} />)
    const walked = bar()
    rerender(<Tracing {...base} progress={{ stage: 'failed', hop: 2, max_depth: 4 }} />)
    expect(current()).toBe(1)
    expect(bar()).toBe(walked)
    rerender(<Tracing {...base} progress={{ stage: 'done' }} />)
    steps().forEach((li) => expect(li).toHaveClass('done'))
    expect(bar()).toBe(100)
    rerender(<Tracing {...base} progress={null} />)
    expect(current()).toBe(0)
    expect(bar()).toBe(0)
  })

  it('says what the walk is reading, as it reads it', () => {
    render(<Tracing {...base} progress={{ stage: 'walking', hop: 2, max_depth: 4, level_size: 10, level_read: 5, addresses: 25 }} />)
    expect(screen.getByText('Hop 2 of 4 · 5 of 10 addresses read · 25 addresses so far')).toHaveAttribute('aria-live', 'polite')
  })

  it('shows the time cap, and stops once', async () => {
    const onStop = vi.fn()
    const { rerender } = render(<Tracing {...base} budget={90} elapsed={95} progress={{ stage: 'walking', hop: 1 }} canStop onStop={onStop} />)
    expect(screen.getByText(/stops expanding at 1:30 — finishing what it has/)).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Stop this trace' }))
    expect(onStop).toHaveBeenCalledTimes(1)
    rerender(<Tracing {...base} progress={{ stage: 'walking', hop: 1 }} canStop stopping onStop={onStop} />)
    expect(screen.getByRole('button', { name: 'Stopping…' })).toBeDisabled()
  })

  it('offers no Stop before the job has an id', () => {
    render(<Tracing {...base} progress={null} />)
    expect(screen.queryByRole('button', { name: 'Stop this trace' })).not.toBeInTheDocument()
  })
})
