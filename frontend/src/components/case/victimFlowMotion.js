// The Flow tab's motion (VictimFlow.jsx), worked out without drawing it:
// where the few slow lights travel on the Sankey, and the in-between frames
// of a figure that counts up once. The figures themselves never change: the
// page's text is always the final number, and these only draw over it.

/** The 60 ms stagger of the motion system, capped at 8 steps. */
export const stagger = (i, base = 0, step = 60) => base + Math.min(Math.max(0, i), 7) * step

const NUM = /\d[\d,]*(?:\.(\d+))?/

/** A figure's frames as it counts up from zero: a function from progress
 * (0 to 1) to the text, with the final text's decimals, grouping and words
 * around it; at 1 it is the final text. Null when there is nothing to count:
 * no number, zero, or words in the number ("under 0.1%"). */
export function countFrames(text) {
  const m = NUM.exec(text ?? '')
  if (!m || /[a-z]/i.test(text)) return null
  const to = Number(m[0].replace(/,/g, ''))
  if (!(to > 0)) return null
  const places = m[1]?.length ?? 0
  const nf = new Intl.NumberFormat('en-US', { minimumFractionDigits: places, maximumFractionDigits: places })
  const [before, after] = [text.slice(0, m.index), text.slice(m.index + m[0].length)]
  return (p) => (p >= 1 ? text : `${before}${nf.format(to * Math.max(0, p))}${after}`)
}

const round = (v, places) => Number(v.toFixed(places))

/** The routes the lights travel, from the layout's ribbons: each pair (the
 * reported wallet to a hop-1 row, that row to a bucket) is one route through
 * three points, x as a part of the width (%) and y in the box's own units
 * (px: the stage is as tall as the layout). Each light follows the middle of
 * its ribbons exactly: a ribbon edge is the curve of the CSS timing function
 * cubic-bezier(0.5, 0, 0.5, 1), so y eased by that while x runs straight
 * traces it. Up to three lights on the money that reached an exchange (the
 * only green ones), one on each of the two widest other routes; never more
 * than `max`, spread evenly over one `period` (s) after `start` (s). */
export function particleRoutes(lay, { max = 5, start = 2.2, period = 4.8 } = {}) {
  if (!lay?.ribbons?.length) return []
  const pct = (x) => round((x / lay.width) * 100, 3)
  const mid = (a, b) => round((a + b) / 2, 2)
  const routes = []
  for (let j = 0; j + 1 < lay.ribbons.length; j += 2) {
    const [a, b] = [lay.ribbons[j], lay.ribbons[j + 1]]
    if (a.to !== b.from || !(a.amount > 0)) continue
    routes.push({
      kind: b.kind, go: b.colour === 'go', amount: a.amount, thick: a.sy1 - a.sy0,
      x: [pct(a.x0), pct(a.x1), pct(b.x1)], y: [mid(a.sy0, a.sy1), mid(a.ty0, a.ty1), mid(b.ty0, b.ty1)],
    })
  }
  const wide = (p, q) => q.amount - p.amount
  const go = routes.filter((r) => r.go).sort(wide)
  // A hairline route carries no light: it would be a dot on nothing.
  const rest = routes.filter((r) => !r.go && r.thick >= 2).sort(wide)
  const picks = [...(go.length ? Array.from({ length: Math.min(3, max) }, (_, i) => go[i % go.length]) : []), ...rest.slice(0, 2)].slice(0, max)
  return picks.map((r, i) => ({ key: `${r.kind}-${i}`, kind: r.kind, colour: r.go ? 'go' : 'grey', x: r.x, y: r.y, delay: round(start + (i * period) / picks.length, 3) }))
}
