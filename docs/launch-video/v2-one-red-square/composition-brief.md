# Hyperframes Composition Brief: Exchequer — v2 "One red square"

## Objective
A 28.2 s cinematic narrative brag video for Exchequer built from type and drawn illustration only — no screen captures.

## Output
- Composition directory: `composition/` · Rendered video: `brag.mp4` · Poster: `brag.jpg` (the drawn trace at 11.9 s, baked as frame 0)
- Format: landscape 1920×1080 · 30 fps · 33.2 s (narrated; 28.2 s without)

## Source Material
- `~/exchequer`: README.md (claims, validation numbers), DEMO.md (trace 7's OFAC designation, present-mode copy), `frontend/src/styles.css` (tokens), `Mark.jsx` (the chequer geometry), `backend/data/*labels*.json` (407 exchange labels · 28 exchanges · 3 chains; 407 OFAC addresses = 124 + 282 + 1)
- Copy verbatim from the repo: "A victim reports one wallet address." · "Every attribution is an exact match against a published exchange wallet." · "No model. No clustering. No proprietary score." · "Traces cryptocurrency fraud from a reported wallet to the exchange it was cashed out through." · flagship trace facts (Binance 14 · 0.90 · 2 hops · 129 addresses · 144 transfers · 53 API calls · 3.236427 ETH · 0x28c6c6…f21d60)

## Creative Direction
- Tone: cinematic · direction: a title sequence for a cyber-crime unit; one red square (the money, from the mark's red cell) carries the story through all six beats
- Beats: the report (the wall → the needle → the headline → the typed address) → the trace, drawn → screened → the handoff → the stance → Exchequer (see brag-plan.md)
- Avoid: screenshots, zoom-in/out on UI, generic SaaS language, web-page layouts

## Visual Identity
- Beat 1 opens on a full-frame wall of seeded wallet addresses under a directional scrim, one of them red — the needle. Elsewhere #0b0c0e ground with a drifting 60 px ledger grid at 10% ink, a red radial glow that follows the money, an edge vignette, ghost beat numerals; ink #ececea, muted #a0a5ab, red #ff5c5c, green #2fd3a2, amber #e0a44a; paper card #f5f4f0 / #16191d
- IBM Plex Serif 600 headlines (68–124 px), IBM Plex Sans body (26–32 px), IBM Plex Mono for addresses, numbers, labels (local woff2)

## Audio
- Bed: the film's own score, `assets/music/bed.wav` from `score.py` — D-minor drone, a chord change on every cut, a half-time pulse on the beat grid, a sub drop per cut, risers into 12.65 and 28.97; −14.3 LUFS; ducked to 0.20 under speech, ~0.40 in the gaps, a swell to 0.55 at 31.9. No third-party music, so nothing to licence. Cuts stay locked to the same grid (5.28 · 12.65 · 16.86 · 23.70 · 28.97).
- SFX: pre-mixed keypresses (typing), drops (node pops, chequer cells), bell (green lock-in, finished chequer), chips (counters), switch + plate (scan, OFAC snap), card slide + wood stamp (report, seal), heavy soft impacts (stance lines)
- Audio-reactive: none by design

## Hyperframes
Single paused GSAP timeline (`window.__timelines["main"]`), SVG trace drawn with stroke-dashoffset, comet along pre-sampled path points, count-ups via proxy objects, all fonts local. Gate: `npx hyperframes check` — 0 errors, all text WCAG AA.
