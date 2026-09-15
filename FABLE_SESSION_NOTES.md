# Session notes — 15 September 2026

## What was done

- **Phase 0, adversarial review.** One real correctness bug: the traversal had no notion of time and followed a wallet's transfers made *before* the victim's money arrived. Fixed (only transfers at or after arrival are followed; mirrored for reverse traces), tested, documented. Four smaller fixes: deep fetch failures now mark the trace truncated; the report no longer claims "token transfers are not covered" on a USDT trace; the scored path is the shortest path that could have carried the most value rather than networkx's arbitrary pick; peel-chain findings come out in a fixed order. Seven limitations added to the README (fan-out evasion, 200-transfer cap, "single-use" means within the trace, no time window on the split rule, correlation capped at 100%, seed not windowed).
- **Phase 1a, RESEARCH.md.** Every laundering claim listed with the source read, the exact passage and a verdict. Two claims were overstated and were rewritten: "dominant cash-out rail for Indian scam proceeds" (no source measures India) and "structuring" (a statutory currency term). Thresholds are now stated to be the project's own. Indian legal framework section: PMLA s.12 and s.50, the 7 March 2023 notification, FIU-IND registration.
- **Phase 1b, validation.** 40 documented-illicit and 48 ordinary wallets, all fetched by script and bytecode-checked, traced with the real pipeline; 1,416 requests snapshotted so the run is offline and reproducible. 68-point threshold sweep.
- **Phase 2, deposit-address inference.** Unlabelled wallet whose entire outgoing history is ≥2 sweeps to one labelled exchange wallet → "probable E deposit address", scored lower (directness 0.5), evidence attached, confirmation sentence in the report, sidebar qualifier.
- **Phase 3.** JUDGE_QA.md, DEMO.md re-verified, this file.
- **Phase 4, swaps at DEX routers.** 20 Ethereum and 4 BSC routers imported by script and bytecode-verified; a transfer into one stops the trace, the receipt is read, and the edge carries `swap{router, asset_in, amount_in, asset_out, amount_out, tx}`. The response and report say what the money became and where to re-run. Detection only — the trace is not resumed on the output asset, because amount correlation across two assets has no defensible definition yet. Verified on a real 2,000 ETH → wstETH swap.
- **Phase 5, Tron labels.** The seeder now pages TronScan's largest USDT-TRC20 holders and TRX accounts, keeps only tags naming a known exchange, and verifies each on chain (no bytecode, inbound value > 0): 7 labels / 4 exchanges → **40 / 18**, 0 rejected. No Indian exchange is tagged by TronScan among the 900 largest accounts; stated in the README. Verified end to end on a live USDT-TRC20 trace to Binance-Hot 7.
- **Phase 6, cross-case correlation.** `GET /cases/correlate`: unlabelled intermediaries (and inferred deposit addresses) reached by two or more different reported addresses, same chain, with cases, depths and values; a *Related cases* panel in the trace view. Three phishing-labelled wallets were found to share 61 intermediaries. Caveat documented: unlabelled public contracts (the Beacon Deposit Contract) show up as shared intermediaries because no label file knows them.
- **Phase 7, internal transactions.** Etherscan `txlistinternal` merged into the same `Transaction` shape, tagged `internal`, on by default (`ETHERSCAN_INCLUDE_INTERNAL`). Two requests per expanded native address instead of one. Demo 3 gained 203 contract-moved transfers and 21 addresses; others unchanged. A first version capped the merged list at 200 and shrank a busy demo from 31 to 6 addresses — caught by measuring, fixed, and pinned by a test.
- **Phase 8, the investigator's report.** Report format v2: header with `git describe` version, one-paragraph plain summary, the finding with its basis (label match or inference), the path hop by hop with amounts, times and hashes, patterns with thresholds, inferred addresses with evidence and confirmation sentence, limitations, and an appendix of every address and transaction. Every individual transfer is now stored with the case for that appendix; older cases render with a note instead of failing. No PDF: nothing in the dependency set renders one and the text report is the deliverable.

- **Follow-up 1, the flagship regression.** Reading internal transactions made the README's flagship address expand WETH and nine pools — contracts with no signed outflow paying out to dozens of addresses — and cost 249 requests / 127 s at 4 hops instead of 41 / 22 s. Two fixes: a fifth brake (a contract paying out to more than 3 distinct addresses is a service and is not expanded), and `txlistinternal` is now requested on a forward trace only for addresses with no signed outflow, since a signing wallet cannot originate an internal transfer. Result: 73 requests / 38.5 s, Binance at 0.90. Every demo re-measured cold; numbers in DEMO.md.
- **Follow-up 2, second adversarial pass on this session's additions.** Four ways to name money or an exchange falsely, each fixed with a test: a refund of the traced token read as a swap output; a pool's internal payout to a router described as the pool's swap; the inference sentence saying "every transfer" when only the newest 200 were read; and a wallet paying into an exchange's *contract* wallet (a deposit forwarder) qualifying as a sweep. One limitation documented rather than fixed: the time rule resolves to the block timestamp, so a transfer earlier in the same block as the arrival is admitted.

- **Follow-up 3, Related cases in the demo.** The panel showed "100 related cases" with the Beacon Chain deposit contract on top. Cause: my measurement and seeding scripts called the trace endpoint and stored ~50 cases beside the demo ones (`validate_patterns.py` itself never stores). Fixed three ways: the store was pruned to the DEMO.md traces with a backup (`scripts/prune_cases.py`, refuses to delete everything); correlation now excludes service contracts and anything in the exchange or router label files, even for cases stored before the graph carried those flags; and the panel groups by *related case*, each listing the wallets shared, probable deposit addresses first.

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

- Swap *resumption* on the output asset (Phase 4 ships detection only). Internal transactions remain invisible on BSC, Tron and every token trace. No PDF renderer.
- Swaps whose output is the native coin, or whose transfer lands on a liquidity pool rather than a router, are not recognised; PancakeSwap and SunSwap routers have no scripted label source in the pinned dataset.
- No Tron or BSC validation: no scripted source of Tron *controls* with provenance was found, and the brief forbids hand-typed addresses.
- FATF's own documents could not be fetched (HTTP 403); they are cited through a labelled secondary source.

## Three things to say to the judge who asked the research question

1. "Every claim in the README now has a source you can open, and where the source said less than we did, we changed the README, not the source — the 'dominant rail for India' sentence is gone because nobody has measured it."
2. "We measured our own rules on 88 real wallets and published the inconvenient result: the shapes we look for appear near ordinary high-volume wallets too, so a pattern is a reason to look closer and the tool has never scored it as more. What the tool establishes with confidence is the exact-match attribution to an exchange, and now the probable deposit address the request should name."
3. "The one thing an evidentiary tool must not do is report money that was never the victim's, and we found our tool could — by following transfers made before the funds arrived. That is fixed, tested, and written down."
