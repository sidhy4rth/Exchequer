# Exchequer — project timeline, from idea to execution

**Smart India Hackathon 2026 · problem statement SIH26183 · Ministry of Home Affairs · Team WiFiBandits**

> **Designed version:** [eight illustrated pages](timeline-design/README.md) · [PDF](Exchequer-Project-Timeline.pdf)

A victim reports one wallet address. Exchequer follows the money hop by hop, screens
every address it passes against sanctions lists, freezes, mixers and known theft,
names the exchange where the funds were cashed out — down to the customer deposit
address where it can — and drafts the letter an officer sends to that exchange.
Every conclusion is an exact match against a published list or a stated arithmetic
rule, so a human can re-check it by hand.

This document records how it got there. Dates come from the git history (77
commits, local time) and the project's own notes, briefs and deliverables. Where a
date is not recorded anywhere, the document says so rather than guessing.

---

## The project in numbers, over time

| | 4 Sep<br>one-pager | 5 Sep<br>first commit | 15 Sep<br>research session | 18 Sep<br>pre-round | 24 Sep<br>now |
|---|---:|---:|---:|---:|---:|
| Name | TraceChain | TraceChain | TraceChain | Exchequer | Exchequer |
| Chains traced | 1 (Ethereum) | 3 | 3 | 3 | 3 |
| Exchange addresses labelled | 337 | 374 | 407 | 407 | **25,117** |
| — customer deposit addresses | 0 | 0 | 0 | 0 | **24,018** |
| Sanctioned addresses screened | 0 | 0 | 407 (OFAC) | 407 (OFAC) | **1,061** (6 governments) |
| Tether-frozen, mixer, hack & scam addresses | 0 | 0 | 0 | 0 | **18,386** |
| All labelled addresses | 337 | ~374 | ~840 | ~840 | **44,588** |
| Tests | — | 0 | 140 → 172 | 234 | **273** |
| Hosted | no | no | no | Railway (paused that day) | Railway, live |

---

## Phase 0 · The idea — up to 4 September

- **The problem.** SIH26183, set by the Ministry of Home Affairs: cryptocurrency
  fraud against Indian victims, where the police have a victim's wallet address and
  need to know where the money went and whom to ask about it.
- **The stance, decided before any code was kept.** No model, no clustering, no
  proprietary score. A conclusion that reaches a courtroom must be one an officer can
  re-check by hand: attribution is an exact match against a published wallet list,
  and every laundering finding is arithmetic that prints the thresholds it applied.
- **4 September — the TraceChain one-pager** (`TraceChain-Overview.pdf`, 3 pages).
  Ethereum only. 337 verified exchange wallets across 18 exchanges, 4 hops by
  default, a confidence score from three weighted factors (hop proximity 40%, amount
  correlation 35%, match directness 25%), peel-chain and amount-split rules, a bubble
  map, JSON and text export. First live result: a reported address traced to
  **Binance 14 in 2 hops, confidence 0.80**, 138 addresses mapped.

## Phase 1 · The foundation — 5 to 7 September

**5 Sep · `c07156d` — the first commit.** Three chains from day one, because
Etherscan's free tier serves Ethereum mainnet only: a provider seam with Etherscan
(Ethereum), NodeReal (BNB Smart Chain) and TronGrid (Tron). One asset per trace
(native coin, USDT or USDC), because amounts in different assets cannot be compared
or scored. 374 exchange wallets, each verified on chain; token contracts and DEX
routers carrying an exchange's name removed. FastAPI backend, React/Vite frontend,
one Docker image serving both.

**7 Sep — the second core capability set.**
- `19f495e` A test suite for the attribution and detection rules, written two-sided:
  every rule is tested for firing on its shape *and* for staying silent on ordinary
  activity.
- `5e1ad0b`, `7eb5129` **Reverse tracing** ("who paid this wallet?" — on a scammer's
  wallet, the payers are candidate victims) and **sanctions/mixer screening**, with a
  rule that a trace *stops* at a mixer.
