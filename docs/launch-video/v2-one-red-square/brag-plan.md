# Brag Plan: Exchequer — v2, "One red square"

## What is this app?
Exchequer takes the one wallet address a fraud victim can give the police and follows the money outward, hop by hop, to the exchange it was cashed out through — naming the exchange, how sure, and the exact address to cite in the legal request, with every hop screened against the OFAC list and no model, clustering or proprietary score anywhere in the chain.

## The angle
The Exchequer was named for the chequered cloth on which the Crown's money was counted, square by square. In the mark, one square is red: the sum being traced. This video follows that red square — the victim's money — from the moment a scam takes it, through the ledger hop by hop, into an exchange wallet, onto a sealed report, and finally into its place on the chequer. No screenshots: type and drawn illustration only, built from the console's own tokens.

## Hook (first 2-3 seconds)
**The wall.** The film opens already moving: a full-frame field of 179 wallet addresses, six columns shearing past each other in alternating directions at different speeds — the ledger, the haystack. Each address is coloured by what the label files know about it, using the console's own key: **green** a labelled exchange wallet (26%), **blue** a router or service contract (27%), **red** a sanctioned address (5%), **grey** unlabelled (42%). A small legend names the four while the field is readable. Cells flicker as the field refreshes. At 0.6 s one of them turns red and takes a hairline box: the reported address, the needle. The red square docks beside it. Only then does a scrim slide under the type and the headline land: "A scam takes someone's savings." No empty frame, and the first thing the viewer sees is the problem the tool exists for.

## Key moments (the middle)
- **The trace, drawn.** The red square becomes the root node. Hop columns rise (HOP 1…4). Edges DRAW to intermediaries, nodes POP; the traced branch is heavy, dust branches thin out. A red comet runs the path; the second-hop node LOCKS IN green: "Binance 14 · published exchange wallet · exact match". Counters stack up: 129 addresses · 144 transfers · 53 API calls.
- **Screening.** A ledger of addresses scrolls like a departure board; a scan bar sweeps; one row SNAPS red: "OFAC-LISTED · SDGT". SDN list of 4 September 2026 · 124 Ethereum · 282 Tron · 1 BSC.
- **The handoff.** A paper report card SLIDES in — the only bright object in the film — finding, confidence, the address to cite, then a red SEALED stamp and the SHA-256 of what it was built from.

## Outro / punchline
"No model." / "No clustering." / "No proprietary score." slam in on three beats. Then seven ink squares fly in around the red one — the chequer assembles around the money — and Exchequer lands with the README's own sentence.

## User flow worth showing
1. Entry — the victim's address (typed, red-square caret).
2. Key action — the trace drawn hop by hop to a labelled exchange wallet.
3. Result — the sealed report: exchange, confidence, address to cite, hash.

## Tone
- Preset: cinematic
- Creative direction: a title sequence for a cyber-crime unit — trailer-scale type, one red square carrying the story, drawn evidence instead of screenshots
- Interpretation: short declarative lines, each lands before the next; big reveals on strong beats; hard cuts for register shifts; every scene has a background layer (ledger grid + glow + ghost numerals), a midground (the illustration), and foreground metadata.

## Format: landscape — 1920x1080
## Duration: 37.9 seconds with narration (the bubble-map beat added 4.74 s = 9 beats of the grid, so every later cut still lands on a real beat) (28.2 s silent cut; the voice set the pace of beats 4–6, per the `--voice` rule)

## Visual identity (from the project)
- Background: #0b0c0e (console dark skin) with a 60 px ledger grid at ~10% ink, drifting
- Accent: #ff5c5c red — the money, the caret, the sanctions hit, the seal; #2fd3a2 green — the confirmed exchange match; #e0a44a amber — "Restricted"
- Text: #ececea ink · #a0a5ab muted · #9aa0a6 micro labels; paper card #f5f4f0 with #16191d ink
- Display font: IBM Plex Serif 600/500 (96–130 px headlines)
- Body font: IBM Plex Sans 400/500 (28–34 px); IBM Plex Mono for every address, number, label
- Strongest visual element: the chequer (4×4, one square red) and the FlowView idea — a heavy red path across hop columns to a green node

## Voiceover script
Voice: Kokoro `bf_emma` (British female), speed 1.0, one clip per line on its own track; bed ducked to 0.13 under speech, ~0.3 in the gaps, a short swell at the end.

