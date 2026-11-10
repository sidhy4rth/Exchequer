import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import Citizen from './routes/Citizen'

// The site names no contest. noContest.test.js scans everything it ships;
// this renders the citizen page the sidebar links to and reads what it says.
const CONTEST = /\bSIH\b|hackathon|smart india/i

describe('the citizen page the console links to', () => {
  it('says nothing of a contest', () => {
    const { container } = render(<MemoryRouter><Citizen /></MemoryRouter>)
    expect(container.textContent).not.toMatch(CONTEST)
    expect(container).toHaveTextContent(/still being built/)
  })
})
