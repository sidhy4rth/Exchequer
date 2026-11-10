import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { RIM } from './components/GlobeBackground'
import { PALETTES } from './components/GraphView'

// The Glass colour tokens (styles.css). Colour has one job each: green is
// money at an exchange, the main actions and passed checks; red is risk and
// the blanks an officer must fill; white and greys are text, panels and
// unlabelled wallets. Amber and purple are retired: an inference or a pattern
// is drawn dashed or faded instead.

// Read from disk: vitest hands a stylesheet imported with ?raw back empty.
const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const css = read('./styles.css')
const traceForm = read('./components/TraceForm.css')

/** The custom properties declared in the block that starts with `selector {`. */
function block(selector, text = css) {
  const start = text.indexOf(`${selector} {`)
  if (start < 0) return {}
  const body = text.slice(text.indexOf('{', start) + 1, text.indexOf('}', start)).replace(/\/\*[\s\S]*?\*\//g, '')
  return Object.fromEntries(body.split(';').map((d) => d.split(/:(.*)/s).map((s) => s?.trim())).filter(([k]) => k?.startsWith('--')))
}
/** `text` matched literally inside a RegExp: every special character escaped, the backslash too. */
const literal = (text) => text.replace(/[\\^$.*+?()[\]{}|/]/g, '\\$&')
const ALIAS_BLOCK = ':root, .gate'
const aliases = block(ALIAS_BLOCK)
const THEMES = {
  light: { ...aliases, ...block(':root') },
  dark: { ...aliases, ...block(':root'), ...block('html[data-theme="dark"], .gate') },
}
/** `name` in a theme, or inside an element that declares `scope`. A custom
 * property is resolved where it is declared and inherited as that value: a
 * name the scope does not declare keeps the value it has on the root. */
function value(theme, name, scope = {}) {
  const v = scope[name] ?? THEMES[theme][name]
  const ref = /^var\((--[\w-]+)\)$/.exec(v ?? '')?.[1]
  if (!ref) return v
  return name in scope ? value(theme, ref, scope) : value(theme, ref)
}

/** [r, g, b, a] from #rgb, #rrggbb or rgba(). */
function rgba(text) {
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text ?? '')?.[1]
  if (hex) return [...(hex.length === 3 ? hex.split('').map((c) => c + c) : hex.match(/../g)).map((h) => parseInt(h, 16)), 1]
  const m = /^rgba?\(([^)]*)\)$/.exec(text ?? '')
  if (!m) throw new Error(`not a colour: ${text}`)
  const [r, g, b, a = 1] = m[1].split(',').map(Number)
  return [r, g, b, a]
}
const over = ([r, g, b, a], [R, G, B]) => [r * a + R * (1 - a), g * a + G * (1 - a), b * a + B * (1 - a), 1]
const lum = (c) => c.slice(0, 3).map((v) => v / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0)
const ratio = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05)
/** CSS saturate(s): the colour matrix a backdrop-filter applies. */
const saturate = ([r, g, b, a], s) => [
  (0.213 + 0.787 * s) * r + (0.715 - 0.715 * s) * g + (0.072 - 0.072 * s) * b,
  (0.213 - 0.213 * s) * r + (0.715 + 0.285 * s) * g + (0.072 - 0.072 * s) * b,
  (0.213 - 0.213 * s) * r + (0.715 - 0.715 * s) * g + (0.072 + 0.928 * s) * b,
  a,
].map((v, i) => (i < 3 ? Math.min(255, Math.max(0, v)) : v))

const SEMANTIC = ['--ground', '--panel', '--panel-2', '--line', '--line-strong', '--text', '--text-2', '--text-3',
  '--go', '--go-soft', '--go-tint', '--risk', '--risk-soft', '--risk-tint', '--glass', '--glass-line', '--glass-input', '--glass-overlay']
const OLD = {
  '--paper': '--ground', '--ink': '--text', '--muted': '--text-2', '--faint': '--text-3', '--rule': '--line',
  '--rule-strong': '--line-strong', '--glass-rule': '--glass-line', '--overlay': '--glass-overlay',
  '--green': '--go', '--green-soft': '--go-tint', '--red': '--risk', '--red-soft': '--risk-tint',
  '--navy': '--text', '--navy-hover': '--text', '--on-navy': '--ground', '--navy-soft': '--panel-2',
  '--amber': '--text-2', '--amber-soft': '--panel-2', '--purple': '--text-2',
}

