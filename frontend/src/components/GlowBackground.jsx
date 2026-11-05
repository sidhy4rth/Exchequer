import { useEffect, useRef } from 'react'

// The investigator console's backdrop: five soft glows that drift and slowly
// cross-fade through the five chains' colours. Decoration only: no pointer
// events, no cursor tracking, one still frame under reduced motion, and no
// drawing while the tab is hidden.
const CHAIN_VARS = ['--c-tron', '--c-eth', '--c-arb', '--c-poly', '--c-bnb']
const STEP_MS = 12000
const smooth = (t) => t * t * (3 - 2 * t)

function rgb(hex) {
  const h = hex.trim().replace('#', '')
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export default function GlowBackground() {
  const ref = useRef(null)

  useEffect(() => {
    const canvas = ref.current
    const ctx = canvas?.getContext?.('2d')
    if (!ctx) return undefined
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    let raf = 0
    let colours = []
    let alpha = 0.3

    function readTheme() {
      const css = getComputedStyle(document.documentElement)
      colours = CHAIN_VARS.map((v) => rgb(css.getPropertyValue(v) || '#888888'))
      alpha = document.documentElement.dataset.theme === 'dark' ? 0.3 : 0.22
    }
    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(window.innerWidth * dpr)
      canvas.height = Math.round(window.innerHeight * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    function draw(now) {
      const w = window.innerWidth
      const h = window.innerHeight
      const r0 = Math.max(w, h) * 0.42
      ctx.clearRect(0, 0, w, h)
      for (let i = 0; i < 5; i += 1) {
        const t = now / 1000
        const x = w * (0.5 + 0.38 * Math.sin(t * (0.031 + i * 0.007) + i * 1.7))
        const y = h * (0.5 + 0.34 * Math.cos(t * (0.027 + i * 0.006) + i * 2.3))
        const r = r0 * (1 + 0.15 * Math.sin(t * (0.05 + i * 0.01) + i))
        // Each glow walks the five colours in turn, offset so no two match.
        const phase = now / STEP_MS + i
        const from = colours[Math.floor(phase) % 5]
        const to = colours[(Math.floor(phase) + 1) % 5]
        const k = smooth(phase % 1)
        const [cr, cg, cb] = from.map((c, j) => Math.round(c + (to[j] - c) * k))
        const g = ctx.createRadialGradient(x, y, 0, x, y, r)
        g.addColorStop(0, `rgba(${cr},${cg},${cb},${alpha})`)
        g.addColorStop(1, `rgba(${cr},${cg},${cb},0)`)
        ctx.fillStyle = g
        ctx.fillRect(0, 0, w, h)
      }
    }
    function frame(now) {
      draw(now)
      raf = requestAnimationFrame(frame)
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
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      cancelAnimationFrame(raf)
      theme.disconnect()
      window.removeEventListener('resize', onResize)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  return <canvas ref={ref} className="glow-bg" aria-hidden="true" />
}
