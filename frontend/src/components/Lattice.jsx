import { useEffect, useRef } from 'react'
import { currentTheme } from '../theme'

// The sign-in backdrop: a transaction lattice that the cursor scans.
//
// Hundreds of unlit wallets sit on a jittered grid, each joined to its
// nearest neighbours. Nothing shows until the pointer passes: nodes and the
// edges between them surface inside a soft radius and fade out behind it a
// few seconds later, so moving the mouse leaves a dimming trail of the graph
// it crossed. A click sends a trace pulse: a wave that runs outward from the
// nearest wallet along the edges, one hop at a time -- the same walk the tool
// performs on a real ledger -- in the red the case view uses for the traced
// funds, then dies away.
//
// Everything is plain 2D canvas, drawn only where something is lit. The graph
// is built once per resize; each frame costs one pass over the nodes to
// score their brightness and a stroke per lit edge.

const CONFIG = {
  cell: 58,          // px between wallets, before jitter
  jitter: 0.42,      // fraction of a cell a wallet may wander
  neighbours: 3,     // edges per wallet, to the nearest
  scan: 230,         // px radius of the scanner
  trail: 2.8,        // seconds a scanned wallet takes to go dark
  pulseHop: 0.11,    // seconds per hop of the trace pulse
  pulseLife: 4.2,    // seconds a pulse is visible
  ambient: 0.045,    // how much of the lattice shows unlit
}

const PALETTES = {
  dark: { ink: '236,236,234', node: '160,166,172', edge: '236,236,234', pulse: '255,92,92', reached: '47,211,162', bg: '#07090c' },
  light: { ink: '22,25,29', node: '60,66,72', edge: '22,25,29', pulse: '179,38,30', reached: '29,122,76', bg: '#f3f1ea' },
}

function buildGraph(W, H) {
  const cols = Math.ceil(W / CONFIG.cell) + 2
  const rows = Math.ceil(H / CONFIG.cell) + 2
  const nodes = []
  let seed = 1337
  const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296 }
  for (let r = -1; r < rows - 1; r += 1) {
    for (let c = -1; c < cols - 1; c += 1) {
      const jx = (rnd() - 0.5) * 2 * CONFIG.jitter * CONFIG.cell
      const jy = (rnd() - 0.5) * 2 * CONFIG.jitter * CONFIG.cell
      nodes.push({ x: c * CONFIG.cell + CONFIG.cell / 2 + jx, y: r * CONFIG.cell + CONFIG.cell / 2 + jy, r: 1.2 + rnd() * 1.6, adj: [] })
    }
  }
  // Nearest-neighbour edges, symmetric, no duplicates.
  const key = (a, b) => (a < b ? `${a}-${b}` : `${b}-${a}`)
  const seen = new Set()
  const edges = []
  const reach = CONFIG.cell * 1.7
  nodes.forEach((n, i) => {
    const near = []
    for (let j = 0; j < nodes.length; j += 1) {
      if (j === i) continue
      const m = nodes[j]
      const dx = m.x - n.x; const dy = m.y - n.y
      const d2 = dx * dx + dy * dy
      if (d2 < reach * reach) near.push([d2, j])
    }
    near.sort((a, b) => a[0] - b[0])
    near.slice(0, CONFIG.neighbours).forEach(([, j]) => {
      const k = key(i, j)
      if (seen.has(k)) return
      seen.add(k)
      edges.push([i, j])
      n.adj.push(j); nodes[j].adj.push(i)
    })
  })
  return { nodes, edges }
}

function hopsFrom(graph, start) {
  const hops = new Int16Array(graph.nodes.length).fill(-1)
  const queue = [start]; hops[start] = 0
  for (let q = 0; q < queue.length; q += 1) {
    const i = queue[q]
    graph.nodes[i].adj.forEach((j) => { if (hops[j] < 0) { hops[j] = hops[i] + 1; queue.push(j) } })
  }
  return hops
}