- `9d462ee` **407 sanctioned addresses imported from OFAC's live SDN list** (124
  Ethereum, 282 Tron, 1 BSC). The mixer list came back empty — Tornado Cash had been
  delisted in March 2025 — and that was documented as the correct answer.
- `7ad93a9` Verified reverse-trace demos; `f9e1084` each depth level fetched
  concurrently.

## Phase 2 · The internal judging round — between 7 and 15 September

The exact date is not recorded in the repository. What is recorded (in the
15 September session brief) is the question the judges asked:

> *"Since you pointed out money laundering, have you done any research to support
> your claims?"*

The team did not have a good answer. The README asserted that most laundering moves
as stablecoins, that USDT on Tron is the dominant rail for Indian scam proceeds, and
that its thresholds were the right ones — and cited nothing. The next round has the
same judges, and they would check. That question set the agenda for the next phase.

## Phase 3 · Research, correctness and measurement — 15 September

One long session driven by a written brief with a fixed budget and ordered phases.
Twenty-five commits between 19:03 and 23:30.

- **Adversarial review first** (`4b097b8`). The one real correctness bug: the trace
  had no notion of time and followed transfers a wallet made *before* the victim's
  money arrived — reporting money that was never the victim's. Fixed with the
  **time rule** (only transfers at or after arrival are followed), tested, documented.
  Four smaller fixes and seven documented limitations.
- **RESEARCH.md** (`e464f71`). Every laundering claim listed with the source actually
  read, the exact passage and a verdict. Two claims were overstated and rewritten —
  the India-specific "dominant rail" sentence (no source measures India) and the word
  "structuring" (a statutory term). Indian legal framework: PMLA s.12 and s.50.
- **Validation on real wallets** (`291bc7d`). 40 documented-illicit and 48 ordinary
  wallets, 1,416 requests snapshotted for offline reproduction, a 68-point threshold
  sweep. The inconvenient result was published: the old amount-split defaults flagged
  **40%** of ordinary wallets; the new ones 11%; and no threshold separates the two
  groups — so a pattern is a reason to look closer, never a score.
- **Deposit-address inference** (`9e0ab5b`): an unlabelled wallet whose every outflow
  sweeps to one exchange wallet is named as that exchange's *probable* deposit
  address — the address a request must name — scored lower than a label match.
- **Swaps at DEX routers** (`0cb5633`): 20 Ethereum and 4 BSC routers; a swap's
  receipt is read so the trace says what the money became.
- **Tron coverage** (`e830168`): 7 labels / 4 exchanges → **40 / 18**, read from
  TronScan's own tags and checked on chain. No Indian exchange tagged; stated.
- **Cross-case correlation** (`2954ea4`): stored cases whose money converges on the
  same wallets. Three phishing wallets found to share 61 intermediaries.
- **Internal transactions** (`43aaff5`), **the officer's report** (`5622cd2`), a fifth
  traversal brake for service contracts (`b99b688`), a second adversarial pass fixing
  four ways to name money falsely (`05ea20b`).
- **Evidence integrity** (`25c01c0`): every provider response hashed on arrival; the
  report sealed with a content hash.
- **UI revamp** (`3c29a27` → `c1e537e`): the results view as a case file that answers
  the officer's questions in order; the home page as a case board; a dark console
  skin.
- **JUDGE_QA.md** (`daf1741`): fifteen prepared answers. Tests: 140 → 172.

## Phase 4 · Becoming Exchequer, and going online — 16 September

- **00:15 · `bdf5f01` — renamed Exchequer**, because a rival SIH26183 team ships as
  "TraceChain". The Exchequer was named for the chequered cloth on which the Crown's
  money was counted.
- **Hosting** (`bf495e4`, `2f77778`): Railway, one Docker image, a `/data` volume, a
  seed script. Officer sign-in added (`6fdf018`) and then **removed at the user's
  request** (`35521df`); chain of custody rests on evidence hashing instead.
