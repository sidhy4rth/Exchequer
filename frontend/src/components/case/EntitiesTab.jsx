import { memo, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { fetchRelatedCases } from '../../api'
import GraphView, { PALETTES } from '../GraphView'
import FlowView from '../FlowView'
import RoleSwatch from '../RoleSwatch'
import { PATTERN_VALIDATION, validationLine } from '../confidence'
import { flagCounts, roleOf } from '../mapRoles'
import { usePhone } from '../../phone'
import { currentTheme } from '../../theme'
import { plain } from '../../text'
import { entityGroups, groupLayout } from './entityGroups'
import { Address, PATTERN_NAME, RISK_NAME, middle, num, when } from './format'
import './EntitiesTab.css'

const count = (n, noun) => `${n} ${noun}${n === 1 ? '' : 's'}`
// A line toward the exchange is green, one into a frozen wallet red.
const tone = (to) => (['exchange', 'deposit', 'route'].includes(to) ? 'go' : to === 'frozen' ? 'risk' : 'plain')

/** The groups as a map: a bubble per group, as big as its wallet count, and a
 * line per pair, as wide as the gross amount between them. Each bubble is a
 * button that opens its group's card. */
function GroupMap({ groups, links, at, chosen, onChoose, labelledBy }) {
  const perColumn = groups.reduce((by, g) => ({ ...by, [g.depth]: (by[g.depth] ?? 0) + 1 }), {})
  const rows = Math.max(1, ...Object.values(perColumn))
  const height = Math.max(360, rows * 110)
  const most = Math.max(...links.map((l) => l.gross), 1)
  const curve = ({ x: x1, y: y1 }, { x: x2, y: y2 }) => {
    const [ax, ay, bx, by] = [x1 * 1000, y1 * height, x2 * 1000, y2 * height]
    const [c1, c2] = Math.abs(ax - bx) < 1 ? [ax + 90, bx + 90] : [(ax + bx) / 2, (ax + bx) / 2]
    return `M${ax} ${ay}C${c1} ${ay} ${c2} ${by} ${bx} ${by}`
  }
  return (
    <>
      <div className="ent-map" role="group" aria-labelledby={labelledBy} style={{ height }}>
        <svg className="ent-lines" aria-hidden="true" viewBox={`0 0 1000 ${height}`} preserveAspectRatio="none">
          {links.map((l) => (
            <path key={`${l.from}>${l.to}`} data-link={`${l.from}>${l.to}`} className={tone(l.to)} d={curve(at[l.from], at[l.to])} fill="none"
              strokeWidth={(1.5 + 8 * Math.sqrt(l.gross / most)).toFixed(2)} strokeDasharray={l.style === 'dashed' ? '6 5' : undefined} vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
        {groups.map((g) => (
          <button key={g.key} type="button" className={`ent-node${g.key === chosen ? ' on' : ''}`} aria-pressed={g.key === chosen}
            style={{ left: `${at[g.key].x * 100}%`, top: `${at[g.key].y * 100}%`, '--d': `${Math.round(Math.min(72, 24 + 10 * Math.sqrt(g.addresses.length - 1)))}px` }}
            onClick={() => onChoose(g.key)}>
            <span aria-hidden="true" className={`ent-bubble ${g.kind}${g.inferred ? ' inferred' : ''}${g.key === 'reported' ? ' reported' : ''}`} />
            <span className="ent-label">{g.name}<span className="ent-count">{` · ${count(g.addresses.length, 'wallet')}`}</span></span>
          </button>
        ))}
      </div>
      <p className="ent-legend">
        <span>bubble = wallets in the group</span>
        <span>line width = gross amount between groups; the victim's share is on Flow</span>
        <span>dashed = inferred</span>
      </p>
    </>
  )
}

/** How often a shape fired on real wallets (README, "Validation against real wallets"). */
function Measured({ pattern }) {
  const v = PATTERN_VALIDATION[pattern]
  if (!v) return null
  const dots = (n, of) => <span className="ent-dots">{Array.from({ length: of }, (_, i) => <span key={i} className={i < n ? 'on' : ''} />)}</span>
  return (
    <div className="ent-measured" role="img" aria-label={`${PATTERN_NAME[pattern]} seen in ${v.fraud} of ${v.fraudOf} documented fraud wallets and ${v.ordinary} of ${v.ordinaryOf} ordinary ones`}>
      {dots(v.fraud, v.fraudOf)}<span>{v.fraud} / {v.fraudOf} fraud wallets</span>
      {dots(v.ordinary, v.ordinaryOf)}<span>{v.ordinary} / {v.ordinaryOf} ordinary wallets</span>
    </div>
  )
}

/** The card for the group chosen: for a split, what came in and how it was
 * divided; for any group, the gross in and out of it and its wallets. */
function GroupCard({ group, groups, links, result, unit }) {
  const [open, setOpen] = useState(false)
  const listId = useId()
  const nodes = new Map(result.graph.nodes.map((n) => [n.address, n]))
  const edges = result.graph.edges
  const nameOf = Object.fromEntries(groups.map((g) => [g.key, g.name]))
  const splits = group.key === 'split' ? (result.findings ?? []).filter((f) => f.pattern === 'amount_split') : []
  // Each recipient's amount from the graph: the finding sorts its amounts but not its recipients.
  const paid = splits.flatMap((f) => edges.filter((e) => e.source === f.evidence.address && f.evidence.recipients.includes(e.target)))
    .sort((a, b) => b.value_native - a.value_native)
  const into = (a) => edges.filter((e) => e.target === a).reduce((sum, e) => sum + (e.value_native || 0), 0)
  const out = (a) => edges.filter((e) => e.source === a).reduce((sum, e) => sum + (e.value_native || 0), 0)
  const wallets = splits.length ? paid.map((e) => ({ address: e.target, amount: e.value_native, dir: 'in' }))
    : group.addresses.map((a) => (into(a) > 0 ? { address: a, amount: into(a), dir: 'in' } : { address: a, amount: out(a), dir: 'out' }))
  const risky = (a) => Boolean(nodes.get(a)?.risk_category)
  const tag = (n) => plain(n?.label) || RISK_NAME[n?.risk_category] || n?.risk_category || (n?.inferred_exchange ? `Probable ${plain(n.inferred_exchange)} deposit` : null)
  const flows = [...links.filter((l) => l.to === group.key).map((l) => ['In from', l.from, l]), ...links.filter((l) => l.from === group.key).map((l) => ['Out to', l.to, l])]
  return (
    <section className="card ent-card" aria-label={`Selected group: ${group.name}`}>
      <div className="ent-card-head">
        <h2>{group.name}</h2>
        {splits.length > 0 && <span className="pill amber">hint · a shape, not evidence</span>}
      </div>
      {splits.map((f) => {
        const amounts = paid.filter((e) => e.source === f.evidence.address).map((e) => e.value_native)
        return (
          <div className="ent-split" key={f.evidence.address}>
            <Address value={f.evidence.address} head={12} tail={10} />
            <p className="ent-split-sum">
              <span className="ent-split-in"><b>{num(f.evidence.total_in_native)}</b> in</span>
              <svg aria-hidden="true" width="40" height="12" viewBox="0 0 40 12" fill="none" strokeWidth="1.3"><path d="M1 6h36M33 2l4 4-4 4" /></svg>
              <span className="ent-split-out"><b>{f.evidence.branch_count}</b> recipients</span>
            </p>
            <div className="ent-bars" aria-hidden="true">
              {paid.filter((e) => e.source === f.evidence.address).map((e) => (
                <span key={e.target} title={`${num(e.value_native)} ${unit}`} className={risky(e.target) ? 'risk' : ''} style={{ height: `${Math.max(6, (100 * e.value_native) / amounts[0])}%` }} />
              ))}
            </div>
            <p className="note ent-range">
              <span>{`${num(Math.min(...amounts))} to ${num(amounts[0])} ${unit} each`}</span>
              <span>{` · the largest is ${Math.round(100 * f.evidence.largest_branch_share)}% of the total`}</span>
            </p>
            <Measured pattern="amount_split" />
          </div>
        )
      })}
      {flows.length > 0 && (
        <ul className="ent-flows">
          {flows.map(([dir, other, l]) => <li key={`${l.from}>${l.to}`}><span>{dir} {nameOf[other]}</span><span className="num">{num(l.gross)} {unit} gross</span></li>)}
        </ul>
      )}
      <button type="button" className="ent-open" aria-expanded={open} aria-controls={listId} onClick={() => setOpen((v) => !v)}>
        {`${open ? 'Hide' : 'Open'} the ${count(wallets.length, 'wallet')}`}
      </button>
      <ul className="ent-wallets" id={listId} hidden={!open}>
        {wallets.map((w) => (
          <li key={w.address}>
            <Address value={w.address} />
            {tag(nodes.get(w.address)) && <span className={`note${risky(w.address) ? ' risk' : ''}`}>{tag(nodes.get(w.address))}</span>}
            <span className="num">{num(w.amount)} {unit} {w.dir}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Other complaints that reached this case's wallets, from the case book
 * (GET /cases/correlate). A stored case's answer comes from the page; a
 * recorded or unsaved one is not in the book, so it asks which wallets two
 * or more stored complaints share and keeps the ones in this case, on this
 * case's chain (the book matches a wallet by chain and address). */
function OtherComplaints({ caseId, correlation, groups, own, chain }) {
  const [asked, setAsked] = useState(null)
  const headId = useId()
  useEffect(() => {
    if (caseId) return undefined
    let cancelled = false
    fetchRelatedCases(null)
      .then((r) => { if (!cancelled) setAsked(r) })
      .catch(() => { if (!cancelled) setAsked({ failed: true }) })
    return () => { cancelled = true }
  }, [caseId])
  const data = caseId ? correlation : asked
  const groupOf = new Map(groups.flatMap((g) => g.addresses.map((a) => [a.toLowerCase(), g.name])))
  const me = String(own ?? '').toLowerCase()
  const onChain = String(chain || 'ethereum')
  const shared = (data?.clusters ?? [])
    .filter((c) => String(c.chain || 'ethereum') === onChain && groupOf.has(String(c.address).toLowerCase()))
    .map((c) => ({
      address: c.address,
      group: groupOf.get(String(c.address).toLowerCase()),
      others: (c.reported_addresses ?? []).filter((a) => String(a).toLowerCase() !== me).length + (c.other_complaints ?? 0),
    }))
    .filter((s) => s.others > 0)
  return (
    <section className="card ent-other" aria-labelledby={headId}>
      <h2 id={headId}>Other complaints</h2>
      <svg className="ent-other-mark" aria-hidden="true" viewBox="0 0 300 30" fill="none">
        <circle cx="15" cy="15" r="12" /><path className="them" d="M33 15h96M171 15h96" /><circle className="them" cx="150" cy="15" r="9" /><circle className="them" cx="285" cy="15" r="12" />
      </svg>
      {data == null && <p className="note">Checking the case book…</p>}
      {data?.failed && <p className="note">The case book could not be checked just now.</p>}
      {data && !data.failed && (shared.length > 0 ? (
        <ul className="ent-shared">
          {shared.map((s) => (
            <li key={s.address}><Address value={s.address} /><span className="note">{s.group}</span><span>{count(s.others, 'other complaint')}</span></li>
          ))}
        </ul>
      ) : (
        <p className="note">{caseId
          ? 'No other stored complaint shares a wallet with this case yet. When one does, it appears here with the wallet they share.'
          : "This case is not in the case book, so only wallets that two or more stored complaints already share can show here. None of this case's wallets is one yet."}</p>
      ))}
    </section>
  )
}

const MAP_VIEWS = [
  { key: 'bubble', label: 'Bubble map', other: 'hop' },
  { key: 'hop', label: 'Hop map', other: 'bubble' },
]
const MAP_NAME = { bubble: 'bubble map', hop: 'hop map' }
// The role's colour on the card: red for a list's confirmation and for a
// pattern that fired (the dashed swatch says it is not confirmed), green only
// for an exchange and an inferred deposit.
const ROLE_TONE = {
  seed: 'var(--text)', risk: 'var(--risk)', flagged: 'var(--risk)', exchange: 'var(--go)', inferred: 'var(--go-soft)',
  gambling: 'var(--text-2)', service: 'var(--text-2)', node: 'var(--text-2)',
}

/** The skin the page is in, kept current as it flips (as GraphView does), so
 * a swatch can take the very colour the bubble map paints that role in. */
function useTheme() {
  const [theme, setTheme] = useState(currentTheme)
  useEffect(() => {
    const onChange = (e) => setTheme(e.detail === 'light' ? 'light' : 'dark')
    window.addEventListener('themechange', onChange)
    return () => window.removeEventListener('themechange', onChange)
  }, [])
  return theme
}

/** The bubble map's key, in its words, for the phone where the map is compact. */
const BUBBLE_KEY = [
  ['seed', 'Reported address'],
  ['risk', 'Sanctioned / mixer / frozen (confirmed)'],
  ['flagged', 'Possible flag · pattern (not confirmed)'],
  ['gambling', 'Gambling platform wallet'],
  ['exchange', 'Labelled exchange wallet'],
  ['inferred', 'Probable deposit address (inferred)'],
  ['service', 'Service contract / router, not expanded'],
  ['node', 'Traced address'],
]

/** The pattern names a wallet's flags carry, in words. */
const patternsOf = (node) => (node.flags ?? []).filter((f) => f !== node.risk_category).map((f) => PATTERN_NAME[f] ?? String(f).replace(/_/g, ' '))

/** What the card calls a wallet, by the role it plays on the maps. */
function walletRole(node) {
  const role = roleOf(node)
  const risk = plain(node.risk_entity) || RISK_NAME[node.risk_category] || node.risk_category
  const name = {
    seed: 'Reported address',
    risk: `Confirmed risk · ${risk}`,
    gambling: `Gambling platform · ${risk}`,
    exchange: `Labelled exchange · ${plain(node.label) || plain(node.exchange)}`,
    inferred: `Probable deposit · ${plain(node.inferred_exchange)}`,
    service: `Service contract${node.router || node.label ? ` · ${plain(node.router ?? node.label)}` : ''}`,
    flagged: `Possible flag · ${patternsOf(node).join(', ')}`,
    node: 'Traced address',
  }[role]
  return { role, name }
}

/** "Bubble map | Hop map": one radio group, the arrow keys move and choose,
 * and the chosen pill slides under the label. */
function MapSwitch({ view, onChange, refs }) {
  const onKeyDown = (event) => {
    const keys = { ArrowLeft: 'flip', ArrowRight: 'flip', ArrowUp: 'flip', ArrowDown: 'flip', Home: 'bubble', End: 'hop' }
    const step = keys[event.key]
    if (!step) return
    event.preventDefault()
    const next = step === 'flip' ? (view === 'bubble' ? 'hop' : 'bubble') : step
    onChange(next)
    refs.current[next]?.focus()
  }
  return (
    <div className={`ent-seg${view === 'hop' ? ' hop' : ''}`} role="radiogroup" aria-label="Map view" onKeyDown={onKeyDown}>
      <span className="ent-seg-pill" aria-hidden="true" />
      {MAP_VIEWS.map((v) => (
        <button key={v.key} ref={(el) => { refs.current[v.key] = el }} type="button" role="radio" aria-checked={view === v.key}
          tabIndex={view === v.key ? 0 : -1} onClick={() => onChange(v.key)}>
          {v.label}
        </button>
      ))}
    </div>
  )
}

/** The selected wallet: its role, full address, hop and amounts, the same on
 * both maps. Beside the maps on a wide screen, never over them; a sheet that
 * slides up from the bottom on a phone. */
function SelectedWallet({ node, result, unit, view, onShowOther, onClear, phone, open, onRoom }) {
  const [copied, setCopied] = useState(false)
  const theme = useTheme()
  const sheetRef = useRef(null)
  // The sheet takes focus as it opens, so a screen reader or a keyboard
  // lands on it rather than at the far end of the page.
  useEffect(() => {
    if (phone && open) sheetRef.current?.focus({ preventScroll: true })
  }, [phone, open])
  // While the sheet is up, the page keeps room for it: a control the
  // keyboard reaches scrolls clear of it, and the page's end can too.
  useEffect(() => {
    const el = sheetRef.current
    if (!phone || !open || !el) return undefined
    const root = document.documentElement
    const before = root.style.scrollPaddingBottom
    const fit = () => {
      const room = el.offsetHeight + 16
      root.style.scrollPaddingBottom = `${room}px`
      onRoom?.(room)
    }
    fit()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(fit)
    observer?.observe(el)
    return () => {
      observer?.disconnect()
      root.style.scrollPaddingBottom = before
      onRoom?.(0)
    }
  }, [phone, open, onRoom])
  useEffect(() => {
    if (!copied) return undefined
    const timer = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(timer)
  }, [copied])
  useEffect(() => { setCopied(false) }, [node?.id])
  if (!node) return null
  const { role, name } = walletRole(node)
  const address = node.address ?? node.id
  const other = view === 'bubble' ? 'hop' : 'bubble'
  const amount = (v) => (v == null ? '—' : `${num(v)} ${unit}`)
  const onRoute = role !== 'seed' && (result.trace_path ?? []).some((p) => p.address === address)
  const to = plain(result.exchange_label) || plain(result.exchange)
  const copy = () => navigator.clipboard?.writeText(address).then(() => setCopied(true), () => {})
  const onKeyDown = (event) => {
    if (event.key !== 'Escape') return
    event.preventDefault()
    onClear()
  }
  const facts = (
    <>
      {role === 'seed' && node.risk_category && <span className="ent-pick-tag">{RISK_NAME[node.risk_category] ?? node.risk_category}</span>}
      {role === 'risk' && node.risk_label && <p className="ent-pick-fact risk">{plain(node.risk_label)}</p>}
      {role === 'flagged' && <p className="ent-pick-fact">A pattern fired here: a lead to check, not a finding.</p>}
      {onRoute && <p className="ent-pick-route"><span aria-hidden="true" />{to ? `On the traced route to ${to}` : 'On the traced route'}</p>}
    </>
  )
  const head = (
    <div className="ent-pick-role">
      <RoleSwatch role={role} color={PALETTES[theme][role]} />
      <span style={{ color: ROLE_TONE[role] }}>{name}</span>
    </div>
  )
  if (phone) {
    // On the page's body, so no panel's transform or blur can pin the
    // sheet inside it instead of to the foot of the screen.
    return createPortal(
      <section ref={sheetRef} tabIndex={-1} className={`ent-sheet${open ? ' open' : ''}`} aria-label="Selected wallet" aria-hidden={!open} onKeyDown={onKeyDown}>
        <div className="ent-sheet-grab" aria-hidden="true" />
        <div className="ent-sheet-head">
          <div className="ent-sheet-main">
            {head}
            <p className="ent-sheet-short">{middle(address, 6, 4)}</p>
            <p className="ent-pick-addr">{address}</p>
          </div>
          <span className="ent-sheet-hop">{node.depth === 0 ? 'Hop 0 · reported' : `Hop ${node.depth}`}</span>
        </div>
        {facts}
        <dl className="ent-sheet-stats">
          <div><dt>Received</dt><dd>{amount(node.total_in_native)}</dd></div>
          <div><dt>Sent</dt><dd>{amount(node.total_out_native)}</dd></div>
        </dl>
        <div className="ent-sheet-acts">
          <button type="button" className="strong" onClick={copy} tabIndex={open ? 0 : -1}>Copy address</button>
          <button type="button" onClick={onShowOther} tabIndex={open ? 0 : -1}>{`See on ${MAP_NAME[other]}`}</button>
          <button type="button" onClick={onClear} tabIndex={open ? 0 : -1}>Close</button>
        </div>
        <p className="ent-sheet-msg" role="status">{copied ? 'Address copied' : ''}</p>
      </section>,
      document.body,
    )
  }
  return (
    <section className="ent-pick" aria-label="Selected wallet" onKeyDown={onKeyDown}>
      <div className="ent-pick-top">{head}<span className="micro">Selected</span></div>
      {facts}
      <div className="ent-pick-addr-row">
        <p className="ent-pick-addr">{address}</p>
        <button type="button" className="ent-pick-copy" onClick={copy} aria-label="Copy address">{copied ? 'Copied' : 'Copy'}</button>
      </div>
      <dl className="ent-pick-rows">
        <div><dt>Hop</dt><dd>{node.depth === 0 ? '0 · reported' : node.depth}</dd></div>
        <div><dt>Received</dt><dd>{amount(node.total_in_native)}</dd></div>
        <div><dt>Sent</dt><dd>{amount(node.total_out_native)}</dd></div>
      </dl>
      <p className="note">Selected on both maps — switch views to see it in context.</p>
      <div className="ent-pick-acts">
        <button type="button" onClick={onShowOther}>{`Show on ${MAP_NAME[other]}`}</button>
        <button type="button" className="quiet" onClick={onClear}>Clear</button>
      </div>
      <p className="visually-hidden" role="status">{copied ? 'Address copied' : ''}</p>
    </section>
  )
}

/** Every wallet, on two maps that share one selection: the bubble map (the
 * graph) and the hop map (the flow by hop). Both stay mounted, so each keeps
 * its zoom while the other is shown; only the shown one is active. */
function WalletMaps({ result, unit, onRoom }) {
  const phone = usePhone()
  const theme = useTheme()
  const [view, setView] = useState('bubble')
  const [selectedId, setSelectedId] = useState(null)
  const [flagsOnly, setFlagsOnly] = useState(false)
  const radios = useRef({})
  const byId = useMemo(() => new Map((result.graph?.nodes ?? []).flatMap((n) => [[n.id, n], [n.address, n]])), [result.graph])
  const { possible, confirmed } = useMemo(() => flagCounts(result.graph), [result.graph])
  // A map hands back the node it picked, or its id, or null to let go.
  const onSelect = useCallback((picked) => {
    const id = picked == null ? null : typeof picked === 'string' ? picked : picked.id ?? picked.address ?? null
    setSelectedId(id)
  }, [])
  const node = selectedId ? byId.get(selectedId) ?? null : null
  // The sheet keeps the wallet it showed while it slides away.
  const last = useRef(null)
  if (node) last.current = node
  const clear = () => {
    setSelectedId(null)
    radios.current[view]?.focus()
  }
  const showOther = () => setView((v) => (v === 'bubble' ? 'hop' : 'bubble'))
  const shared = { data: result.graph, tracePath: result.trace_path, unit, selected: node ? node.id : null, onSelect, flagsOnly, compact: phone }
  return (
    <div className={`ent-maps${phone ? ' phone' : ''}`}>
      <div className="ent-maps-bar">
        <MapSwitch view={view} onChange={setView} refs={radios} />
        <button type="button" className={`ent-switch${flagsOnly ? ' on' : ''}`} role="switch" aria-checked={flagsOnly} onClick={() => setFlagsOnly((v) => !v)}>
          <span className="ent-switch-track" aria-hidden="true"><span className="ent-switch-knob" /></span>
          Show only flags
        </button>
        <p className="ent-flag-note">
          <RoleSwatch role="flagged" color="var(--risk)" />
          <span>{`${possible} possible flag${possible === 1 ? '' : 's'}`}</span>
          <span aria-hidden="true">·</span>
          <RoleSwatch role="risk" color="var(--risk)" />
          <span>{`${confirmed} confirmed`}</span>
        </p>
      </div>
      <div className="ent-maps-body">
        <div className="ent-maps-stage">
          {/* The map not shown is set aside, not collapsed: it keeps its width
              (so its zoom and layout hold) and fades out under the one shown. */}
          <div className={`ent-mapwrap bubble${view === 'bubble' ? '' : ' off'}`} role="group" aria-label="Bubble map" inert={view !== 'bubble'}>
            <div className="stage"><GraphView {...shared} active={view === 'bubble'} /></div>
            {/* A compact bubble map leaves its key to the page; the hop map keeps its own. */}
            {phone && (
              <div className="flow-legend ent-bubble-key" aria-label="Bubble map key" role="group">
                {BUBBLE_KEY.map(([role, name]) => (
                  <span key={role}><RoleSwatch role={role} color={PALETTES[theme][role]} />{name}</span>
                ))}
              </div>
            )}
          </div>
          <div className={`ent-mapwrap hop${view === 'hop' ? '' : ' off'}`} role="group" aria-label="Hop map" inert={view !== 'hop'}>
            <FlowView {...shared} direction={result.direction} active={view === 'hop'} />
          </div>
        </div>
        {!phone && (
          <div className="ent-maps-side">
            {node
              ? <SelectedWallet key={node.id} node={node} result={result} unit={unit} view={view} onShowOther={showOther} onClear={clear} />
              : <p className="note ent-pick-empty">Select a wallet on either map to see it here. The selection is shared by both maps.</p>}
          </div>
        )}
      </div>
      {phone && <SelectedWallet phone open={Boolean(node)} node={node ?? last.current} result={result} unit={unit} view={view} onShowOther={showOther} onClear={clear} onRoom={onRoom} />}
      <p className="visually-hidden" aria-live="polite">{node
        ? `Selected ${middle(node.address ?? node.id, 6, 4)} on both maps.${phone ? ' Its details are in the panel at the foot of the screen.' : ''}`
        : ''}</p>
    </div>
  )
}

/** The Entities view: who the wallets are, by the role each plays, then the
 * hints, inferred deposits, swaps, related cases and funders of the case. */
function EntitiesTab({ result, unit, correlation }) {
  const headId = useId()
  const reverse = result.direction === 'incoming'
  const { groups, links } = useMemo(() => entityGroups(result), [result])
  const at = useMemo(() => groupLayout(groups, { reverse }), [groups, reverse])
  const [view, setView] = useState('grouped')
  // Room at the page's end for a phone's open wallet sheet.
  const [room, setRoom] = useState(0)
  const [chosen, setChosen] = useState(() => (groups.find((g) => g.key === 'split') ?? groups.find((g) => g.key === 'exchange') ?? groups[0])?.key)
  const group = groups.find((g) => g.key === chosen)
  const inferred = result.inferred_deposits ?? []
  const findings = result.findings ?? []
  const swaps = result.swaps ?? []
  const followOns = (result.follow_ons ?? []).filter((f) => f.result)
  const related = correlation?.related_cases ?? []
  const funders = result.direct_senders ?? []
  return (
    <>
      <div className={`ent-layout${view === 'every' ? ' every' : ''}`}>
        <section className="card ent-groups" aria-labelledby={headId}>
          <div className="ent-head">
            <h2 id={headId}>{count(result.graph.nodes.length, 'wallet')} in {count(groups.length, 'group')}</h2>
            <span className="ent-toggle">
              <button type="button" aria-pressed={view === 'grouped'} onClick={() => setView('grouped')}>Grouped</button>
              <button type="button" aria-pressed={view === 'every'} onClick={() => setView('every')}>Every wallet</button>
            </span>
          </div>
          {view === 'grouped'
            ? <GroupMap groups={groups} links={links} at={at} chosen={chosen} onChoose={setChosen} labelledBy={headId} />
            : <WalletMaps result={result} unit={unit} onRoom={setRoom} />}
        </section>
        <div className="ent-side">
          {group && <GroupCard key={group.key} group={group} groups={groups} links={links} result={result} unit={unit} />}
          <OtherComplaints caseId={result.case_id} correlation={correlation} groups={groups} own={result.address} chain={result.chain} />
        </div>
      </div>

      {inferred.length > 0 && (
        <details className="card sec" open={Boolean(result.attribution_inferred)}>
          <summary><span className="micro">Inferred deposit addresses · {inferred.length}</span><span className="pill amber">inference</span></summary>
          <div className="body">
            {inferred.map((m) => {
              const e = m.evidence ?? {}
              return (
                <div className="rule-block" key={m.address}>
                  <div className="top"><span className="nm amber">Probable {m.exchange} deposit address</span><span className="st">{m.depth} hop{m.depth === 1 ? '' : 's'}</span></div>
                  <Address value={m.address} head={12} tail={10} />
                  <div className="thresholds">
                    <span className="tk">outgoing transfers</span><span className="tv">{e.sweep_count}{e.outgoing_history_capped ? ' (newest only)' : ''}</span>
                    <span className="tk">all to</span><span className="tv">{e.sweep_destination_label}</span>
                    <span className="tk">total swept</span><span className="tv">{num(e.total_swept_native ?? 0)} {unit}</span>
                    {e.current_balance_native != null && <><span className="tk">current balance</span><span className="tv">{num(e.current_balance_native)} {e.current_balance_symbol ?? result?.chain_native_symbol ?? unit}</span></>}
                    {e.first_sweep && <><span className="tk">sweeps between</span><span className="tv">{when(e.first_sweep).slice(0, 10)} – {when(e.last_sweep).slice(0, 10)}</span></>}
                  </div>
                </div>
              )
            })}
          </div>
        </details>
      )}

      {findings.length > 0 ? (
        <details className="card sec">
          <summary><span className="micro">Hints · {findings.length}</span><span className="pill amber">a shape, not evidence</span></summary>
          <div className="body">
            {findings.map((f) => (
              <div className="rule-block" key={f.pattern}>
                <div className="top"><span className="nm amber">{PATTERN_NAME[f.pattern] ?? f.pattern}</span></div>
                <div className="desc">{f.description}</div>
                {validationLine(f.pattern) && <p className="hint-rate">{validationLine(f.pattern)}</p>}
                {f.evidence?.thresholds_applied && (
                  <div className="thresholds">
                    {Object.entries(f.evidence.thresholds_applied).map(([k, v]) => (
                      <span key={k} style={{ display: 'contents' }}><span className="tk">{k}</span><span className="tv">{String(v)}</span></span>
                    ))}
                  </div>
                )}
              </div>
            ))}
            <p className="note">A hint is a reason to look closer, not a finding: it never moves the score and should not appear in a request as evidence.</p>
          </div>
        </details>
      ) : (
        <div className="card sec flat"><span className="micro">Hints · none</span><span className="note">no peel chain or amount split</span></div>
      )}

      {swaps.length > 0 && (
        <details className="card sec" open={!result.exchange}>
          <summary><span className="micro">Swaps · {swaps.length}</span><span className="note">the trace changes asset here</span></summary>
          <div className="body">
            {swaps.map((s) => (
              <div className="swap" key={s.tx}>
                <Address value={s.sender} head={8} tail={6} /> sent <span className="num">{num(s.amount_in)} {s.asset_in}</span> to <strong>{s.router_label}</strong>
                {s.output_read
                  ? s.amount_out != null
                    ? <> and got <span className="num">{num(s.amount_out)} {s.asset_out}</span> back. {followOns.some((f) => f.address === s.sender && f.asset === s.asset_out)
                      ? <>The {s.asset_out} is followed from here — see <em>Continued in {s.asset_out}</em>.</>
                      : <>Re-run on {s.asset_out} from the sender to follow it further.</>}</>
                    : <> and got <span className="num">{s.amount_out_units}</span> raw units of an unlisted token{s.asset_out_contract ? <> (<Address value={s.asset_out_contract} head={8} tail={6} />)</> : null} back. Its decimals are not known, so the amount is not converted, and Exchequer does not trace that token — the trail stops here.</>
                  : <>. Nothing came back to the sender in the receipt — a swap into the native coin looks like this — so the output is unread, not guessed.</>}
                <div className="grid">
                  <span className="k">tx</span><Address value={s.tx} head={12} tail={10} />
                </div>
              </div>
            ))}
          </div>
        </details>
      )}

      {related.length > 0 ? (
        <details className="card sec" open>
          <summary><span className="micro">Related cases · {related.length}</span><span className="note">same wallets, other complaints</span></summary>
          <div className="body">
            {related.slice(0, 8).map((c) => (
              <div className="related-case" key={c.case_id ?? c.ref}>
                <div className="top">
                  {c.hidden
                    ? <span className="mono" title="Traced by someone else; only the wallets it shares with this case are shown">{c.ref}</span>
                    : <a href={`/case/${c.case_id}`} className="mono" title={c.reported_address}>{middle(c.reported_address, 10, 8)}</a>}
                  <span className="st">{c.shared_count} shared wallet{c.shared_count === 1 ? '' : 's'}</span>
                </div>
                <div className="ent">{c.exchange ? `reached ${c.exchange}` : 'no exchange matched'}{c.traced_at ? ` · traced ${String(c.traced_at).slice(0, 10)}` : ''}</div>
                {c.shared.slice(0, 3).map((s) => (
                  <div className="row" key={s.address}>
                    <Address value={s.address} head={10} tail={8} />
                    <span className="via">{s.inferred_exchange ? `probable ${s.inferred_exchange} deposit · ` : ''}{s.risk_category ? `${RISK_NAME[s.risk_category] ?? s.risk_category} · ` : ''}{s.value_in_native == null ? (s.after_swap_to ? `after a swap to ${s.after_swap_to}` : c.asset) : `${num(s.value_in_native)} ${s.after_swap_to ?? c.asset}${s.after_swap_to ? ' after a swap' : ''}`}</span>
                  </div>
                ))}
                {c.shared_count > 3 && <div className="ent">…and {c.shared_count - 3} more</div>}
              </div>
            ))}
            {related.length > 8 && <p className="note">…and {related.length - 8} more related cases.</p>}
            <p className="note">Only wallets no list names count — unlabelled, probable deposit addresses, or flagged but unnamed (a Tether freeze, a warning tag). A shared exchange is a shared bank, not a shared offender.</p>
          </div>
        </details>
      ) : (
        <div className="card sec flat"><span className="micro">Related cases · none</span><span className="note">no other stored complaint shares a wallet</span></div>
      )}

      {reverse && funders.length > 0 && (
        <details className="card sec" open>
          <summary><span className="micro">Funded this address · {funders.length}</span><span className="note">{funders.filter((f) => f.exchange).length} are exchange withdrawals</span></summary>
          <div className="body">
            {funders.map((f) => (
              <div className="funder" key={f.address}>
                <Address value={f.address} head={12} tail={10} />
                <span className="amt">{num(f.value_native)} {unit}</span>
                <span className="sub">
                  {f.tx_count} transfer{f.tx_count === 1 ? '' : 's'}{f.last_seen ? ` · ${when(f.last_seen)}` : ''}
                  {f.exchange && <span className="pill green">{f.exchange} withdrawal, not a victim</span>}
                  {f.risk_category && <span className="pill red">{RISK_NAME[f.risk_category] ?? f.risk_category}</span>}
                </span>
              </div>
            ))}
            <p className="note">Candidate victims where the reported address is an offender's — but a sender may equally be the offender's own wallet; the exchanges are marked.</p>
          </div>
        </details>
      )}
      {view === 'every' && room > 0 && <div className="ent-sheet-room" aria-hidden="true" style={{ height: room }} />}
    </>
  )
}

// Skips a render while its props are the same (see TimelineTab).
export default memo(EntitiesTab)
