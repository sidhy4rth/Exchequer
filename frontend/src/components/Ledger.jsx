import { useEffect, useRef } from 'react'
import { currentTheme } from '../theme'
import { fetchLedger } from '../api'

// The sign-in backdrop: the ledger the tool knows, drifting in lanes.
//
// Every address is real, fetched from the backend: the sanctions list it
// screens against (red), the exchange wallets it attributes to (one hue per
// exchange), the deposit addresses it has inferred (the exchange's colour,
// dotted) and the unlabelled intermediaries of the stored cases (grey). The
// cursor resolves the ones near it -- the full address, its colour, and what
// the tool knows about it -- and nothing ever prints over anything else: each
// lane knows every address's width and moves neighbours aside as one grows.
// A click traces the address under it: a lit route hops across the ledger to
// the nearest exchange wallet, or says honestly that none was within reach.

const P = { lane: 34, reach: 210, drift: 9, gap: 22, hop: 0.55, traceLife: 6.5 }
const CHAR = 0.6 // IBM Plex Mono advance, in em

// One hue per exchange at similar lightness; red belongs to the sanctions
// list alone; grey to everyone unlabelled.
const EXCHANGE = {
  Binance: [243, 186, 47], Coinbase: [92, 140, 255], Kraken: [178, 132, 255], OKX: [200, 235, 255],
  'Huobi / HTX': [58, 184, 255], Bitfinex: [128, 214, 138], KuCoin: [47, 211, 162], Bybit: [255, 143, 90],
  'Gate.io': [110, 231, 255], Poloniex: [158, 207, 90], Bithumb: [255, 158, 209], 'Crypto.com': [126, 165, 255],
  Gemini: [160, 224, 255], HitBTC: [195, 214, 74], Bitstamp: [111, 220, 140], Upbit: [122, 197, 255],
  Remitano: [255, 211, 110], Bittrex: [166, 182, 255],
}
const PALETTE = {
  dark: { bg: '#07090c', sanctioned: [255, 92, 92], wallet: [176, 182, 188], ink: '236,236,234', red: '255,92,92' },
  light: { bg: '#f3f1ea', sanctioned: [179, 38, 30], wallet: [70, 76, 84], ink: '22,25,29', red: '179,38,30' },
}
const AMBIENT = { sanctioned: 0.36, exchange: 0.36, inferred: 0.22, wallet: 0.11 }

// With the backend unreachable the page still needs a sea: a few hundred
// plain hex strings, all unlabelled, so nothing is claimed about them.
function placeholder(n = 360) {
  const hex = '0123456789abcdef'
  const out = []
  let seed = 99
  const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296 }
  for (let i = 0; i < n; i += 1) {
    let a = '0x'
    for (let k = 0; k < 40; k += 1) a += hex[Math.floor(rnd() * 16)]
    out.push({ a, k: 'wallet', e: '', t: '' })
  }
  return out
}