- A finished trace opens as its stored case (`f4ab7a5`); provider responses kept on
  disk and the demos traced at startup, so they answer instantly (`7152740`) —
  flagship 43 s cold → 0.12 s.
- **CI** on every push, badge in the README (`3a16357`, `ae4cab7`).
- "Answer first, evidence on demand" declutter (`c813f1f`); the traced funds drawn in
  red with a light running the chain (`8db059b` → `3e7924a`); zoom, pan and fit
  (`ffecb3b`).
- **Letting a judge pick a live address** (`d5e6cab`) from Etherscan's Phish/Hack
  list, with a scout script; an optional **"Stop after 1:30"** time budget
  (`c5e289d`).

## Phase 5 · The mark, the room and robustness — 17 September

- `1bde564` A sign-in page over a transaction lattice; `90c73fd` **the chequer mark**
  (one square red — the sum being traced) and a sign-in page drawn over the *real*
  ledger of addresses the tool knows.
- `59788b8`, `204849f` **Present mode**: any case as four projector screens.
- `b3a18c3`, `4409aea` Tron and BSC pagination bounded by records *read*, not kept —
  a busy wallet had paged its whole history for minutes on the hosted demo.
- The hosted instance was brought up for a friend. **234 tests**; CI green.

## Phase 6 · Documents and the launch film — 18 to 20 September

- **18 Sep** — hosting taken down; state frozen at `4409aea`.
- **19 Sep** — hosting brought back up for an evening demo. `docs/`: the
  **Director proposal** (5 pages, a support request) and the **Research Report**
  (12 pages plus RESEARCH.md as an 18-page appendix), generated by
  `docs/make_pdfs.py`.
- **19–20 Sep — the launch video**, three cuts built with Hyperframes: v1 (23 s,
  screenshots — rejected as bland), v2 (37.9 s, "one red square"), **v3 (43.2 s,
  seven beats, the latest)**: drawn SVG and type only, narrated by the Kokoro "Emma"
  voice, with a bespoke score and the user's own closing line — *"No model, no
  clustering, no proprietary score. But everything hand-checked. That's Exchequer
  for you in a nutshell."*

## Phase 7 · From 407 labels to 44,588 — 22 to 23 September

**22 Sep — housekeeping.** A Codex copy of the repo was reviewed (its Python
environment still pointed at the original and it pushed to the same `main`), then
retired to the Trash at the user's request.

| Time | Commit | What |
|---|---|---|
| 23 Sep 00:05 | `2dda364` | Ethereum exchange labels **337 → 1,020** (92 exchanges, incl. CoinDCX, Delta Exchange) from a newer scrape of Etherscan's tags, each verified on chain; OFAC refreshed to 18 Sep (Tron 282 → 334, Xinbi Guarantee). |
| 00:12 | `3053ab5` | New **stolen-funds** category (WazirX, Bybit, BingX, Ronin exploiters…) and **mixer pools** rebuilt from Etherscan tags (Tornado Cash, Typhoon, Privacy Pools). |
| 00:24 | `f825542` | **Five more governments**: UK and EU lists read directly; Israel NBCTF, Japan MOF, France DG Trésor via OpenSanctions. Lifted seizure orders excluded. Sanctioned Tron 334 → 915. → *deployed* |
| 00:40 | `966ffec` | All demos re-verified cold; four changed and each change explained (demo 3 now reaches Uphold; the flagship a probable Bitget deposit address). → *deployed* |
| 03:21 | `53740c1` | **8,600 reported phishing and scam wallets** (ScamSniffer; Etherscan Phish/Hack via two mirrors); 1,604 never-used left out. |
| 05:25 | `8803efb` | **19,027 Bitget customer deposit addresses**, every one checked on chain. → *deployed* |
| 06:55 | `1971e33` | **README rewritten** (logo banner, badges, screenshots, sources and licences); RESEARCH.md "Where the label data comes from"; JUDGE_QA updated. |
| 07:06 | `318426a` | **Tether's USDT freeze list**, replayed from the USDT contracts' own events and spot-checked against `isBlackListed()`; demo 11 (a Tron wallet frozen 11 Sep → Binance-Hot 7). |
| 07:13 | `2dcdec1` | **Follow the money through a swap**: a swap into USDT/USDC is traced onward from the swap, as its own linked trace. Verified on a real Uniswap swap. |
| 08:05 | `073b1c6` | **Draft request letters** to the exchange and to Tether, filled from the case; legal provision and signature left for the officer. |
| 08:09 | `68ba2af` | **4,991 Binance customer deposit addresses.** → *all four deployed together* |

