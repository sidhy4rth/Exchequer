import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TaskDeadlines from '../TaskDeadlines'
import TasksPanel, { dueText, historyLine } from './TasksPanel'

// The case's task list on the Evidence tab (backend tasks.py) and the home
// page's tasks-due card. Rows come from the backend; the panel adds a task,
// marks one done, and asks why before dropping one or opening it again.
const TASK = {
  task_id: 't1', case_id: 'c1', title: 'Send the notice to the bank', assignee: 'SI Iyer', due_on: '2026-11-16',
  status: 'open', notes: '', created_at: '2026-11-14T05:00:00Z', updated_at: '2026-11-14T05:00:00Z',
  days_left: 2, overdue: false, history: [{ at: '2026-11-14T05:00:00Z', by: 'demo', action: 'added' }],
}
const DONE = { ...TASK, task_id: 't2', title: 'Get the court order', assignee: 'Insp. Rao', status: 'done', days_left: null,
  history: [...TASK.history, { at: '2026-11-15T05:00:00Z', by: 'demo', action: 'done', changed: ['status'] }] }

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

const open = () => render(<MemoryRouter><TasksPanel result={{ case_id: 'c1' }} /></MemoryRouter>)

describe('the case task list', () => {
  it('shows open tasks with who and when, and keeps closed ones folded away', async () => {
    api({ 'GET /trace/c1/tasks': { body: { tasks: [TASK, DONE] } } })
    open()
    expect(await screen.findByText('Send the notice to the bank')).toBeInTheDocument()
    expect(screen.getByText('Due in 2 days')).toBeInTheDocument()
    expect(screen.getByLabelText('Assigned to')).toHaveValue('SI Iyer')
    expect(screen.getByText('Insp. Rao')).toBeInTheDocument() // a closed task's assignee, as text
    expect(screen.getByText('Tasks · 1 open')).toBeInTheDocument()
    expect(screen.getByText('Done and dropped · 1')).toBeInTheDocument()
  })

  it('adds a task with what, who and by when', async () => {
    const calls = api({
      'GET /trace/c1/tasks': { body: { tasks: [] } },
      'POST /trace/c1/tasks': (b) => ({ status: 201, body: { ...TASK, ...b } }),
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Add a task' }))
    const form = screen.getByRole('form', { name: 'Add a task' })
    const save = within(form).getByRole('button', { name: 'Add the task' })
    expect(save).toBeDisabled()
    await user.type(within(form).getByLabelText('What has to be done'), 'Collect the phone extraction')
    await user.type(within(form).getByLabelText('Assigned to'), 'SI Pal')
    await user.click(save)
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST').body).toEqual({ title: 'Collect the phone extraction', assignee: 'SI Pal', due_on: '', notes: '' })
  })

  it('marks a task done in one click', async () => {
    const calls = api({
      'GET /trace/c1/tasks': { body: { tasks: [TASK] } },
      'PATCH /tasks/t1': (b) => ({ body: { ...TASK, ...b } }),
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Mark done' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH').body).toEqual({ status: 'done' })
  })

  it('asks why before dropping a task, and sends the reason', async () => {
    const calls = api({
      'GET /trace/c1/tasks': { body: { tasks: [TASK] } },
      'PATCH /tasks/t1': (b) => ({ body: { ...TASK, ...b } }),
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Drop…' }))
    const drop = screen.getByRole('button', { name: 'Drop the task' })
    expect(drop).toBeDisabled()
    await user.type(screen.getByLabelText('Why drop it?'), 'Bank answered on the portal')
    await user.click(drop)
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH').body).toEqual({ status: 'dropped', note: 'Bank answered on the portal' })
  })

  it('stays open after the last open task is closed', async () => {
    let tasks = [TASK]
    api({
      'GET /trace/c1/tasks': () => ({ body: { tasks } }),
      'PATCH /tasks/t1': (b) => { tasks = [{ ...TASK, ...b, days_left: null }]; return { body: tasks[0] } },
    })
    const user = userEvent.setup()
    const { container } = open()
    await user.click(await screen.findByRole('button', { name: 'Mark done' }))
    await screen.findByText('Done and dropped · 1')
    expect(container.querySelector('.tasks-panel')).toHaveAttribute('open')
  })

  it("shows the server's refusal", async () => {
    api({
      'GET /trace/c1/tasks': { body: { tasks: [] } },
      'POST /trace/c1/tasks': { status: 400, body: { detail: 'This looks like a private key or seed phrase.' } },
    })
    const user = userEvent.setup()
    open()
    await user.click(await screen.findByRole('button', { name: 'Add a task' }))
    await user.type(screen.getByLabelText('What has to be done'), 'x')
    await user.click(screen.getByRole('button', { name: 'Add the task' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('private key or seed phrase')
  })

  it('shows nothing without a case', () => {
    const { container } = render(<TasksPanel result={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('what a due date says', () => {
  it('reads overdue, today, this week, later and closed', () => {
    expect(dueText({ ...TASK, days_left: -3, overdue: true })).toEqual({ tone: 'red', text: 'Overdue by 3 days' })
    expect(dueText({ ...TASK, days_left: 0 })).toEqual({ tone: 'red', text: 'Due today' })
    expect(dueText({ ...TASK, days_left: 1 })).toEqual({ tone: 'amber', text: 'Due in 1 day' })
    expect(dueText({ ...TASK, days_left: 30, due_on: '2026-12-14' })).toEqual({ tone: '', text: 'Due 14 Dec 2026' })
    expect(dueText({ ...TASK, due_on: '', days_left: null })).toEqual({ tone: '', text: 'No due date' })
    expect(dueText(DONE).text).toBe('Done')
    expect(dueText({ ...TASK, status: 'dropped' }).text).toBe('Dropped')
  })

  it('writes history as short lines with any reason', () => {
    expect(historyLine({ at: '2026-11-14T05:00:00Z', action: 'dropped', changed: ['status'], note: 'Bank answered' }))
      .toBe('2026-11-14 dropped: Bank answered')
    expect(historyLine({ at: '2026-11-14T05:00:00Z', action: 'changed', changed: ['assignee', 'due_on'] }))
      .toBe('2026-11-14 changed assignee, due date')
    expect(historyLine({ at: '2026-11-15T05:00:00Z', action: 'reopened', changed: ['status'], note: 'Wrong account' }))
      .toBe('2026-11-15 opened again: Wrong account')
  })
})

describe("the home page's tasks-due card", () => {
  it('lists tasks due soon, linking to the case', async () => {
    api({ 'GET /tasks/due': { body: { tasks: [{ ...TASK, days_left: -1, overdue: true }] } } })
    render(<MemoryRouter><TaskDeadlines /></MemoryRouter>)
    const link = await screen.findByRole('link', { name: /Send the notice to the bank/ })
    expect(link).toHaveAttribute('href', '/case/c1?tab=evidence')
    expect(within(link).getByText('Overdue by 1 day')).toBeInTheDocument()
  })

  it('shows nothing when no task is due, or the list cannot be reached', async () => {
    const calls = api({ 'GET /tasks/due': { body: { tasks: [] } } })
    const { container } = render(<MemoryRouter><TaskDeadlines /></MemoryRouter>)
    await waitFor(() => expect(calls.length).toBe(1))
    expect(container).toBeEmptyDOMElement()
  })
})
