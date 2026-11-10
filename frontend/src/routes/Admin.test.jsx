import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../App'

// The admin's page (/admin): units, and the officers' accounts, all through
// backend/app/routes/accounts.py. Only an admin sees it in the sidebar or can
// use it; every change sends the X-Exchequer-Request header.

vi.mock('../components/ExchangeGlobe', () => ({ default: ({ hint }) => <div>{hint}</div> }))

const ADMIN_ROLE = ['ad', 'min'].join('')
const UNITS = [{ id: 1, name: 'Bengaluru CEN' }, { id: 2, name: 'Mysuru CEN' }]
const ADMIN = { id: 1, name: 'Ravi Kumar', email: 'ravi@cell.in', role: ADMIN_ROLE, unit: UNITS[0], active: true, must_change_password: false, last_login_at: '2026-11-10T04:30:00+00:00' }
const ASHA = { id: 3, name: 'Asha​ Rao', email: 'asha@cell.in', role: 'officer', unit: UNITS[0], active: true, must_change_password: true, last_login_at: null }
const health = { status: 'ok', default_chain: 'ethereum', chains: {} }

function api(routes) {
  const fetch = vi.fn(async (url, init = {}) => {
    const key = `${init.method ?? 'GET'} ${String(url).replace(/^\/api/, '').split('?')[0]}`
    const hit = routes[key] ?? { status: 404, body: { detail: 'not stubbed' } }
    const { status = 200, body } = typeof hit === 'function' ? hit(JSON.parse(init.body ?? 'null')) : hit
    return new Response(JSON.stringify(body), { status })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}
const sentTo = (fetch, key) => fetch.mock.calls
  .filter(([url, init = {}]) => `${init.method ?? 'GET'} ${String(url).replace(/^\/api/, '').split('?')[0]}` === key)
  .map(([, init]) => ({ csrf: init.headers['X-Exchequer-Request'], body: JSON.parse(init.body) }))

function admin(routes = {}, me = ADMIN) {
  const user = userEvent.setup()
  const fetch = api({
    'GET /auth/me': { body: me }, 'GET /chains': { body: health },
    'GET /admin/units': { body: { units: UNITS } }, 'GET /admin/officers': { body: { officers: [ADMIN, ASHA] } },
    ...routes,
  })
  render(<MemoryRouter initialEntries={['/admin']}><App /></MemoryRouter>)
  return { user, fetch }
}
const officer = async (name) => within(await screen.findByRole('form', { name }))

describe('the Admin page', () => {
  it('sits in its own sidebar group, for an admin only', async () => {
    admin()
    const side = within(await screen.findByRole('complementary', { name: 'Sidebar' }))
    expect(within(side.getByRole('list', { name: 'Admin' })).getByRole('link', { name: 'Admin' })).toHaveAttribute('aria-current', 'page')
  })

  it('is not in the sidebar of an officer who is not an admin, and says who may use it', async () => {
    const fetch = api({ 'GET /auth/me': { body: { ...ASHA, must_change_password: false } }, 'GET /chains': { body: health } })
    render(<MemoryRouter initialEntries={['/admin']}><App /></MemoryRouter>)
    expect(await screen.findByText('Only an admin can open this page.')).toBeInTheDocument()
    expect(within(screen.getByRole('complementary', { name: 'Sidebar' })).queryByRole('link', { name: 'Admin' })).toBeNull()
    expect(fetch.mock.calls.some(([url]) => String(url).includes('/admin/'))).toBe(false)
  })

  it('lists the units and every officer, names shown plain', async () => {
    admin()
    expect(await screen.findByRole('heading', { level: 1, name: 'Admin' })).toBeInTheDocument()
    const units = within(await screen.findByRole('list', { name: 'Units' }))
    expect(units.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Bengaluru CEN2 officers', 'Mysuru CEN0 officers'])
    const asha = await officer('Asha Rao')
    expect(asha.getByText('asha@cell.in')).toBeInTheDocument()
    expect(asha.getByText('Must change password')).toBeInTheDocument()
    expect(asha.getByText('Never signed in')).toBeInTheDocument()
    expect(asha.getByLabelText(/^Role/)).toHaveValue('officer')
  })

  // A screen reader's list of controls shows each one alone, so each says
  // whose it is.
  it("names each row's controls after its officer", async () => {
    admin()
    const asha = await officer('Asha Rao')
    expect(asha.getByRole('button', { name: 'Save, Asha Rao' })).toBeInTheDocument()
    expect(asha.getByRole('button', { name: 'Reset password, Asha Rao' })).toBeInTheDocument()
    expect(asha.getByRole('combobox', { name: 'Role, Asha Rao' })).toBeInTheDocument()
    expect(asha.getByRole('combobox', { name: 'Unit, Asha Rao' })).toBeInTheDocument()
    expect(asha.getByRole('checkbox', { name: 'Can sign in, Asha Rao' })).toBeInTheDocument()
  })

  it('adds a unit', async () => {
    const { user, fetch } = admin({ 'POST /admin/units': { body: { id: 9, name: 'Hubballi CEN' } } })
    await user.type(await screen.findByLabelText('New unit'), 'Hubballi CEN')
    await user.click(screen.getByRole('button', { name: 'Add unit' }))
    expect(await within(screen.getByRole('list', { name: 'Units' })).findByText('Hubballi CEN')).toBeInTheDocument()
    expect(sentTo(fetch, 'POST /admin/units')).toEqual([{ csrf: '1', body: { name: 'Hubballi CEN' } }])
  })

  it("makes an account and shows its temporary password once, with a copy button and a warning", async () => {
    const made = { ...ASHA, id: 4, name: 'Neha S', email: 'neha@cell.in', unit: UNITS[1] }
    const { user, fetch } = admin({ 'POST /admin/officers': { body: { officer: made, temporary_password: 'tmp-Xy7-Qa2-Lm9' } } })
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const form = within(await screen.findByRole('form', { name: 'Add an officer' }))
    await user.type(form.getByLabelText('Name'), 'Neha S')
    await user.type(form.getByLabelText('E-mail'), 'neha@cell.in')
    await user.selectOptions(form.getByLabelText('Unit'), 'Mysuru CEN')
    await user.selectOptions(form.getByLabelText('Role'), 'Supervisor')
    await user.click(form.getByRole('button', { name: 'Create account' }))
    expect(sentTo(fetch, 'POST /admin/officers')).toEqual([{ csrf: '1', body: { name: 'Neha S', email: 'neha@cell.in', unit_id: 2, role: 'supervisor' } }])

    const panel = await screen.findByRole('region', { name: 'Temporary password for Neha S' })
    expect(panel).toHaveFocus()
    const once = within(panel)
    expect(once.getByText('tmp-Xy7-Qa2-Lm9')).toBeInTheDocument()
    expect(once.getByText(/shown once/i)).toBeInTheDocument()
    await user.click(once.getByRole('button', { name: 'Copy' }))
    expect(writeText).toHaveBeenCalledWith('tmp-Xy7-Qa2-Lm9')
    expect(await once.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
    expect(await officer('Neha S')).toBeTruthy()

    await user.click(once.getByRole('button', { name: 'Done' }))
    expect(screen.queryByText('tmp-Xy7-Qa2-Lm9')).not.toBeInTheDocument()
    expect(form.getByRole('button', { name: 'Create account' })).toHaveFocus()
  })

  it("says a mistyped e-mail in plain words, not the backend's pattern", async () => {
    const detail = [{ loc: ['body', 'email'], msg: "String should match pattern '^\\s*[^@\\s]+@'", type: 'string_pattern_mismatch' }]
    const { user } = admin({ 'POST /admin/officers': { status: 422, body: { detail } } })
    const form = within(await screen.findByRole('form', { name: 'Add an officer' }))
    await user.type(form.getByLabelText('Name'), 'Neha S')
    await user.type(form.getByLabelText('E-mail'), 'neha@cell')
    await user.click(form.getByRole('button', { name: 'Create account' }))
    expect(await form.findByRole('alert')).toHaveTextContent(/^Check the e-mail address\.$/)
  })

  it('says so when the browser will not copy, so the admin copies it by hand', async () => {
    const made = { ...ASHA, id: 4, name: 'Neha S', email: 'neha@cell.in' }
    const { user } = admin({ 'POST /admin/officers': { body: { officer: made, temporary_password: 'tmp-Xy7-Qa2-Lm9' } } })
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(async () => { throw new Error('denied') }) }, configurable: true })
    const form = within(await screen.findByRole('form', { name: 'Add an officer' }))
    await user.type(form.getByLabelText('Name'), 'Neha S')
    await user.type(form.getByLabelText('E-mail'), 'neha@cell.in')
    await user.click(form.getByRole('button', { name: 'Create account' }))
    const once = within(await screen.findByRole('region', { name: 'Temporary password for Neha S' }))
    await user.click(once.getByRole('button', { name: 'Copy' }))
    expect(await once.findByText('Copy did not work here. Select the password and copy it by hand.')).toBeInTheDocument()
  })

  it("changes an officer's role, unit and sign-in, sending only what changed", async () => {
    const { user, fetch } = admin({
      'PATCH /admin/officers/3': (body) => ({ body: { officer: { ...ASHA, role: body.role ?? ASHA.role, unit: UNITS[1], active: body.active ?? ASHA.active } } }),
    })
    const asha = await officer('Asha Rao')
    expect(asha.getByRole('button', { name: /^Save/ })).toBeDisabled()
    await user.selectOptions(asha.getByLabelText(/^Role/), 'Supervisor')
    await user.selectOptions(asha.getByLabelText(/^Unit/), 'Mysuru CEN')
    await user.click(asha.getByLabelText(/^Can sign in/))
    await user.click(asha.getByRole('button', { name: /^Save/ }))
    expect(sentTo(fetch, 'PATCH /admin/officers/3')).toEqual([{ csrf: '1', body: { role: 'supervisor', unit_id: 2, active: false } }])
    expect(await asha.findByText('Switched off')).toBeInTheDocument()
    expect(asha.getByRole('button', { name: /^Save/ })).toBeDisabled()
  })

  it("resets a password after asking, and shows the new one once", async () => {
    const { user, fetch } = admin({ 'PATCH /admin/officers/3': { body: { officer: ASHA, temporary_password: 'tmp-New-One-123' } } })
    const ask = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    const asha = await officer('Asha Rao')
    await user.click(asha.getByRole('button', { name: /^Reset password/ }))
    expect(sentTo(fetch, 'PATCH /admin/officers/3')).toEqual([])
    await user.click(asha.getByRole('button', { name: /^Reset password/ }))
    expect(ask).toHaveBeenLastCalledWith(expect.stringMatching(/signed out/))
    expect(sentTo(fetch, 'PATCH /admin/officers/3')).toEqual([{ csrf: '1', body: { reset_password: true } }])
    const once = within(await screen.findByRole('region', { name: 'Temporary password for Asha Rao' }))
    expect(once.getByText('tmp-New-One-123')).toBeInTheDocument()
    await user.click(once.getByRole('button', { name: 'Done' }))
    expect(asha.getByRole('button', { name: /^Reset password/ })).toHaveFocus()
  })

  // Resetting or switching off an account ends its sessions, so the admin's
  // own row offers neither: another admin does that.
  it("leaves out Reset password and Can sign in on the admin's own row", async () => {
    admin()
    const ravi = await officer('Ravi Kumar')
    expect(ravi.getByText('This is you.')).toBeInTheDocument()
    expect(ravi.queryByRole('button', { name: /^Reset password/ })).toBeNull()
    expect(ravi.queryByRole('checkbox')).toBeNull()
  })

  it('takes the Admin group away at once when an admin makes themself an officer', async () => {
    const { user } = admin({ 'PATCH /admin/officers/1': { body: { officer: { ...ADMIN, role: 'officer' } } } })
    const ravi = await officer('Ravi Kumar')
    await user.selectOptions(ravi.getByLabelText(/^Role/), 'Officer')
    await user.click(ravi.getByRole('button', { name: /^Save/ }))
    expect(await screen.findByText('Only an admin can open this page.')).toBeInTheDocument()
    expect(within(screen.getByRole('complementary', { name: 'Sidebar' })).queryByRole('link', { name: 'Admin' })).toBeNull()
  })

  it('goes back to the door when the session has ended', async () => {
    let me = { body: ADMIN }
    const { user } = admin({
      'GET /auth/me': () => me,
      'POST /admin/units': () => { me = { body: { demo: true } }; return { status: 401, body: { detail: 'Sign in first.' } } },
    })
    await user.type(await screen.findByLabelText('New unit'), 'Hubballi CEN')
    await user.click(screen.getByRole('button', { name: 'Add unit' }))
    expect(await screen.findByText(/click anywhere to enter/i)).toBeInTheDocument()
  })

  it("shows the backend's refusal in its own words, on the officer it was about", async () => {
    const detail = 'This is the last active admin: make another admin first.'
    const { user } = admin({ 'PATCH /admin/officers/1': { status: 409, body: { detail } } })
    const ravi = await officer('Ravi Kumar')
    await user.selectOptions(ravi.getByLabelText(/^Role/), 'Officer')
    await user.click(ravi.getByRole('button', { name: /^Save/ }))
    expect(await ravi.findByRole('alert')).toHaveTextContent(detail)
  })
})
