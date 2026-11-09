import { useEffect, useRef, useState } from 'react'
import globeData from '../data/exchange_globe.json'
import { ERAS, landDots } from './ExchangeGlobe'
import './GlobeBackground.css'

// The investigator console's backdrop: the sign-in globe, half off the right
// edge, so the console and its front door read as one place. Dotted land, a
// sparse sea lattice, every placed exchange lit in its founding era's colour,
// and a red rim. It turns once in about 80 s. In the empty parts of the page
// it can be taken by hand: drag to spin (it coasts back to its turn), hover an
// exchange for its name, click one for a ripple. It never takes a click or a
// key from a form control, and under reduced motion it holds still.

const RAD = Math.PI / 180
const CRUISE = -4.5 // degrees of longitude per second
const RIPPLE_MS = 1800
// Strength of the whole drawing, tuned on the design canvas (intensity 0.6 × 1.45).
const K = 0.87
// The red rim's colour in each theme and its strongest alpha: the brightest
// glow behind the console's glass (tokens.test.js holds the console's text
// and field edges to it).
export const RIM = { light: [189, 35, 41], dark: [255, 90, 78], alpha: 0.34 * K }
// Where a pointer belongs to the page rather than to the globe.
const CONTROLS = 'input,select,textarea,button,a,label,summary,[role="tab"],table,form'

const prep = (lat, lon) => ({ sl: Math.sin(lat * RAD), cl: Math.cos(lat * RAD), lr: lon * RAD })
const eraOf = (year) => Math.max(0, ERAS.findIndex((e) => e.test(year ?? 0)))

function halo(rgb) {
  const c = document.createElement('canvas')
  c.width = c.height = 32
  const x = c.getContext('2d')
  if (!x) return c
  const g = x.createRadialGradient(16, 16, 0, 16, 16, 16)
  g.addColorStop(0, `rgba(${rgb}, 0.95)`)
  g.addColorStop(0.2, `rgba(${rgb}, 0.55)`)
  g.addColorStop(0.5, `rgba(${rgb}, 0.15)`)
  g.addColorStop(1, `rgba(${rgb}, 0)`)
  x.fillStyle = g
  x.fillRect(0, 0, 32, 32)
  return c
}

/** Globe size and position for a viewport: half off the right edge on a desk,
 * smaller and further out on a phone so it never sits under the form. */
export function placeGlobe(w, h) {
  const R = Math.min(h * 0.68, w * 0.75)
  return { R, cx: w - R * (w < 720 ? 0.25 : 0.48), cy: h * 0.56 }
}