| Beat | Starts | Line |
|---|---|---|
| 1 | 0.35 | When a scam empties someone's savings, the police get back a wallet address. |
| 2 | 5.55 | Exchequer follows the money, hop by hop, to a wallet an exchange has published as its own. |
| 3 | 12.85 | Every address on the way is checked against the sanctions list. |
| 4 | 17.05 | The result: a sealed report. The exchange, how sure, and the address to name in the request. |
| 5 | 23.72 / 24.77 / 25.86 / 27.42 | No model. · No clustering. · No proprietary score. · But everything hand-checked. |
| 6 | 29.20 | That's Exchequer for you in a nutshell. |

Sync: beat 5's three phrases are separate clips placed on the three slams (23.70 / 24.75 / 25.81) so each "No" lands with its line; "But everything hand-checked." starts as the red rule draws (27.39); the closer plays over the chequer assembling, "Exchequer" spoken as the wordmark lands. Beat 4: the SEALED stamp lands at 18.6, right after "sealed report"; a red underline sweeps the finding line on "the exchange, how sure" (19.0) and the address line on "and the address to name" (20.25); the hash types in after.

## Share copy (draft)
One red square. Exchequer follows a fraud victim's money hop by hop to the exchange it was cashed out through — the exchange, how sure, the address to cite — with every hop screened against the OFAC list and nothing you cannot re-check by hand. SIH 2026 · SIH26183.

## Audio direction
- Role: a steady bed with real presence; SFX carry the motion
- **The investigating figure:** a four-note ostinato on eighth notes that follows the chord under it, with a dry off-beat tick running beside it. It is the search. It enters exactly when the trace starts (5.28), tightens under the sanctions sweep with sixteenth-note telemetry ticks tracking the scan bar (12.85–14.30), thins to downbeats once the answer is found (16.86), **stops dead under the stance** so "No model / No clustering / No proprietary score" land in the clear, and returns to resolve under the mark. Measured arc in the 150–700 Hz band, relative to the loudest moment: beat 1 −7.3 · trace −4.4 · screened −6.2 · report −5.2 · **stance −9.5** · mark −3.6.
- Music: **the film's own score** — `assets/music/bed.wav`, generated by `score.py` (no samples, no licence to clear). D minor: a drone under the whole piece, a pad that changes chord on every scene cut (Dm → Dm add C → **Bb** under the sanctions beat → **F** under the report, the only lift → D root-and-fifth, stripped, under the stance → Dm add9 under the mark), a half-time pulse on the music's own beats, a sub drop on each hard cut and a riser into the two biggest turns (12.65, 28.97). Matched to −14.3 LUFS, the loudness of the track it replaced, so the ducking lane kept its values. It replaced the bundled "Happy Beats / Business Moves vol. 11" — corporate optimism under a cyber-crime film, and a licence that would have needed clearing before posting.
- Beat grid: taken from that track's cue preset, the same grid every cut in this film is locked to, so a pulse never drifts off a reveal.
- Music treatment: in to 0.42 by 0.45 s, ducked to 0.20 under speech and lifted to ~0.40 in the gaps, a swell to 0.55 at 31.9 under the mark, out at 33.15
- Revert (if ever wanted): `cp ~/.claude/plugins/marketplaces/brag/skills/brag/assets/music/happy-beats-business-moves-vol-11-by-ende-dot-app.mp3 composition/assets/music/bed.mp3` and point the `#bed` element back at it
- Music cue guidance (preset): cuts locked to strong cues 5.28 · 12.65 · 16.86 · 20.54 · 24.23; inside beats: typing starts 3.18, line swap 2.65, lock-in 8.44, counters 9.5, stance lines 20.54 / 21.59 / 22.65, wordmark 24.23
- Audio-reactive treatment: none — motion is authored to the cue grid instead
- SFX posture: expressive but motion-matched: keys (typing), soft drops (nodes pop), a bell on the green lock-in and on the finished chequer, chips stacking under the counters, a plate hit on the OFAC snap, a card slide for the report, a wood stamp for the seal, heavy soft impacts for the three stance lines
- Restraint rule: two bells in the whole film; nothing rings over a line the viewer is reading

## Storyboard