describe.each(['dark', 'light'])('the %s theme', (theme) => {
  const colour = (name) => rgba(value(theme, name))
  const ground = () => colour('--ground')
  // Every surface text sits on, made solid: the ground and the panels, and
  // the green and red tints laid over each of those.
  const surface = (name) => over(colour(name), ground())
  const BASES = ['--ground', '--panel', '--panel-2']

  it.each(SEMANTIC)('defines %s', (name) => expect(() => colour(name)).not.toThrow())

  it('keeps every old token name working as an alias of a new one', () => {
    for (const [old, now] of Object.entries(OLD)) expect(`${old}: ${aliases[old]}`).toBe(`${old}: var(${now})`)
  })

  // Faint text (--text-3) never sits on a tint: at the pack's own values it
  // cannot keep 4.5:1 over a raised panel, so the transfer feed lifts the
  // faint text on its tinted rows to --text-2 (styles.css, .feed .row.on-path).
  const PAIRS = [
    ...BASES.flatMap((bg) => ['--text', '--text-2', '--text-3', '--go', '--risk'].map((fg) => [fg, bg, '--ground', 4.5])),
    ...BASES.flatMap((base) => ['--text', '--text-2', '--go', '--go-soft', '--risk'].map((fg) => [fg, '--go-tint', base, 4.5])),
    ...BASES.flatMap((base) => ['--text', '--text-2', '--go', '--risk', '--risk-soft'].map((fg) => [fg, '--risk-tint', base, 4.5])),
    // UI components: a field's edge, the focus ring and the main action's edge.
    ...BASES.flatMap((bg) => ['--line-strong', '--go', '--risk'].map((fg) => [fg, bg, '--ground', 3])),
  ]
  it.each(PAIRS)('%s on %s over %s passes %s:1', (fg, bg, base, min) => {
    const back = over(colour(bg), surface(base))
    const fore = over(colour(fg), back)
    expect(ratio(fore, back)).toBeGreaterThanOrEqual(min)
  })

  it("keeps a draft letter's sheet paper-white, its text and its red blanks at 4.5:1", () => {
    expect(value(theme, '--sheet')).toBe(value('light', '--panel'))
    for (const fg of ['--sheet-text', '--sheet-text-2']) expect(ratio(colour(fg), colour('--sheet'))).toBeGreaterThanOrEqual(4.5)
    expect(ratio(colour('--sheet-blank-text'), over(colour('--sheet-blank'), colour('--sheet')))).toBeGreaterThanOrEqual(4.5)
  })

  it('shows selected text on every surface, and keeps it readable', () => {
    expect(css).toMatch(/\n::selection \{ background: var\(--select\); \}/)
    for (const base of BASES) {
      const back = surface(base)
      const picked = over(colour('--select'), back)
      expect(ratio(picked, back)).toBeGreaterThanOrEqual(1.4)
      expect(ratio(colour('--text'), picked)).toBeGreaterThanOrEqual(4.5)
    }
  })

  // The console (Home) shows the globe through its glass, blurred and
  // saturated (--glass-blur). The globe's red rim is the brightest glow behind
  // its cards. Taken at its peak and unblurred, it is brighter than any
  // screenshot of the console shows, so what passes over it passes wherever
  // the globe has turned. A flat ground alone hid the trace form's field
  // edges falling to 2.75:1 over the rim.
  const saturation = Number(/saturate\((\d+)%\)/.exec(value(theme, '--glass-blur'))[1]) / 100
  const under = {
    'the bare ground': ground(),
    "the globe's brightest glow": saturate(over([...RIM[theme], RIM.alpha], ground()), saturation),
  }
  const glass = (what) => over(colour('--glass'), under[what])

  it.each(Object.keys(under).flatMap((what) => ['--text', '--text-2', '--text-3', '--go', '--risk'].map((fg) => [fg, what])))(
    "%s on the console's glass over %s passes 4.5:1", (fg, what) => {
      expect(ratio(colour(fg), glass(what))).toBeGreaterThanOrEqual(4.5)
    })

  // A field's edge stands 3:1 against its own fill and against the glass
  // around it: the new trace form's fields and the console's plain fields.
  it.each(Object.keys(under))("edges the console's fields at 3:1 against their fill and the glass, over %s", (what) => {
    const field = /\n\.trace-card \.fld \{([^}]*)\}/.exec(traceForm)[1]
    const tileEdge = /border: 1px solid var\((--[\w-]+)\)/.exec(field)[1]
    const tileFill = /background: var\((--[\w-]+)\)/.exec(field)[1]
    const plainEdge = /\ninput, select \{[^}]*border: 1px solid var\((--[\w-]+)\)/.exec(css)[1]
    const back = glass(what)
    const fields = [
      ['a trace form field', tileEdge, value(theme, tileFill)],
      ['a plain field', plainEdge, value(theme, '--glass-input')],
    ]
    for (const [field, name, fill] of fields) {
      const edge = rgba(value(theme, name, block('.home.console')))
      const inside = over(rgba(fill), back)
      expect(ratio(over(edge, inside), inside), `${field}: edge on its fill`).toBeGreaterThanOrEqual(3)
      expect(ratio(over(edge, back), back), `${field}: edge on the glass`).toBeGreaterThanOrEqual(3)
    }
  })

  it('the graph canvas paints with the same colours (GraphView PALETTES)', () => {
    const p = PALETTES[theme]
    const pinned = { seed: '--text', text: '--text', dim: '--text-2', risk: '--risk', exchange: '--go', inferred: '--go-soft', gambling: '--text-2', flagged: '--text-2', background: '--panel' }
    for (const [key, name] of Object.entries(pinned)) expect(`${key}: ${p[key].toLowerCase()}`).toBe(`${key}: ${value(theme, name).toLowerCase()}`)
  })
})