export default function GlobeBackground() {
  const ref = useRef(null)
  const [tip, setTip] = useState(null)
  const [cursor, setCursor] = useState('')

  useEffect(() => {
    const canvas = ref.current
    const ctx = canvas?.getContext?.('2d')
    if (!ctx) return undefined
    const still = Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)

    const { land, sea } = landDots(2.6)
    const exchanges = globeData.points.map((p, i) => ({ ...prep(p.lat, p.lon), p, era: eraOf(p.year), ph: (i * 0.618) % 1 }))
    const halos = ERAS.map((e) => halo(e.rgb))

    const rot = { lon: 78, lat: 18, v: CRUISE, tilt: 0, pan: 0 }
    const state = { mouse: null, drag: false, hover: null, hits: [], ripples: [], geo: null, last: performance.now(), light: false }
    let raf = 0

    function readTheme() { state.light = document.documentElement.dataset.theme === 'light' }
    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(window.innerWidth * dpr)
      canvas.height = Math.round(window.innerHeight * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    function draw(now) {
      const w = window.innerWidth, h = window.innerHeight
      const dt = Math.min(0.05, (now - state.last) / 1000)
      state.last = now
      if (!state.drag && !still) {
        rot.v += (CRUISE - rot.v) * Math.min(1, dt * 1.2)
        rot.lon += rot.v * dt
      }
      const m = state.mouse
      const tilt = m && !still ? ((m.y / h) - 0.5) * -10 : 0
      const pan = m && !still ? ((m.x / w) - 0.5) * 8 : 0
      rot.tilt += (tilt - rot.tilt) * Math.min(1, dt * 3)
      rot.pan += (pan - rot.pan) * Math.min(1, dt * 3)

      const { R, cx, cy } = placeGlobe(w, h)
      state.geo = { R, cx, cy }
      const spin = (rot.lon + rot.pan) * RAD
      const vlat = (rot.lat + rot.tilt) * RAD
      const s0 = Math.sin(vlat), c0 = Math.cos(vlat)
      const project = (q) => {
        const dl = q.lr - spin
        const x = q.cl * Math.sin(dl)
        const y = c0 * q.sl - s0 * q.cl * Math.cos(dl)
        const z = s0 * q.sl + c0 * q.cl * Math.cos(dl)
        return [cx + R * x, cy - R * y, z]
      }
      const light = state.light
      const accent = (light ? RIM.light : RIM.dark).join(', ')
      const ink = light ? '10, 10, 10' : '237, 237, 237'

      ctx.clearRect(0, 0, w, h)
      const rim = ctx.createRadialGradient(cx, cy, R * 0.86, cx, cy, R * 1.18)
      rim.addColorStop(0, `rgba(${accent}, 0)`)
      rim.addColorStop(0.42, `rgba(${accent}, ${RIM.alpha.toFixed(3)})`)
      rim.addColorStop(1, `rgba(${accent}, 0)`)
      ctx.fillStyle = rim
      ctx.beginPath(); ctx.arc(cx, cy, R * 1.18, 0, Math.PI * 2); ctx.fill()
      const body = ctx.createRadialGradient(cx - R * 0.3, cy - R * 0.35, R * 0.1, cx, cy, R)
      body.addColorStop(0, light ? 'rgba(255, 255, 255, 0.35)' : 'rgba(40, 22, 26, 0.55)')
      body.addColorStop(1, light ? 'rgba(244, 244, 244, 0.15)' : 'rgba(12, 10, 12, 0.25)')
      ctx.fillStyle = body
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill()

      const s = Math.max(1.8, R / 260)
      ctx.fillStyle = `rgb(${ink})`
      for (const q of sea) {
        const p = project(q)
        if (p[2] <= 0) continue
        ctx.globalAlpha = 0.16 * p[2] * K
        ctx.fillRect(p[0] - s * 0.4, p[1] - s * 0.4, s * 0.8, s * 0.8)
      }
      ctx.fillStyle = `rgb(${accent})`
      for (const q of land) {
        const p = project(q)
        if (p[2] <= 0) continue
        ctx.globalAlpha = (0.12 + 0.5 * p[2]) * 1.6 * K
        ctx.fillRect(p[0] - s / 2, p[1] - s / 2, s, s)
      }
      const t = now / 1000
      const hits = []
      exchanges.forEach((q, i) => {
        const p = project(q)
        if (p[2] <= 0.05) return
        hits.push([p[0], p[1], i])
        const on = state.hover === i
        const pulse = still ? 1 : 0.65 + 0.35 * Math.sin(t * 1.2 + q.ph * Math.PI * 2)
        ctx.globalAlpha = Math.min(1, (on ? 1.6 : 1) * p[2] * pulse * 1.7 * K)
        const hs = s * (on ? 16 : 9)
        ctx.drawImage(halos[q.era], p[0] - hs / 2, p[1] - hs / 2, hs, hs)
      })
      state.hits = hits
      state.ripples = state.ripples.filter((r) => now - r.t0 < RIPPLE_MS)
      for (const r of state.ripples) {
        const q = exchanges[r.i]
        const p = project(q)
        if (p[2] <= 0) continue
        const f = (now - r.t0) / RIPPLE_MS
        ctx.globalAlpha = (1 - f) * 0.9
        ctx.strokeStyle = `rgb(${ERAS[q.era].rgb})`
        ctx.lineWidth = 2
        ctx.beginPath(); ctx.arc(p[0], p[1], 6 + f * 70, 0, Math.PI * 2); ctx.stroke()
        ctx.beginPath(); ctx.arc(p[0], p[1], 4 + f * 36, 0, Math.PI * 2); ctx.stroke()
      }
      ctx.globalAlpha = 1
    }

    function frame(now) {
      draw(now)
      raf = requestAnimationFrame(frame)
    }
    // Under reduced motion only a hand on the globe (or a ripple) redraws it.
    function nudge() { if (still) draw(performance.now()) }

    const isControl = (el) => Boolean(el?.closest?.(CONTROLS))
    function onMove(e) {
      const prevX = state.mouse ? state.mouse.x : e.clientX
      state.mouse = { x: e.clientX, y: e.clientY }
      if (state.drag) {
        const d = (e.clientX - prevX) * 0.3
        rot.lon += d
        rot.v = d * 30
        nudge()
        return
      }
      let best = null
      let bd = 13
      if (!isControl(e.target)) {
        for (const hit of state.hits) {
          const dd = Math.hypot(hit[0] - e.clientX, hit[1] - e.clientY)
          if (dd < bd) { bd = dd; best = hit }
        }
      }
      const g = state.geo
      const onGlobe = !isControl(e.target) && g && Math.hypot(e.clientX - g.cx, e.clientY - g.cy) < g.R
      const hover = best ? best[2] : null
      if (hover !== state.hover) {
        state.hover = hover
        const p = best ? exchanges[best[2]].p : null
        setTip(p ? { x: e.clientX, y: e.clientY, name: p.name, meta: `${p.country} · founded ${p.year}` } : null)
        nudge()
      }
      setCursor(best ? 'point' : onGlobe ? 'grab' : '')
    }
    function onDown(e) {
      const g = state.geo
      if (!g || isControl(e.target) || state.hover != null) return
      if (Math.hypot(e.clientX - g.cx, e.clientY - g.cy) < g.R) {
        state.drag = true
        setCursor('grabbing')
        setTip(null)
        e.preventDefault()
      }
    }
    function onUp() {
      if (!state.drag) return
      state.drag = false
      setCursor('grab')
    }
    function onClick(e) {
      if (state.hover == null || isControl(e.target)) return
      state.ripples.push({ i: state.hover, t0: performance.now() })
      if (still) {
        // No animation loop to play the ripple: run one just for it.
        const end = performance.now() + RIPPLE_MS
        const step = (now) => { draw(now); if (now < end) requestAnimationFrame(step) }
        requestAnimationFrame(step)
      }
    }
    function onLeave() {
      state.mouse = null
      state.drag = false
      state.hover = null
      setTip(null)
      setCursor('')
    }
    function onVisibility() {
      cancelAnimationFrame(raf)
      if (!still && document.visibilityState === 'visible') raf = requestAnimationFrame(frame)
    }

    readTheme()
    resize()
    draw(performance.now())
    if (!still) raf = requestAnimationFrame(frame)
    const theme = new MutationObserver(() => { readTheme(); draw(performance.now()) })
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const onResize = () => { resize(); draw(performance.now()) }
    window.addEventListener('resize', onResize)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    window.addEventListener('click', onClick)
    document.documentElement.addEventListener('pointerleave', onLeave)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      cancelAnimationFrame(raf)
      theme.disconnect()
      window.removeEventListener('resize', onResize)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
      window.removeEventListener('click', onClick)
      document.documentElement.removeEventListener('pointerleave', onLeave)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  // The cursor shows what a press would do; it lives on <body> because the
  // canvas itself takes no pointer events.
  useEffect(() => {
    const body = document.body
    body.classList.remove('globe-grab', 'globe-grabbing', 'globe-point')
    if (cursor) body.classList.add(`globe-${cursor}`)
    return () => body.classList.remove('globe-grab', 'globe-grabbing', 'globe-point')
  }, [cursor])

  return (
    <>
      <canvas ref={ref} className="globe-bg" aria-hidden="true" data-testid="globe-bg" />
      {tip && (
        <div className="globe-tip" style={{ left: tip.x, top: tip.y }} aria-hidden="true">
          <strong>{tip.name}</strong>
          <span>{tip.meta}</span>
        </div>
      )}
    </>
  )
}