Problems met and handled along the way: EigenLayer operator tags mislabelled as
exchanges (filtered before commit); a verified Tron wallet dropped by a re-scan
(restored); an exchange count first reported as 106 and corrected to 92; a Tornado
pool that Tether froze losing its mixer label (fixed — a mixer label always wins);
a network drop mid-import while travelling (resumed from the checkpoint, nothing
lost).

## Phase 8 · Bug hunt — 23 to 24 September

**`0b46c4e` · 08:26** — *committed locally, not yet pushed or deployed.*

Method: `ruff` over backend, scripts and tests; every endpoint run on 15 real cases
including the error paths; every page walked in headless Brave with console and
network errors captured (zero JavaScript errors).

1. **A false "Frozen by Tether" finding.** Tether's blacklist includes the zero
   address and 24 other system addresses where tokens are burned. A USDC burn in a
   follow-on trace was flagged as a freeze and offered a Tether letter about the zero
   address. Fixed in the importer and the matcher (Ethereum 2,763, Tron 7,589 frozen).
2. **"Stop after 1:30" did not bound follow-ons** — each got a fresh budget. They now
   share what is left.

Also: unused imports removed; two database backups swept into the commit by mistake
were taken out before anything was pushed.

---

## What exists now

- **Tracing:** Ethereum, BNB Smart Chain, Tron; ETH/BNB/TRX, USDT, USDC; forward and
  reverse; the time rule; six traversal brakes; swaps detected and, into
  stablecoins, followed.
- **Attribution:** 25,117 exchange addresses across 92 exchanges, including 24,018
  customer deposit addresses; probable deposit addresses inferred and scored lower.
- **Screening:** six governments' sanctions and seizure lists; Tether's USDT freezes;
  mixer pools (the trace stops); hack, phishing and scam wallets.
- **Findings:** peel chain and amount split, measured on 88 real wallets, never
  scored; cross-case correlation.
- **Outputs:** a case view, Present mode, a sealed text report with an evidence
  manifest, and draft request letters.
- **Evidence:** RESEARCH.md sources every claim and every data source; DEMO.md holds
  eleven verified traces; JUDGE_QA.md fifteen answers; 273 tests; CI on every push.
- **Deliverables outside the code:** the TraceChain one-pager, the Director proposal
  and Research Report PDFs, the 43-second launch film.

## Open items

1. Push and deploy `0b46c4e` (the live site still has the zero-address false positive).
2. Licences before any commercial use: OpenSanctions data is CC BY-NC 4.0; the
   ScamSniffer-derived entries carry GPL-3.0.
3. Demo running order: skip trace 2, use trace 11 for "why Tron?".
4. Draft letters: the legal provision is left blank for an officer to confirm.
5. Still undone: live TronScan tag lookup during Tron traces; internal transactions
   on BSC and Tron; Bitcoin; a PDF report renderer.
6. Outside the code: SIH registration as Exchequer; the slide deck in Downloads still
   says TraceChain; the launch film's 25-second social cut; the proposal PDFs and the
   three film cuts are not committed; `railway down` when demos are over.