### Beat 1 — The report — 5.28 s (0.00–5.28)
World: the ledger itself, at the scale a wallet address actually hides in. The frame opens FULL of addresses — six columns, thirty rows, drawn from a fixed seed so every render is the same field — already SHEARING, alternate columns running up and down at 55–240 px across the beat, the whole wall settling from 1.06 scale as if the camera arrived mid-flight and then creeping to 1.03. Colour is the console's key, not decoration: green labelled exchange, blue router or service, red sanctioned, grey unlabelled. A legend names them at the lower right and leaves with the field. Individual cells flicker as the ledger refreshes. The needle rides its own column, and the red square rides the needle. At 0.62 one address on the right SNAPS red and takes a hairline box; the red square docks beside it; a plate hit lands. That is the needle. From 0.85 a scrim slides in (dense at the left, thin at the right) and the wall dims to 55%: the field is still there, but the words can land on it. 1.0: "A scam takes someone's savings." SLIDES in from the left, serif 104 px, expo.out. 1.4: a hairline rule DRAWS under it; 1.8: the lede. 2.37 the headline is PULLED up and out; 2.65 (cue) "The police get one thing back." PUNCHES in from below. 2.56: the needle and its box fade as the red square is CARRIED down the frame to the band (0.56 s, power2.inOut) and the wall drops to 24%. 3.18 (cue) the address TYPES ON in a 64 px mono band, the red square riding as the caret, 42 keys over 1.55 s. Corner metadata sits above the scrim throughout.
Sequential/interaction: the field drifts; one address is found; the typed address with the red-square caret.
Audio: a plate hit on the find; keys on the typing; a soft cut on the line swap.
Transition: hard cut on 5.28 → Beat 2.

### Beat 2 — The trace — 7.37 s (5.28–12.65)
World: the ledger as a dark field with four hop columns. Title top-left (serif 72 px): "Exchequer follows it outward, hop by hop." The red square is now the root node at far left (SNAPS to place). 5.5–6.4: four edges DRAW to hop-1 nodes, nodes POP (back.out); the heavy branch stays bright, three thin ones fade to 30% with a micro label "dust · dropped". 6.5–7.6: three edges draw on to hop 2; the comet (a small red square with a glow tail) RUNS root → hop 1 → hop 2. 8.44 (cue): the hop-2 node LOCKS IN green with a ring pulse and a chip "Binance 14 · published exchange wallet"; the title's second line lands: "…to the exchange it was cashed out through." 8.6–10.2: grey hops 3–4 keep drawing behind (the graph goes on), while three counters at bottom-right COUNT UP from 9.5: 129 addresses · 144 transfers · 53 API calls (chips stack). Caption bottom-left from 9.6: "Every attribution is an exact match against a published exchange wallet." Breathe to 12.65 with the red path pulsing.
Sequential/interaction: edges draw, nodes pop, comet runs, counters tick.
Audio: drops on the node pops, bell on the lock-in, chips under the counters.
Transition: hard cut on 12.65 → Beat 3.

### Beat 2b — The map — 4.74 s (12.65–17.39), inside beat 2
World: the same case, re-laid-out. A cursor comes in from the lower right, crosses to the **By hop | Bubbles** toggle the console actually has, and clicks it at 12.95. The hop columns and the chip fade; one proxy drives every node, every edge and a new seed ring from the hop layout into the bubble layout over 1.15 s, so the whole re-layout is a single seekable value. Role colour resolves as they settle — green labelled exchange, amber probable deposit, grey service — 30 more of the case's 129 addresses fade in around them, green halos appear behind the exchanges, and six labels arrive: Reported · Binance 14 · probable Gate.io deposit · probable Crypto.com deposit · Gate.io 1 · Crypto.com 5.
Then the interactivity, twice, exactly as the product behaves: the cursor hovers **Binance 14** — everything dims to 12% except that wallet, the wallet that paid it and the edge between, a ring lands on it and a tooltip gives the case's own numbers (Binance · 2 hops from seed · 3.236427 ETH · 2 transfers). Then it hovers the amber **probable Gate.io deposit** — the dim set changes to keep its two neighbours lit, and the card reads Received 20.869695 ETH, Sent 29.499002 ETH, which is exactly what Gate.io 1 receives one bubble along. The cursor leaves, the field comes back.
Every number, label and address in this beat is read from the stored case `75fa7f6e…889438`, not invented.
Audio: a tick on the click, a tick on each hover; the bed moves to an A-minor voicing while the figure keeps searching.
Transition: hard cut on 17.39 → Beat 3.