export default function Lattice() {
  const ref = useRef(null)

  useEffect(() => {
    const cvs = ref.current
    const ctx = cvs.getContext('2d')
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
    let W = 0; let H = 0; let dpr = 1
    let graph = { nodes: [], edges: [] }
    let trail = []          // [{x, y, t}]
    let pulses = []         // [{hops, t}]
    let pointer = null
    let frame = 0
    let palette = PALETTES[currentTheme()]

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      W = cvs.clientWidth; H = cvs.clientHeight
      cvs.width = Math.round(W * dpr); cvs.height = Math.round(H * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      graph = buildGraph(W, H)
      trail = []; pulses = []
    }
    resize()

    const onMove = (e) => {
      const rect = cvs.getBoundingClientRect()
      pointer = { x: e.clientX - rect.left, y: e.clientY - rect.top }
      const last = trail[trail.length - 1]
      if (!last || Math.hypot(last.x - pointer.x, last.y - pointer.y) > 14) {
        trail.push({ ...pointer, t: performance.now() / 1000 })
        if (trail.length > 80) trail.shift()
      }
    }
    const onLeave = () => { pointer = null }
    const onClick = (e) => {
      const rect = cvs.getBoundingClientRect()
      const x = e.clientX - rect.left; const y = e.clientY - rect.top
      let best = -1; let bd = Infinity
      graph.nodes.forEach((n, i) => { const d = (n.x - x) ** 2 + (n.y - y) ** 2; if (d < bd) { bd = d; best = i } })
      if (best >= 0) {
        pulses.push({ hops: hopsFrom(graph, best), t: performance.now() / 1000 })
        if (pulses.length > 3) pulses.shift()
      }
    }
    const onTheme = () => { palette = PALETTES[currentTheme()] }

    window.addEventListener('resize', resize)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseleave', onLeave)
    window.addEventListener('click', onClick)
    window.addEventListener('themechange', onTheme)

    const light = new Float32Array(0)
    const draw = () => {
      const now = performance.now() / 1000
      const { nodes, edges } = graph
      const lit = light.length === nodes.length ? light : new Float32Array(nodes.length)
      const red = new Float32Array(nodes.length)

      // Trail: every scanned point contributes a soft, decaying disc.
      trail = trail.filter((p) => now - p.t < CONFIG.trail)
      const r2 = CONFIG.scan * CONFIG.scan
      for (let i = 0; i < nodes.length; i += 1) {
        const n = nodes[i]
        let v = 0
        for (let k = 0; k < trail.length; k += 1) {
          const p = trail[k]
          const dx = n.x - p.x; const dy = n.y - p.y
          const d2 = dx * dx + dy * dy
          if (d2 > r2) continue
          const fall = 1 - Math.sqrt(d2) / CONFIG.scan
          const age = 1 - (now - p.t) / CONFIG.trail
          const c = fall * Math.sqrt(fall) * age
          if (c > v) v = c
        }
        if (pointer) {
          const dx = n.x - pointer.x; const dy = n.y - pointer.y
          const d2 = dx * dx + dy * dy
          if (d2 < r2) { const fall = 1 - Math.sqrt(d2) / CONFIG.scan; v = Math.max(v, fall * Math.sqrt(fall)) }
        }
        lit[i] = v
      }

      // Pulses: a wave one hop wide, running outward, fading with age.
      pulses = pulses.filter((p) => now - p.t < CONFIG.pulseLife)
      pulses.forEach((p) => {
        const age = now - p.t
        const front = age / CONFIG.pulseHop
        const fade = 1 - age / CONFIG.pulseLife
        for (let i = 0; i < nodes.length; i += 1) {
          const h = p.hops[i]
          if (h < 0 || h > front) continue
          const behind = front - h
          const w = behind < 2 ? 1 - behind / 2 * 0.55 : Math.max(0, 0.45 - (behind - 2) * 0.05)
          const c = w * fade
          if (c > red[i]) red[i] = c
        }
      })

      ctx.fillStyle = palette.bg
      ctx.fillRect(0, 0, W, H)

      // Edges first, under the nodes.
      ctx.lineWidth = 1
      for (let e = 0; e < edges.length; e += 1) {
        const [a, b] = edges[e]
        const l = Math.min(lit[a], lit[b])
        const p = Math.min(red[a], red[b])
        const alpha = Math.max(CONFIG.ambient * 0.6, l * 0.75)
        if (alpha > 0.01) {
          ctx.strokeStyle = `rgba(${palette.edge},${alpha.toFixed(3)})`
          ctx.beginPath(); ctx.moveTo(nodes[a].x, nodes[a].y); ctx.lineTo(nodes[b].x, nodes[b].y); ctx.stroke()
        }
        if (p > 0.02) {
          ctx.strokeStyle = `rgba(${palette.pulse},${(p * 0.9).toFixed(3)})`
          ctx.lineWidth = 1 + p * 1.2
          ctx.beginPath(); ctx.moveTo(nodes[a].x, nodes[a].y); ctx.lineTo(nodes[b].x, nodes[b].y); ctx.stroke()
          ctx.lineWidth = 1
        }
      }
      for (let i = 0; i < nodes.length; i += 1) {
        const n = nodes[i]
        const l = Math.max(CONFIG.ambient, lit[i])
        const p = red[i]
        if (p > 0.02) {
          ctx.fillStyle = `rgba(${palette.pulse},${Math.min(1, p * 1.1).toFixed(3)})`
          ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 1.6 * p, 0, Math.PI * 2); ctx.fill()
          if (p > 0.6) {
            ctx.strokeStyle = `rgba(${palette.pulse},${((p - 0.6) * 1.2).toFixed(3)})`
            ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 5, 0, Math.PI * 2); ctx.stroke()
          }
        } else if (l > 0.01) {
          ctx.fillStyle = `rgba(${palette.node},${Math.min(1, l * 1.5).toFixed(3)})`
          ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill()
        }
      }

      // The scanner itself: a faint ring where the pointer is.
      if (pointer) {
        ctx.strokeStyle = `rgba(${palette.ink},0.10)`
        ctx.beginPath(); ctx.arc(pointer.x, pointer.y, CONFIG.scan * 0.42, 0, Math.PI * 2); ctx.stroke()
      }

      frame = requestAnimationFrame(draw)
    }

    if (reduced) {
      // No motion: one still frame of the ambient lattice.
      ctx.fillStyle = palette.bg; ctx.fillRect(0, 0, W, H)
      ctx.strokeStyle = `rgba(${palette.edge},${CONFIG.ambient})`
      graph.edges.forEach(([a, b]) => { ctx.beginPath(); ctx.moveTo(graph.nodes[a].x, graph.nodes[a].y); ctx.lineTo(graph.nodes[b].x, graph.nodes[b].y); ctx.stroke() })
    } else {
      frame = requestAnimationFrame(draw)
    }

    return () => {
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