export default function Ledger() {
  const ref = useRef(null)

  useEffect(() => {
    const cvs = ref.current
    const ctx = cvs.getContext('2d')
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
    let palette = PALETTE[currentTheme()]
    let W = 0; let H = 0; let lanes = []
    let data = placeholder()
    const pointer = { x: -1e9, y: -1e9, active: false }
    let traces = []
    let frame = 0
    let seed = 7
    const rnd = (a, b) => { seed = (seed * 1664525 + 1013904223) >>> 0; return a + (seed / 4294967296) * (b - a) }

    const colorOf = (it) => (it.k === 'sanctioned' ? palette.sanctioned : (EXCHANGE[it.e] || (it.e ? [47, 211, 162] : palette.wallet)))

    function build() {
      lanes = []
      seed = 7
      const count = Math.floor((H - 80) / P.lane)
      let k = 0
      for (let r = 0; r < count; r += 1) {
        const y = 44 + r * P.lane
        const v = rnd(0.5, 1.3) * (r % 2 ? 1 : -1)
        const items = []
        let x = rnd(-160, 0)
        while (x < W + 160) {
          const d = data[k % data.length]; k += 1
          items.push({ ...d, x, disp: 0, heat: 0, w: 0, size: 10.5, text: '', tag: '' })
          x += 8 * CHAR * 10.5 + P.gap + rnd(30, 140)
        }
        lanes.push({ y, v, items })
      }
    }
    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      W = cvs.clientWidth; H = cvs.clientHeight
      cvs.width = Math.round(W * dpr); cvs.height = Math.round(H * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      build()
    }
    resize()

    // The real ledger, when the backend answers.
    let cancelled = false
    fetchLedger().then((body) => {
      if (cancelled || !body?.entries?.length) return
      data = body.entries
      build()
    }).catch(() => {})

    const onMove = (e) => {
      const rect = cvs.getBoundingClientRect()
      pointer.x = e.clientX - rect.left; pointer.y = e.clientY - rect.top; pointer.active = true
    }
    const onLeave = () => { pointer.active = false }
    const onTheme = () => { palette = PALETTE[currentTheme()] }

    const pos = (it, lane) => ({ x: it.x + it.disp + it.w / 2, y: lane.y })
    function nearestItem(x, y, within, avoid, accept) {
      let best = null; let bd = within * within
      for (const lane of lanes) {
        for (const it of lane.items) {
          if (avoid && avoid.has(it)) continue
          if (accept && !accept(it, lane)) continue
          const p = pos(it, lane)
          if (p.x < 0 || p.x > W) continue
          const d2 = (p.x - x) ** 2 + (p.y - y) ** 2
          if (d2 < bd) { bd = d2; best = { it, lane } }
        }
      }
      return best
    }
    const onClick = (e) => {
      if (e.target && e.target.closest && e.target.closest('form, button, a')) return
      const rect = cvs.getBoundingClientRect()
      const start = nearestItem(e.clientX - rect.left, e.clientY - rect.top, 110)
      if (!start) return
      const hops = [start]
      const used = new Set([start.it])
      const isExchange = (it) => it.k === 'exchange' || it.k === 'inferred'
      let reached = isExchange(start.it)
      for (let h = 0; h < 3 && !reached; h += 1) {
        const cur = hops[hops.length - 1]
        const p = pos(cur.it, cur.lane)
        const otherLane = (lane) => lane !== cur.lane && Math.abs(lane.y - p.y) <= P.lane * 3
        const next = nearestItem(p.x, p.y, 320, used, (it, lane) => otherLane(lane) && isExchange(it))
          || nearestItem(p.x, p.y, 260, used, (it, lane) => otherLane(lane))
        if (!next) break
        hops.push(next); used.add(next.it)
        if (isExchange(next.it)) reached = true
      }
      traces.push({ hops, t: performance.now() / 1000, reached })
      if (traces.length > 2) traces.shift()
    }

    window.addEventListener('resize', resize)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseleave', onLeave)
    window.addEventListener('click', onClick)
    window.addEventListener('themechange', onTheme)

    let last = performance.now() / 1000
    const ease = (u) => u * u * (3 - 2 * u)

    function draw() {
      const now = performance.now() / 1000
      const dt = Math.min(0.05, now - last); last = now
      ctx.fillStyle = palette.bg; ctx.fillRect(0, 0, W, H)
      traces = traces.filter((t) => now - t.t < P.traceLife)
      const pinned = new Map()
      for (const tr of traces) {
        const age = now - tr.t
        tr.hops.forEach((h, i) => { if (age >= i * P.hop) pinned.set(h.it, Math.min(1, (age - i * P.hop) / 0.35)) })
      }
      ctx.textBaseline = 'middle'; ctx.textAlign = 'left'

      for (const lane of lanes) {
        const y = lane.y
        for (const it of lane.items) {
          it.x += lane.v * P.drift * dt
          if (it.x > W + 260) it.x -= W + 520; else if (it.x < -260) it.x += W + 520
          let focus = 0
          if (pointer.active) {
            const d = Math.hypot(it.x + it.disp + 40 - pointer.x, y - pointer.y)
            if (d < P.reach) focus = 1 - d / P.reach
          }
          it.heat = Math.max(it.heat * 0.9, focus, pinned.get(it) || 0)
          const f = it.heat
          const chars = 8 + Math.round(f * f * 34)
          it.size = 10.5 + f * 2.5
          it.text = it.a.slice(0, chars) + (chars < 42 ? '…' : '')
          it.tag = f > 0.72 && it.t ? it.t.toUpperCase() : ''
          it.w = it.text.length * CHAR * it.size + (it.tag ? 14 + it.tag.length * CHAR * 10 : 0)
        }
        // Never overlap: where each address has to sit, then glide there.
        lane.items.sort((a, b) => a.x - b.x)
        let edge = -Infinity
        for (const it of lane.items) {
          const target = Math.max(it.x, edge) - it.x
          // Pushed aside at once -- an overlap must never be drawn -- and
          // only the way back is eased.
          it.disp = target > it.disp ? target : it.disp + (target - it.disp) * 0.3
          edge = it.x + it.disp + it.w + P.gap
        }
        for (const it of lane.items) {
          const x = it.x + it.disp
          if (x + it.w < -10 || x > W + 10) continue
          const [r, g, b] = colorOf(it)
          const f = it.heat
          const alpha = Math.min(1, AMBIENT[it.k] * 0.55 + f * 0.95) * (it.k === 'inferred' ? 0.75 : 1)
          ctx.font = `400 ${it.size}px "IBM Plex Mono", Menlo, monospace`
          ctx.fillStyle = `rgba(${r},${g},${b},${alpha.toFixed(3)})`
          const glow = Math.max(f, it.k === 'wallet' ? 0 : 0.22)
          if (glow > 0.2) {
            ctx.shadowColor = `rgba(${r},${g},${b},${Math.min(1, glow * 0.9).toFixed(3)})`
            ctx.shadowBlur = 4 + glow * 16
            ctx.fillText(it.text, x, y)
            ctx.shadowBlur = 0; ctx.shadowColor = 'transparent'
          }
          ctx.fillText(it.text, x, y)
          if (it.k === 'inferred' && f > 0.2) {
            ctx.strokeStyle = `rgba(${r},${g},${b},${(alpha * 0.9).toFixed(3)})`; ctx.setLineDash([2, 3]); ctx.lineWidth = 1
            ctx.beginPath(); ctx.moveTo(x, y + it.size * 0.7); ctx.lineTo(x + it.text.length * CHAR * it.size, y + it.size * 0.7); ctx.stroke()
            ctx.setLineDash([])
          }
          if (it.tag) {
            ctx.font = '500 10px "IBM Plex Mono", Menlo, monospace'
            ctx.fillStyle = `rgba(${r},${g},${b},${((f - 0.72) / 0.28 * 0.95).toFixed(3)})`
            ctx.fillText(it.tag, x + it.text.length * CHAR * it.size + 14, y)
          }
        }
      }

      // Traces: a lit route hopping address to address, and a verdict.
      for (const tr of traces) {
        const age = now - tr.t; const fade = Math.min(1, (P.traceLife - age) / 0.8)
        ctx.lineCap = 'round'
        for (let i = 1; i < tr.hops.length; i += 1) {
          const u = ease(Math.max(0, Math.min(1, (age - i * P.hop) / P.hop)))
          if (u <= 0) break
          const a = pos(tr.hops[i - 1].it, tr.hops[i - 1].lane); const b = pos(tr.hops[i].it, tr.hops[i].lane)
          const dir = b.y >= a.y ? 1 : -1
          const ax = a.x; const ay = a.y + dir * P.lane * 0.34; const bx = b.x; const by = b.y - dir * P.lane * 0.34
          const mx = (ax + bx) / 2 + (by - ay) * 0.25; const my = (ay + by) / 2 - (bx - ax) * 0.12
          const at = (t) => [(1 - t) * (1 - t) * ax + 2 * (1 - t) * t * mx + t * t * bx, (1 - t) * (1 - t) * ay + 2 * (1 - t) * t * my + t * t * by]
          ctx.beginPath(); ctx.moveTo(ax, ay)
          for (let k = 1; k <= 24; k += 1) { const [x, y] = at(u * k / 24); ctx.lineTo(x, y) }
          ctx.strokeStyle = `rgba(${palette.red},${(0.22 * fade).toFixed(3)})`; ctx.lineWidth = 7; ctx.stroke()
          ctx.strokeStyle = `rgba(${palette.red},${(0.9 * fade).toFixed(3)})`; ctx.lineWidth = 1.4; ctx.stroke()
          ctx.shadowColor = `rgba(${palette.red},${(0.9 * fade).toFixed(3)})`; ctx.shadowBlur = 14
          if (u < 1) {
            for (let k = 0; k < 6; k += 1) {
              const [x, y] = at(Math.max(0, u - k * 0.03))
              ctx.fillStyle = `rgba(255,200,200,${((1 - k / 6) * fade).toFixed(3)})`
              ctx.beginPath(); ctx.arc(x, y, 3 - k * 0.35, 0, Math.PI * 2); ctx.fill()
            }
          } else {
            ctx.strokeStyle = `rgba(${palette.red},${(0.8 * fade).toFixed(3)})`; ctx.lineWidth = 1
            ctx.beginPath(); ctx.arc(bx, by + dir * 4, 4.5, 0, Math.PI * 2); ctx.stroke()
          }
          ctx.shadowBlur = 0; ctx.shadowColor = 'transparent'
        }
        if (age >= tr.hops.length * P.hop) {
          const lastHop = tr.hops[tr.hops.length - 1]; const p = pos(lastHop.it, lastHop.lane)
          const n = tr.hops.length - 1
          const [r, g, b] = colorOf(lastHop.it)
          const verdict = tr.reached
            ? `REACHED ${(lastHop.it.t || lastHop.it.e).toUpperCase()} · ${n} HOP${n === 1 ? '' : 'S'}`
            : `NO EXCHANGE WITHIN ${n} HOP${n === 1 ? '' : 'S'}`
          ctx.font = '500 10px "IBM Plex Mono", Menlo, monospace'
          const tw = verdict.length * CHAR * 10
          const tx = Math.min(p.x - lastHop.it.w / 2, W - tw - 12)
          ctx.fillStyle = tr.reached ? `rgba(${r},${g},${b},${fade.toFixed(3)})` : `rgba(138,144,152,${fade.toFixed(3)})`
          ctx.fillText(verdict, tx, p.y + P.lane * 0.55)
        }
      }

      if (pointer.active) {
        const halo = ctx.createRadialGradient(pointer.x, pointer.y, 0, pointer.x, pointer.y, P.reach)
        halo.addColorStop(0, `rgba(${palette.ink},0.05)`); halo.addColorStop(1, `rgba(${palette.ink},0)`)
        ctx.fillStyle = halo; ctx.beginPath(); ctx.arc(pointer.x, pointer.y, P.reach, 0, Math.PI * 2); ctx.fill()
        ctx.strokeStyle = `rgba(${palette.ink},0.10)`; ctx.lineWidth = 1
        ctx.beginPath(); ctx.arc(pointer.x, pointer.y, P.reach * 0.5, 0, Math.PI * 2); ctx.stroke()
      }
      frame = requestAnimationFrame(draw)
    }

    if (reduced) {
      // No motion: one still frame of the sea.
      ctx.fillStyle = palette.bg; ctx.fillRect(0, 0, W, H)
      ctx.font = '400 10.5px "IBM Plex Mono", Menlo, monospace'; ctx.textBaseline = 'middle'
      for (const lane of lanes) for (const it of lane.items) {
        const [r, g, b] = colorOf(it)
        ctx.fillStyle = `rgba(${r},${g},${b},${(AMBIENT[it.k] * 0.55).toFixed(3)})`
        ctx.fillText(`${it.a.slice(0, 8)}…`, it.x, lane.y)
      }
    } else {
      frame = requestAnimationFrame(draw)
    }

    return () => {
      cancelled = true
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseleave', onLeave)
      window.removeEventListener('click', onClick)
      window.removeEventListener('themechange', onTheme)
    }
  }, [])

  return <canvas ref={ref} className="lattice" aria-hidden="true" />
}