### Beat 3 — Screened — 4.21 s (12.65–16.86)
World: a departure board. Fourteen rows of addresses SCROLL upward in mono 30 px at 40% ink; a red scan bar SWEEPS down the column (12.8–14.0); at 14.22 (cue) one row SNAPS to full red with a stamp chip "OFAC-LISTED · SDGT" and the red square docks beside it. Headline right, serif 84 px: "Every hop is screened against the OFAC list." Micro facts under it: "SDN list · 4 September 2026 · 124 Ethereum · 282 Tron · 1 BSC".
Sequential/interaction: scan bar, row snap.
Audio: plate hit on the snap; a switch tick when the scan starts.
Transition: 0.5 s crossfade with scale (0.96 → 1) on 16.86 → Beat 4.

### Beat 4 — The handoff — 3.68 s (16.86–20.54)
World: the case file. Left: "Names the exchange, how sure, and the address to cite." (serif 84 px) with a sub-line "a report an investigator can attach to a legal request" (sans 30 px). Right: a paper card (760×540, #f5f4f0) SLIDES in from the right with a −3° → 0° settle: EXCHEQUER · REPORT · case 75fa7f6e; Finding Binance · 0.90 · 2 hops; Address to cite 0x28c6c6…f21d60; Traced 3.236427 ETH (the red square sits on this line — the money, counted); Evidence 53 provider responses, each hashed. At 19.49 (cue) a red SEALED stamp STAMPS on with a 8° rotation and the SHA-256 types under it.
Sequential/interaction: card slide, stamp.
Audio: card slide; wood stamp on the seal.
Transition: hard cut on 20.54 → Beat 5.

### Beat 5 — The stance — 3.69 s (20.54–24.23)
World: black, the grid, nothing else. "No model." SLAMS in at 20.54, "No clustering." at 21.59, "No proprietary score." at 22.65 — serif 120 px, left-anchored, each with a heavy impact; a red rule DRAWS under the third. From 23.2 a mono line: "Measured on 88 real wallets · 1,416 provider requests · the inconvenient result is in the README".
Sequential/interaction: three lines, two beats apart, then the rule.
Audio: heavy soft impacts × 3, tick on the rule.
Transition: continuous — the red square stays; on 24.23 the lines are PULLED out and the chequer assembles.

### Beat 6 — Exchequer — 3.97 s (24.23–28.20)
World: the counting cloth. Seven ink squares FLY in from seven directions (expo.out / back.out, 24.3–25.1) and lock around the red square, forming the mark at 168 px, rx 14. "Exchequer" (serif 120 px) SLIDES in beside it on 24.23; below at 25.2: "Traces cryptocurrency fraud from a reported wallet to the exchange it was cashed out through." (sans 32 px). Bottom band: "3 chains · 28 exchanges · 407 labels · 407 OFAC addresses" and "Smart India Hackathon 2026 · SIH26183 · Ministry of Home Affairs". Bell on the last square; music out 26.8–28.1; last frame holds.
Sequential/interaction: seven squares, wordmark, lines.
Audio: drops per square, bell on completion, bed fades.

## Motion pass (20 Sep)
Twelve behaviours added so no beat holds a still frame:
1. Beat 1 — a rule fills under the address as it is typed, at typing speed.
2. Beat 1 — the red caret blinks once the address is complete.
3. Beat 2 — marching dashes run the traced route after the lock-in: the funds are still moving.
4. Beat 2 — small squares travel the five branches the trace did **not** follow, so the network is alive while the red path stays the story.
5. Beat 3 — every ledger row brightens as the scan bar reaches it, then dims: checked, cleared.
6. Beat 3 — an "addresses screened" counter runs 0 → 129 as the bar descends.
7. Beat 4 — the report card floats on a slow 3D tilt, so it reads as paper rather than a rectangle.
8. Beat 4 — the SEALED stamp settles with a wobble after it lands.
9. Beat 5 — the red square steps down the list, one line at a time, as each lands.
10. Beat 5 — a fourth line, "But everything hand-checked.", arrives on the narration with a red tick that draws itself.
11. Beat 6 — the ledger's size counts itself up: 3 chains · 28 exchanges · 407 labels · 407 OFAC addresses.
12. Beat 6 — the red square keeps breathing under the finished mark to the last frame.

Layout notes from the pass: the ledger column widened to 990 px and the sanctions chip shortened to "OFAC · SDGT" so it clears the full designated address; "cleared" rows dim to 0.40 alpha, the floor that still passes WCAG at 30 px.

**Music mood for this video:** steady, present, cue-locked
**Audio summary:** keys → drops and a bell as the trace resolves → a plate hit on the sanctions snap → card and stamp → three slams → a bell as the chequer completes → silence.
