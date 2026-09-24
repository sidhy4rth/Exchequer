import { useEffect, useMemo, useRef, useState } from 'react'
import { geoEquirectangular, geoPath } from 'd3-geo'
import { feature } from 'topojson-client'
import land110 from 'world-atlas/land-110m.json'
import globeData from '../data/exchange_globe.json'
import { fetchHealth } from '../api'

// The sign-in scene: a see-through globe with every exchange CoinGecko lists
// against a country, placed there. It turns slowly on its axis; a drag
// takes it by hand and it coasts back to its turn; hovering an exchange shows
// its name, founding year and home country. The chequer mark lives in the
// logo, drawn in 3D on this canvas; clicking it (or the globe) opens the
// door: the mark pops out of the logo, swoops into the core of the globe,
// the globe implodes into it, flashes, and bursts outward behind the card.

const RAD = Math.PI / 180
const OPEN_MS = 1900
// Idle spin in degrees of longitude per 60 Hz frame: one turn in about 80 s.
// Scaled by real frame time, so a 120 Hz screen turns it no faster.
const CRUISE = -0.075
const CLOSE_MS = 1300
// The door's timeline, as fractions of it. One motion to the halfway mark:
// the mark flies from the logo to the core while the globe shrinks into it,
// on the same curve, so they meet as it arrives. Then the flash and burst.
const IMPLODE = 0.5
const C = {
  red: '#ff5c5c',
}

// Exchanges are coloured by when they were founded. Three eras, because a
// dot map puts every colour next to every other and three is as many as stay
// apart for colour-blind readers too (validated against the dark surface:
// worst pair ΔE 9.4 deutan, 20.9 normal).
export const ERAS = [
  { key: 'early', label: '2011–2017', note: 'Early exchanges', color: '#d95926', rgb: '217, 89, 38', test: (y) => y <= 2017 },
  { key: 'boom', label: '2018–2021', note: 'ICO and DeFi boom', color: '#3987e5', rgb: '57, 135, 229', test: (y) => y >= 2018 && y <= 2021 },
  { key: 'recent', label: '2022–now', note: 'Recent', color: '#199e70', rgb: '25, 158, 112', test: (y) => y >= 2022 },
]
const CHAIN_NAMES = { ethereum: 'Ethereum', bsc: 'BNB Chain', polygon: 'Polygon', arbitrum: 'Arbitrum', tron: 'Tron' }
const eraOf = (year) => ERAS.findIndex((e) => e.test(year ?? 0))

/** Land as evenly spaced dots, found by rasterising the land polygons once. */
function landDots() {
  const W = 720, H = 360
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  const projection = geoEquirectangular().fitSize([W, H], { type: 'Sphere' })
  ctx.fillStyle = '#000'
  ctx.beginPath()
  geoPath(projection, ctx)(feature(land110, land110.objects.land))
  ctx.fill()
  const pixels = ctx.getImageData(0, 0, W, H).data
  const land = [], sea = []
  const step = 1.3
  let row = 0
  for (let lat = -84; lat <= 84; lat += step, row += 1) {
    const lonStep = step / Math.max(0.12, Math.cos(lat * RAD))
    let col = 0
    for (let lon = -180; lon < 180; lon += lonStep, col += 1) {
      const [x, y] = projection([lon, lat])
      const onLand = pixels[(Math.floor(y) * W + Math.floor(x)) * 4 + 3] > 128
      if (onLand) land.push(prep(lat, lon))
      // A sparse lattice over the sea keeps the sphere reading as a sphere.
      else if (row % 3 === 0 && col % 3 === 0) sea.push(prep(lat, lon))
    }
  }
  return { land, sea }
}

/** The glow of a lit exchange, drawn once per colour and stamped: a round
 * bloom in the era's colour, strongest at the centre. No sparkle. */
function bloomSprite(rgb) {
  const S = 64, c = S / 2
  const canvas = document.createElement('canvas')
  canvas.width = S
  canvas.height = S
  const ctx = canvas.getContext('2d')
  const halo = ctx.createRadialGradient(c, c, 0, c, c, c)
  halo.addColorStop(0, `rgba(${rgb}, 0.95)`)
  halo.addColorStop(0.18, `rgba(${rgb}, 0.6)`)
  halo.addColorStop(0.45, `rgba(${rgb}, 0.18)`)
  halo.addColorStop(1, `rgba(${rgb}, 0)`)
  ctx.fillStyle = halo
  ctx.fillRect(0, 0, S, S)
  return canvas
}

