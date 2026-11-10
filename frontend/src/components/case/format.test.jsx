import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Address } from './format'

describe('an address that copies itself', () => {
  const value = 'T' + '7'.repeat(33)

  it('says copied, and drops that timer when it goes away, so it never fires on a closed page', async () => {
    const user = userEvent.setup()
    render(<Address value={value} />)
    const set = vi.spyOn(globalThis, 'setTimeout')
    const clear = vi.spyOn(globalThis, 'clearTimeout')
    try {
      await user.click(screen.getByRole('button'))
      expect(await navigator.clipboard.readText()).toBe(value)
      await screen.findByText('copied')
      const marks = set.mock.calls.flatMap(([, ms], i) => (ms === 1100 ? [set.mock.results[i].value] : []))
      expect(marks).toHaveLength(1)
      cleanup()
      expect(clear).toHaveBeenCalledWith(marks[0])
    } finally {
      set.mockRestore()
      clear.mockRestore()
    }
  })
})