it('matches a selector literally, whatever characters it holds', () => {
  const odd = String.raw`a\b.c*d+e?f^g$h{i}j(k)l|m[n]o/p`
  expect(new RegExp(`^${literal(odd)}$`).test(odd)).toBe(true)
  expect(new RegExp(literal('.pill')).test('xpill')).toBe(false)
})

describe('amber, purple and the old warm palette are retired', () => {
  const sources = Object.keys(import.meta.glob(['./**/*.{js,jsx,css}', '!./**/*.test.{js,jsx}'])).map((path) => [path, read(path)])
  const withoutAliases = (text) => text.replace(new RegExp(`${literal(ALIAS_BLOCK)} \\{[^}]*\\}`), '')

  it.each(sources)('%s uses no amber or purple', (_, text) => {
    expect(withoutAliases(text)).not.toMatch(/var\(--(amber|purple)/)
    expect(text).not.toMatch(/#(e0a44a|9a5b00|c98a1e|b45309|b388ff|6b3fa0)\b/i)
  })

  it.each(sources)('%s keeps none of the old warm ink and paper', (_, text) => {
    expect(text).not.toMatch(/\b(22, ?25, ?29|236, ?236, ?234|240, ?238, ?233)\b/)
    expect(text).not.toMatch(/#(16191d|ececea|111316|07090c|f3f1ea)\b/i)
  })

  it.each(['.pill.amber', '.flow .flow-link.flagged', '.graph-tooltip .tags span', '.why-list .confirm'])('%s is drawn dashed', (selector) => {
    const rule = new RegExp(`${literal(selector)} \\{([^}]*)\\}`).exec(css)?.[1]
    expect(rule).toMatch(/dashed|stroke-dasharray/)
  })
})

describe('the Glass shape', () => {
  it('rounds panels large and pills and buttons fully', () => {
    expect(parseFloat(THEMES.light['--r-panel'])).toBeGreaterThanOrEqual(16)
    expect(parseFloat(THEMES.light['--r-panel'])).toBeLessThanOrEqual(20)
    expect(THEMES.light['--r-pill']).toBe('999px')
    for (const selector of ['button', '.pill']) expect(new RegExp(`\\n${literal(selector)} \\{[^}]*border-radius: var\\(--r-pill\\)`).test(css)).toBe(true)
    expect(/\n\.card \{[^}]*border-radius: var\(--r-panel\)/.test(css)).toBe(true)
  })
})

describe('the traced funds', () => {
  it('are drawn green, never red: red is for risk', () => {
    const rules = [...css.matchAll(/([^{}]*on-path[^{}]*)\{([^}]*)\}/g)]
    expect(rules.length).toBeGreaterThan(5)
    for (const [, selector, body] of rules) expect(`${selector.trim()} {${body}}`).not.toMatch(/--(red|risk)\b/)
    expect(/@keyframes feedpulse \{[^@]*?\n\}/.exec(css)[0]).not.toMatch(/--(red|risk)\b/)
  })
})

describe('keyboard focus', () => {
  it('rings an element without changing its shape', () => {
    const rule = /\n:focus-visible \{([^}]*)\}/.exec(css)[1]
    expect(rule).toMatch(/outline: 2px solid var\(--go\)/)
    expect(rule).not.toMatch(/border-radius/)
  })
})