function prep(lat, lon) {
  return { lat, lon, sl: Math.sin(lat * RAD), cl: Math.cos(lat * RAD), lr: lon * RAD }
}

const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

/** How the globe looks at door progress k (0 shut, 1 open): implode to the
 * core, flash, then burst out wide and dim behind the card. */
function doorShape(k) {
  if (k <= 0) return { scale: 1, alpha: 1, flash: 0 }
  if (k < IMPLODE) {
    const t = ease(k / IMPLODE)
    return { scale: 1 - 0.94 * t, alpha: 1, flash: 0 }
  }
  const t = ease((k - IMPLODE) / (1 - IMPLODE))
  return { scale: 0.06 + 1.74 * t, alpha: 1 - 0.8 * t, flash: Math.max(0, 1 - (k - IMPLODE) / 0.2) }
}


// The glow of the globe takes the colour of the door: red for investigators,
// green for citizens, matching the access label under the globe.
const ACCENTS = { investigator: [255, 92, 92], citizen: [47, 211, 162] }

export default function ExchangeGlobe({ open, onOpen, hint, anchorRef, role = 'investigator' }) {
  const wrapRef = useRef(null)
  const canvasRef = useRef(null)
  const [tip, setTip] = useState(null)
  const liveRef = useRef({ open: false, doorAt: 0 })

  useEffect(() => { liveRef.current.onOpen = onOpen }, [onOpen])
  useEffect(() => { liveRef.current.accent = ACCENTS[role] ?? ACCENTS.investigator }, [role])

  const countries = useMemo(() => new Set(globeData.points.map((p) => p.country)).size, [])
  const eraCounts = useMemo(() => ERAS.map((_, i) => globeData.points.filter((p) => eraOf(p.year) === i).length), [])
  const [focusEra, setFocusEra] = useState(null)
  useEffect(() => { liveRef.current.focusEra = focusEra }, [focusEra])
  const [focusCountry, setFocusCountry] = useState(null)
  useEffect(() => { liveRef.current.focusCountry = focusCountry }, [focusCountry])

  // Where exchanges register: countries by count, the rest folded together.
  const jurisdictions = useMemo(() => {
    const by = new Map()
    for (const p of globeData.points) {
      const row = by.get(p.country) ?? { country: p.country, n: 0, lat: p.lat, lon: p.lon }
      row.n += 1
      by.set(p.country, row)
    }
    const rows = [...by.values()].sort((a, b) => b.n - a.n)
    const top = rows.slice(0, 7)
    return { top, other: rows.slice(7).reduce((s, r) => s + r.n, 0), otherCountries: rows.length - 7 }
  }, [])

  // What the tool itself can see, read live from the backend.
  const [coverage, setCoverage] = useState(null)
  useEffect(() => {
    let alive = true
    fetchHealth().then((h) => {
      if (!alive) return
      const chains = Object.values(h.chains ?? {})
      const sum = (f) => chains.reduce((s, c) => s + f(c), 0)
      setCoverage({
        exchange: sum((c) => c.exchange_labels ?? 0),
        sanctioned: sum((c) => c.risk_labels?.sanctioned ?? 0),
        frozen: sum((c) => c.risk_labels?.frozen ?? 0),
        stolen: sum((c) => c.risk_labels?.stolen ?? 0),
        mixer: sum((c) => c.risk_labels?.mixer ?? 0),
        chains: Object.keys(h.chains ?? {}),
      })
    }).catch(() => { if (alive) setCoverage(false) })
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (liveRef.current.open === open) return
    liveRef.current.open = open
    liveRef.current.doorAt = performance.now()
    if (open) setTip(null)
  }, [open])

  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    const ctx = canvas.getContext('2d')
    const { land, sea } = landDots()
    const exchanges = globeData.points.map((p, i) => ({
      ...prep(p.lat, p.lon), p, era: eraOf(p.year),
      // Each LED blinks on its own clock: every 3-9 s, out of step.
      period: 3000 + ((i * 7919) % 6000), offset: (i * 104729) % 9000,
    }))
    const blooms = ERAS.map((era) => bloomSprite(era.rgb))
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    let W = 0, H = 0, R = 0, cx = 0, cy = 0
    // Opens over India.
    const view = { lat: 18, lon: 78 }
    let drag = null
    let velocity = { lon: CRUISE, lat: 0 }
    let lastNow = 0
    // The glow colour eases toward the door's accent when the door changes.
    const glow = [...(liveRef.current.accent ?? ACCENTS[role] ?? ACCENTS.investigator)]
    let door = liveRef.current.open ? 1 : 0 // 0 shut .. 1 open
    let doorFrom = door
    let lastDoorAt = liveRef.current.doorAt
    let hoverCore = 0
    // Where the mark rests: the logo slot in the top bar.
    let anchor = { x: 40, y: 34, size: 24 }
    let brandHover = 0, brandTarget = 0, brandSpin = 0
    let trail = []
    let pointerIn = null
    let hovered = null
    let onScreen = []
    let raf = 0
    let spin = 0
    let g = 1 // globe scale from the door
    let shape = doorShape(door)

    function resize() {
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      W = wrap.clientWidth
      H = wrap.clientHeight
      canvas.width = W * dpr
      canvas.height = H * dpr
      canvas.style.width = `${W}px`
      canvas.style.height = `${H}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      R = Math.min(W * 0.42, H * 0.37)
      cx = W / 2
      cy = H * 0.49
      const slot = anchorRef?.current
      if (slot) {
        const a = slot.getBoundingClientRect(), c = canvas.getBoundingClientRect()
        anchor = { x: a.left - c.left + a.width / 2, y: a.top - c.top + a.height / 2, size: a.width }
      }
    }

    // Orthographic projection by hand: thousands of dots a frame is cheaper
    // than going through d3 for each.
    function project(q) {
      const dl = q.lr - (view.lon + spin) * RAD
      const sc = Math.sin(view.lat * RAD), cc = Math.cos(view.lat * RAD)
      const x = q.cl * Math.sin(dl)
      const y = cc * q.sl - sc * q.cl * Math.cos(dl)
      const z = sc * q.sl + cc * q.cl * Math.cos(dl)
      return { x: cx + R * g * x, y: cy - R * g * y, z }
    }

    function dots(list, back, size, color) {
      ctx.fillStyle = color
      const sg = Math.max(0.6, g)
      for (const d of list) {
        const p = project(d)
        if (back ? p.z > 0 : p.z <= 0) continue
        ctx.globalAlpha = (back ? 0.25 + 0.35 * (1 + p.z) : 0.3 + 0.7 * p.z) * shape.alpha
        const s = size * (back ? 0.7 : 0.6 + 0.4 * p.z) * sg
        ctx.fillRect(p.x - s / 2, p.y - s / 2, s, s)
      }
      ctx.globalAlpha = 1
    }

    // The chequer mark, as glass: the logo's squares as blocks, the red one
    // standing proud and lit from inside. Every face is drawn, far ones
    // first and faint, so the solid reads through itself. It swings gently
    // rather than spinning, so the board never turns edge-on.
    const CUBE_FACES = [
      { n: [0, 0, -1], v: [0, 1, 2, 3] }, { n: [0, 0, 1], v: [5, 4, 7, 6] },
      { n: [-1, 0, 0], v: [4, 0, 3, 7] }, { n: [1, 0, 0], v: [1, 5, 6, 2] },
      { n: [0, -1, 0], v: [4, 5, 1, 0] }, { n: [0, 1, 0], v: [3, 2, 6, 7] },
    ]
    const LIGHT = (() => { const l = [-0.45, -0.65, -0.62]; const m = Math.hypot(...l); return l.map((x) => x / m) })()
    const BLOCKS = []
    for (let i = 0; i < 4; i += 1) {
      for (let j = 0; j < 4; j += 1) {
        if ((i + j) % 2 === 0) BLOCKS.push({ i, j, red: i === 2 && j === 2, seed: (i * 5 + j * 3) % 7 })
      }
    }

    /** Where the mark is and how big, for the current door progress: at
     * rest in the logo, then swooping to the core and growing, on the same
     * curve and clock as the globe shrinking into it. */
    function markPlace() {
      const full = R * 0.115
      const rest = anchor.size / 4.4
      if (door <= 0) return { x: anchor.x, y: anchor.y, cell: rest, fly: 0 }
      const t = Math.min(1, door / IMPLODE)
      // Out of the logo fast, then a soft landing; the globe squeezes in on
      // a gentler curve, so the two close on each other and meet together.
      const e = 1 - Math.pow(1 - t, 3)
      // A swoop: down out of the corner, then across into the globe.
      const ctrl = { x: anchor.x + (cx - anchor.x) * 0.1, y: cy + (cy - anchor.y) * 0.15 }
      const u = 1 - e
      const x = u * u * anchor.x + 2 * u * e * ctrl.x + e * e * cx
      const y = u * u * anchor.y + 2 * u * e * ctrl.y + e * e * cy
      const cell = rest + (full * 1.3 - rest) * e
      return { x, y, cell, fly: t }
    }

    function mark(now) {
      const burst = door < IMPLODE ? 0 : ease(Math.min(1, (door - IMPLODE) / 0.35))
      const fade = 1 - burst
      if (fade <= 0.01) return
      const place = markPlace()
      const mx = place.x, my = place.y, cell = place.cell
      const atRest = door <= 0
      // One smooth full turn in flight lands it facing the way it left.
      const yaw = (reduce ? 0.35 : Math.sin(now / 3400) * 0.55) + ease(place.fly) * Math.PI * 2 + brandSpin
      const pitch = atRest
        ? 0.3 + (reduce ? 0 : Math.sin(now / 4700) * 0.1)
        : 0.22 - view.lat * RAD * 0.35 * place.fly + (reduce ? 0 : Math.sin(now / 4700) * 0.1)
      const cyw = Math.cos(yaw), syw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch)
      const rot = ([x, y, z]) => {
        const x1 = x * cyw + z * syw, z1 = -x * syw + z * cyw
        return [x1, y * cp - z1 * sp, y * sp + z1 * cp]
      }
      const F = cell * 26
      const screen = ([x, y, z]) => { const p = F / (F + z); return [mx + x * p, my + y * p] }

      const glowR = cell * (3.2 + brandHover * 0.8)
      const glow = ctx.createRadialGradient(mx, my + cell * 0.5, 0, mx, my + cell * 0.5, glowR)
      glow.addColorStop(0, `rgba(255, 92, 92, ${(0.2 + brandHover * 0.15) * fade})`)
      glow.addColorStop(1, 'rgba(255, 92, 92, 0)')
      ctx.fillStyle = glow
      ctx.beginPath(); ctx.arc(mx, my + cell * 0.5, glowR, 0, Math.PI * 2); ctx.fill()
      const thin = Math.max(0.35, Math.min(1, cell / 30)) // hairlines when small
      // Solid like the flat logo while it sits in the top bar; glass by the
      // time it enters the globe.
      const solid = 1 - ease(Math.min(1, place.fly / 0.8))

      const faces = []
      const h = cell / 2
      for (const b of BLOCKS) {
        let ux = (b.j - 1.5) * cell, uy = (b.i - 1.5) * cell, uz = b.red ? -cell * 0.3 : 0
        // On the burst each block flies out from the centre, tumbling.
        let tumble = 0
        if (burst > 0) {
          const dx = ux || 0.3 * cell, dy = uy || 0.3 * cell
          const k = burst * (3 + b.seed * 0.4)
          ux += dx * k; uy += dy * k; uz -= cell * burst * (2 + b.seed)
          tumble = burst * (2 + b.seed * 0.5)
        }
        const d = b.red ? cell * 0.8 : cell * 0.45
        const ct = Math.cos(tumble), st = Math.sin(tumble)
        const local = ([x, y, z]) => [x * ct - y * st, x * st + y * ct, z]
        const corners = [
          [-h, -h, -d], [h, -h, -d], [h, h, -d], [-h, h, -d],
          [-h, -h, d], [h, -h, d], [h, h, d], [-h, h, d],
        ].map((c) => { const [x, y, z] = local(c); return rot([x + ux, y + uy, z + uz]) })
        for (const f of CUBE_FACES) {
          const n = rot(local(f.n))
          const pts = f.v.map((k) => corners[k])
          const zc = pts.reduce((s, p) => s + p[2], 0) / 4
          const toEye = [-pts[0][0], -pts[0][1], -F - pts[0][2]]
          const front = n[0] * toEye[0] + n[1] * toEye[1] + n[2] * toEye[2] > 0
          const lit = Math.max(0, n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2])
          faces.push({ pts: pts.map(screen), zc, lit, front, red: b.red })
        }
      }
      faces.sort((a, b) => b.zc - a.zc)
      ctx.lineJoin = 'round'
      for (const f of faces) {
        ctx.beginPath()
        ctx.moveTo(...f.pts[0]); ctx.lineTo(...f.pts[1]); ctx.lineTo(...f.pts[2]); ctx.lineTo(...f.pts[3])
        ctx.closePath()
        if (f.red) {
          const k = f.front ? 0.55 + 0.45 * f.lit : 0.3
          ctx.fillStyle = `rgba(255, ${Math.round(70 + 60 * f.lit)}, ${Math.round(70 + 40 * f.lit)}, ${(f.front ? 0.55 + 0.35 * f.lit : 0.3) * fade})`
          ctx.shadowColor = C.red
          ctx.shadowBlur = f.front ? 18 * k * thin : 0
          ctx.fill()
          ctx.shadowBlur = 0
          ctx.strokeStyle = `rgba(255, 190, 190, ${(f.front ? 0.9 : 0.35) * fade})`
        } else {
          const a = (f.front ? 0.07 + 0.2 * f.lit : 0.035) + solid * (f.front ? 0.45 + 0.3 * f.lit : 0.1)
          ctx.fillStyle = `rgba(226, 238, 244, ${Math.min(1, a) * fade})`
          ctx.fill()
          ctx.strokeStyle = `rgba(214, 240, 236, ${(f.front ? 0.55 + 0.35 * f.lit : 0.14) * fade})`
        }
        ctx.lineWidth = (f.front ? 1.1 : 0.7) * thin
        ctx.stroke()
      }
    }

    function frame(now) {
      const live = liveRef.current
      // Door progress, eased from wherever it was when the door last moved.
      if (live.doorAt !== lastDoorAt) { lastDoorAt = live.doorAt; doorFrom = door }
      const t = Math.min(1, (now - live.doorAt) / (live.open ? OPEN_MS : CLOSE_MS))
      door = live.open ? doorFrom + (1 - doorFrom) * t : doorFrom * (1 - t)
      // Dev only: window.__door = 0..1 freezes the door to check a moment of it.
      if (import.meta.env.DEV && typeof window.__door === 'number') door = window.__door
      shape = doorShape(door)
      g = shape.scale
      // The globe spins up as it falls in and slows as it opens out.
      if (!reduce && door > 0 && door < 1) spin += 5 * Math.sin(Math.PI * door)
      brandHover += (brandTarget - brandHover) * 0.1
      if (!reduce && door <= 0) brandSpin += brandHover * 0.09

      const overGlobe = pointerIn && !live.open && Math.hypot(pointerIn.x - cx, pointerIn.y - cy) < R
      hoverCore += ((overGlobe ? 1 : 0) - hoverCore) * 0.12

      // The globe turns on its axis, west to east as the Earth does. A drag
      // takes over; on release it coasts and eases back to that cruise.
      // Hovering an exchange holds it still so the dot stays under the cursor.
      const step = Math.min(3, (now - (lastNow || now)) / (1000 / 60))
      lastNow = now
      const fc = live.focusCountry
      if (fc && !drag) {
        // A jurisdiction is hovered in the side panel: turn to face it.
        const dl = ((fc.lon - (view.lon + spin) + 540) % 360) - 180
        view.lon += dl * Math.min(1, 0.07 * step)
        view.lat += (Math.max(-40, Math.min(50, fc.lat * 0.85)) - view.lat) * Math.min(1, 0.07 * step)
        velocity = { lon: 0, lat: 0 }
      } else if (!drag) {
        const cruise = reduce ? 0 : CRUISE
        const flung = Math.abs(velocity.lon - cruise) > 0.05 || Math.abs(velocity.lat) > 0.05
        if (hovered && !flung) velocity = { lon: 0, lat: 0 }
        else {
          const decay = Math.pow(0.94, step)
          velocity.lon = cruise + (velocity.lon - cruise) * decay
          velocity.lat *= decay
          if (flung && hovered) { hovered = null; setTip(null) }
        }
        view.lon += velocity.lon * step
        view.lat = Math.max(-70, Math.min(70, view.lat + velocity.lat * step))
      }

      const want = live.accent ?? glow
      for (let k = 0; k < 3; k += 1) glow[k] += (want[k] - glow[k]) * Math.min(1, 0.08 * step)
      const tint = glow.map(Math.round).join(', ')

      ctx.clearRect(0, 0, W, H)
      const r = R * g

      // Atmosphere.
      const halo = ctx.createRadialGradient(cx, cy, r * 0.85, cx, cy, r * 1.35)
      halo.addColorStop(0, `rgba(${tint}, ${(0.1 + hoverCore * 0.05) * shape.alpha})`)
      halo.addColorStop(1, `rgba(${tint}, 0)`)
      ctx.fillStyle = halo
      ctx.beginPath(); ctx.arc(cx, cy, r * 1.35, 0, Math.PI * 2); ctx.fill()

      const dotSize = Math.max(1.3, R / 190)
      // Far side first, seen through the glass; then the core; then the near side.
      dots(sea, true, dotSize * 0.8, `rgba(${tint}, 0.3)`)
      dots(land, true, dotSize, `rgba(${tint}, 0.5)`)
      const body = ctx.createRadialGradient(cx - r * 0.4, cy - r * 0.45, r * 0.05, cx, cy, r)
      body.addColorStop(0, `rgba(255, 255, 255, ${0.05 * shape.alpha})`)
      body.addColorStop(0.7, 'rgba(255, 255, 255, 0)')
      body.addColorStop(1, `rgba(${tint}, ${0.13 * shape.alpha})`)
      ctx.fillStyle = body
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill()
      dots(sea, false, dotSize * 0.8, 'rgba(170, 184, 198, 0.4)')
      dots(land, false, dotSize, 'rgba(214, 222, 230, 0.9)')

      // Exchanges, as LEDs: a solid dot in the era's colour, and every few
      // seconds a hard blink -- on fast, held, off fast -- with a round bloom.
      onScreen = []
      const sg = Math.max(0.5, g)
      for (const e of exchanges) {
        const p = project(e)
        if (p.z <= 0) continue
        if (door < 0.05) onScreen.push({ x: p.x, y: p.y, p: e.p })
        const on = hovered === e.p
        const era = ERAS[e.era] ?? ERAS[0]
        // A legend hover lights one era and sinks the rest.
        const offEra = live.focusEra !== null && live.focusEra !== undefined && live.focusEra !== e.era
        const offCountry = live.focusCountry && live.focusCountry.country !== e.p.country
        const dim = offEra || offCountry ? 0.1 : 1
        const held = on || (live.focusCountry && !offCountry)
        let lit = held ? 1 : 0
        if (!reduce && !held) {
          const t = (now + e.offset) % e.period
          lit = t < 40 ? t / 40 : t < 420 ? 1 : t < 540 ? 1 - (t - 420) / 120 : 0
        }
        const facing = 0.45 + 0.55 * p.z
        const a = shape.alpha * dim
        if (lit > 0) {
          const size = 30 * sg * (0.6 + 0.4 * lit)
          ctx.globalCompositeOperation = 'lighter'
          ctx.globalAlpha = lit * facing * a
          ctx.drawImage(blooms[e.era] ?? blooms[0], p.x - size / 2, p.y - size / 2, size, size)
          ctx.globalCompositeOperation = 'source-over'
        }
        // The LED itself: unlit it is the era colour, dimmed; lit it swells a
        // little and burns white at the centre.
        ctx.globalAlpha = (0.55 + 0.45 * lit) * facing * a
        ctx.fillStyle = era.color
        ctx.beginPath(); ctx.arc(p.x, p.y, (2.2 + 1.2 * lit) * sg, 0, Math.PI * 2); ctx.fill()
        if (lit > 0) {
          ctx.globalAlpha = lit * a
          ctx.fillStyle = '#ffffff'
          ctx.beginPath(); ctx.arc(p.x, p.y, 1.3 * sg, 0, Math.PI * 2); ctx.fill()
        }
      }
      ctx.globalCompositeOperation = 'source-over'
      if (hovered) {
        const h = exchanges.find((e) => e.p === hovered)
        const p = h && project(h)
        if (p && p.z > 0) {
          ctx.globalAlpha = 0.9
          ctx.strokeStyle = '#ffffff'
          ctx.lineWidth = 1
          ctx.beginPath(); ctx.arc(p.x, p.y, 9, 0, Math.PI * 2); ctx.stroke()
        }
      }
      ctx.globalAlpha = 1

      // The flash when the globe collapses into the core.
      if (shape.flash > 0) {
        const fr = R * (0.2 + (1 - shape.flash) * 2.2)
        const fg = ctx.createRadialGradient(cx, cy, 0, cx, cy, fr)
        fg.addColorStop(0, `rgba(255, 255, 255, ${0.9 * shape.flash})`)
        fg.addColorStop(0.25, `rgba(255, 92, 92, ${0.5 * shape.flash})`)
        fg.addColorStop(1, 'rgba(255, 92, 92, 0)')
        ctx.fillStyle = fg
        ctx.beginPath(); ctx.arc(cx, cy, fr, 0, Math.PI * 2); ctx.fill()
        ctx.strokeStyle = `rgba(255, 255, 255, ${0.7 * shape.flash})`
        ctx.lineWidth = 2
        ctx.beginPath(); ctx.arc(cx, cy, R * (1 - shape.flash) * 1.8, 0, Math.PI * 2); ctx.stroke()
      }

      // In flight the mark leaves a fading trail behind it.
      if (door > 0 && door < IMPLODE) {
        const p = markPlace()
        trail.push({ x: p.x, y: p.y, r: p.cell * 0.6, at: now })
      }
      trail = trail.filter((q) => now - q.at < 380)
      for (const q of trail) {
        const f = 1 - (now - q.at) / 380
        const gr = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, q.r * 2)
        gr.addColorStop(0, `rgba(255, 120, 120, ${0.22 * f})`)
        gr.addColorStop(1, 'rgba(255, 92, 92, 0)')
        ctx.fillStyle = gr
        ctx.beginPath(); ctx.arc(q.x, q.y, q.r * 2, 0, Math.PI * 2); ctx.fill()
      }
      // The mark is drawn last, in front throughout, so it never changes
      // layer mid-flight; the globe collapses behind and into it.
      mark(now)
      if (door < 0.05) pick()

      raf = requestAnimationFrame(frame)
    }

    function local(event) {
      const rect = canvas.getBoundingClientRect()
      return { x: event.clientX - rect.left, y: event.clientY - rect.top }
    }

    function nearest(x, y, r) {
      let best = null, bd = r * r
      for (const o of onScreen) {
        const d = (o.x - x) ** 2 + (o.y - y) ** 2
        if (d < bd) { bd = d; best = o }
      }
      return best
    }

    function move(event) {
      const { x, y } = local(event)
      pointerIn = { x, y }
      if (liveRef.current.open) { canvas.style.cursor = 'default'; return }
      if (drag) {
        if (Math.hypot(x - drag.x, y - drag.y) > 5) drag.moved = true
        // Turn with the hand: a pixel of drag is a fixed arc of the globe.
        const k = 57 / R
        const lon = drag.lon - (x - drag.x) * k
        const lat = Math.max(-70, Math.min(70, drag.lat + (y - drag.y) * k))
        velocity = { lon: lon - view.lon, lat: lat - view.lat }
        view.lon = lon
        view.lat = lat
        canvas.style.cursor = 'grabbing'
        return
      }
      pick()
    }

    // Which star is under the pointer. Run on every move and every frame,
    // because the globe turns stars under a cursor that is standing still.
    function pick() {
      if (!pointerIn || drag || liveRef.current.open) return
      const hit = nearest(pointerIn.x, pointerIn.y, 10)
      const next = hit ? hit.p : null
      if (next !== hovered) {
        hovered = next
        setTip(hit ? { x: hit.x, y: hit.y, ...hit.p } : null)
      }
      canvas.style.cursor = hit ? 'pointer' : Math.hypot(pointerIn.x - cx, pointerIn.y - cy) < R ? 'grab' : 'default'
    }

    function down(event) {
      if (liveRef.current.open) return
      const { x, y } = local(event)
      velocity = { lon: 0, lat: 0 }
      drag = { x, y, lon: view.lon, lat: view.lat, moved: false }
      hovered = null
      setTip(null)
    }

    function up(event) {
      const d = drag
      drag = null
      if (!d || liveRef.current.open) return
      if (!d.moved) {
        velocity = { lon: 0, lat: 0 }
        const { x, y } = local(event)
        if (Math.hypot(x - cx, y - cy) < R) liveRef.current.onOpen?.()
      }
    }

    function leave() {
      pointerIn = null
      hovered = null
      setTip(null)
    }

    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(wrap)
    // The logo slot moves when web fonts arrive; measure again then.
    document.fonts?.ready.then(resize)
    if (import.meta.env.DEV) window.__frame = (t) => { cancelAnimationFrame(raf); frame(t ?? performance.now()); cancelAnimationFrame(raf) }
    const slot = anchorRef?.current
    const enter = () => { brandTarget = 1 }
    const exit = () => { brandTarget = 0 }
    slot?.parentElement?.addEventListener('pointerenter', enter)
    slot?.parentElement?.addEventListener('pointerleave', exit)
    canvas.addEventListener('pointermove', move)
    canvas.addEventListener('pointerdown', down)
    window.addEventListener('pointerup', up)
    canvas.addEventListener('pointerleave', leave)
    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      canvas.removeEventListener('pointermove', move)
      canvas.removeEventListener('pointerdown', down)
      window.removeEventListener('pointerup', up)
      canvas.removeEventListener('pointerleave', leave)
      slot?.parentElement?.removeEventListener('pointerenter', enter)
      slot?.parentElement?.removeEventListener('pointerleave', exit)
    }
  }, [anchorRef])

  return (
    <section className={`globe ${open ? 'is-open' : ''}`} aria-label="The world's crypto exchanges on a globe">
      <div className="globe-stage" ref={wrapRef}>
        <canvas ref={canvasRef} />
        {tip && (
          <div className="globe-tip" style={{ left: tip.x, top: tip.y, '--era': (ERAS[eraOf(tip.year)] ?? ERAS[0]).color }}>
            <b>{tip.name}</b>
            <dl>
              <dt>Established</dt><dd>{tip.year ?? 'Not stated'}</dd>
              <dt>Headquarters</dt><dd>{tip.country}</dd>
            </dl>
          </div>
        )}
      </div>

      <div className="globe-hint">
        {hint}
      </div>

      <aside className="globe-side left" aria-label="Where exchanges register">
        <header>
          <span className="micro">Where exchanges register</span>
          <p><b>{globeData.points.length}</b> exchanges in <b>{countries}</b> countries</p>
        </header>
        <ol className="juris" onMouseLeave={() => setFocusCountry(null)}>
          {jurisdictions.top.map((j) => (
            <li
              key={j.country}
              className={focusCountry?.country === j.country ? 'on' : ''}
              onMouseEnter={() => setFocusCountry(j)}
            >
              <span className="name">{j.country}</span>
              <span className="bar"><i style={{ width: `${(j.n / jurisdictions.top[0].n) * 100}%` }} /></span>
              <span className="n">{j.n}</span>
            </li>
          ))}
          <li className="other">
            <span className="name">{jurisdictions.otherCountries} other countries</span>
            <span className="bar" />
            <span className="n">{jurisdictions.other}</span>
          </li>
        </ol>

        <div className="eras">
          <span className="micro">Founded</span>
          <ol className="juris era-rows" onMouseLeave={() => setFocusEra(null)}>
            {ERAS.map((e, i) => (
              <li key={e.key} onMouseEnter={() => setFocusEra(i)} className={focusEra === i ? 'on' : ''}>
                <span className="name" title={e.note}><i style={{ background: e.color }} />{e.label}</span>
                <span className="bar"><i style={{ width: `${(eraCounts[i] / Math.max(...eraCounts)) * 100}%`, background: e.color }} /></span>
                <span className="n">{eraCounts[i]}</span>
              </li>
            ))}
          </ol>
        </div>
      </aside>

      <aside className="globe-side right" aria-label="What Exchequer can see">
        <header>
          <span className="micro">What Exchequer can see</span>
          <p>{coverage === false ? 'Backend offline — numbers unavailable' : coverage ? `Live, across ${coverage.chains.length} blockchains` : 'Reading the label files…'}</p>
        </header>
        {coverage && (
          <dl className="cover">
            <div><dt>Exchange wallets labelled</dt><dd><CountUp to={coverage.exchange} /></dd></div>
            <div className="risk"><dt>Reported stolen or phishing</dt><dd><CountUp to={coverage.stolen} /></dd></div>
            <div className="risk"><dt>Frozen by Tether</dt><dd><CountUp to={coverage.frozen} /></dd></div>
            <div className="risk"><dt>Under government sanctions</dt><dd><CountUp to={coverage.sanctioned} /></dd></div>
            <div className="risk"><dt>Mixer pools</dt><dd><CountUp to={coverage.mixer} /></dd></div>
          </dl>
        )}
        {coverage && <p className="chains">{coverage.chains.map((c) => CHAIN_NAMES[c] ?? c).join(' · ')}</p>}
      </aside>

      <div className="globe-src">Exchanges: CoinGecko, {globeData.fetched} · drag to turn · hover a dot</div>
    </section>
  )
}

/** A number that counts up once when it first appears, then holds still. */
function CountUp({ to, ms = 1200 }) {
  const [value, setValue] = useState(0)
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setValue(to); return undefined }
    let raf = 0
    const start = performance.now()
    const tick = (now) => {
      const t = Math.min(1, (now - start) / ms)
      setValue(Math.round(to * (1 - Math.pow(1 - t, 3))))
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [to, ms])
  return value.toLocaleString('en-IN')
}
