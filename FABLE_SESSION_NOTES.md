# Session notes — 15 September 2026

## What was done

- **Phase 0, adversarial review.** One real correctness bug: the traversal had no notion of time and followed a wallet's transfers made *before* the victim's money arrived. Fixed (only transfers at or after arrival are followed; mirrored for reverse traces), tested, documented. Four smaller fixes: deep fetch failures now mark the trace truncated; the report no longer claims "token transfers are not covered" on a USDT trace; the scored path is the shortest path that could have carried the most value rather than networkx's arbitrary pick; peel-chain findings come out in a fixed order. Seven limitations added to the README (fan-out evasion, 200-transfer cap, "single-use" means within the trace, no time window on the split rule, correlation capped at 100%, seed not windowed).
- **Phase 1a, RESEARCH.md.** Every laundering claim listed with the source read, the exact passage and a verdict. Two claims were overstated and were rewritten: "dominant cash-out rail for Indian scam proceeds" (no source measures India) and "structuring" (a statutory currency term). Thresholds are now stated to be the project's own. Indian legal framework section: PMLA s.12 and s.50, the 7 March 2023 notification, FIU-IND registration.
- **Phase 1b, validation.** 40 documented-illicit and 48 ordinary wallets, all fetched by script and bytecode-checked, traced with the real pipeline; 1,416 requests snapshotted so the run is offline and reproducible. 68-point threshold sweep.
- **Phase 2, deposit-address inference.** Unlabelled wallet whose entire outgoing history is ≥2 sweeps to one labelled exchange wallet → "probable E deposit address", scored lower (directness 0.5), evidence attached, confirmation sentence in the report, sidebar qualifier.
- **Phase 3.** JUDGE_QA.md, DEMO.md re-verified, this file.
- **Phase 4, swaps at DEX routers.** 20 Ethereum and 4 BSC routers imported by script and bytecode-verified; a transfer into one stops the trace, the receipt is read, and the edge carries `swap{router, asset_in, amount_in, asset_out, amount_out, tx}`. The response and report say what the money became and where to re-run. Detection only — the trace is not resumed on the output asset, because amount correlation across two assets has no defensible definition yet. Verified on a real 2,000 ETH → wstETH swap.

## What was measured

| | positives (32 active) | controls (47 active) |
|---|---|---|
| Amount split, old defaults | 12 | 19 (40%) |
| Amount split, new defaults (4 recipients, 90–102%, 60% cap) | 6 | 5 (11%) |
| Peel chain, defaults | 2 | 2 (both mining-pool payouts) |
| Deposit inference on the seed | — | 0 of 48 |

## What was found to be wrong

- Following pre-arrival transfers (fixed).
- A stale caveat that was false on every stablecoin report (fixed).
- The README's India-specific "dominant rail" claim and the word "structuring" (rewritten).
- The amount-split defaults flagged 40% of ordinary high-volume wallets (changed; and stated plainly that no threshold separates the corpora).

## Left undone, and why

- Swap *resumption* on the output asset (Phase 4 ships detection only). Phases 5–8 (Tron label coverage, cross-case correlation, internal transactions, investigator's report) were ordered after the mandatory Q&A; see NOTES.md for what, if anything, was started.
- Swaps whose output is the native coin, or whose transfer lands on a liquidity pool rather than a router, are not recognised; PancakeSwap and SunSwap routers have no scripted label source in the pinned dataset.
- No Tron or BSC validation: no scripted source of Tron *controls* with provenance was found, and the brief forbids hand-typed addresses.
- FATF's own documents could not be fetched (HTTP 403); they are cited through a labelled secondary source.

## Three things to say to the judge who asked the research question

1. "Every claim in the README now has a source you can open, and where the source said less than we did, we changed the README, not the source — the 'dominant rail for India' sentence is gone because nobody has measured it."
2. "We measured our own rules on 88 real wallets and published the inconvenient result: the shapes we look for appear near ordinary high-volume wallets too, so a pattern is a reason to look closer and the tool has never scored it as more. What the tool establishes with confidence is the exact-match attribution to an exchange, and now the probable deposit address the request should name."
3. "The one thing an evidentiary tool must not do is report money that was never the victim's, and we found our tool could — by following transfers made before the funds arrived. That is fixed, tested, and written down."
