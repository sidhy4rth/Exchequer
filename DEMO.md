# TraceChain — demo addresses

Three Ethereum mainnet addresses, verified on 4 September 2026. Each was traced
**twice back to back** and returned identical findings both times.

All three run at **depth 3** on **Ethereum / ETH** and complete in under 20
seconds, so they can be traced live.

---

## What these labels mean

TraceChain establishes two things and no more:

1. whether funds reached a wallet published in an exchange label file, and
2. whether the transfers matched fixed arithmetic thresholds.

It does **not** establish that anyone committed a crime. An amount split means
funds were fanned across many recipients — launderers do that, and so do
exchanges, payment processors and market makers. Describe these as *findings*,
not verdicts. That is also the strongest position to argue from: every number
below is re-checkable by hand from public transaction data.

---

## 1 — No cash-out found

```
0x7c3e9bab6715e4040f013e865b193b0209642e36
```
Ethereum · ETH · 3 hops · **~4 seconds**

| | |
|---|---|
| Addresses traced | 12 |
| Exchange | none matched |
| Confidence | not applicable — nothing attributed |
| Patterns | none |

The funds were followed for three hops and never reached a labelled exchange,
and no laundering rule matched. Note what the tool does here: the confidence
panel reads **"Not applicable — no exchange attributed"** rather than 0%.
Finding nothing is a legitimate result, not a failure, and the tool refuses to
score an attribution it did not make.

---

## 2 — A pattern fired, but no cash-out

```
0xbc1ada2e98dd0087cf4cc0c8bd0e6276c82fadc9
```
Ethereum · ETH · 3 hops · **~5 seconds**

| | |
|---|---|
| Addresses traced | 30 |
| Exchange | none matched |
| Confidence | not applicable |
| Patterns | **amount split** |

This is the ambiguous case, and the most honest one to show. The wallet fanned
its balance across multiple recipients — the shape structuring produces — but
the money did not reach any exchange in the label file within three hops. That
is a reason to look closer, not a conclusion. The rail prints the exact
thresholds the rule applied, so a reviewer can decide for themselves.

---

## 3 — Attributed cash-out, two patterns

```
0x536c4921d1aafde6a5cda882fb5ca046f3601c65
```
Ethereum · ETH · 3 hops · **~16 seconds**

| | |
|---|---|
| Addresses traced | ~90 |
| Exchange | **Binance** |
| Confidence | **0.65** |
| Patterns | **amount split** + **peel chain** |

The strongest case in the set: funds reach a published Binance wallet, and
**both** laundering rules fire independently along the route. Switch to the
Graph view — the amber fan-out and the green attributed path are visible in one
frame.

Note the confidence is 0.65, not 1.00. The route is longer and more diluted, so
the score is lower, and the tool says so rather than overstating.

---

## Running order

Trace 1, then 2, then 3. The story escalates: nothing found → something odd but
inconclusive → money located at an exchange with two independent patterns.

Set the depth selector to **3 hops**. Two hops is faster but none of the
patterns fire there; four hops takes about three minutes and adds nothing to
the argument.

---

## If a live trace disappoints

Pattern findings are threshold comparisons against a graph that reshapes as new
transactions arrive. These three were stable when verified, but a wallet that
fires today may not fire next week — this is a property of the method, not a
defect, and it is worth saying out loud if asked.

Every trace is stored as a case, so a known-good result can be opened instantly
and will look identical every time:

```
http://localhost:5173/case/4db62a96-588b-4db0-b220-f99b3c5fc0a3
```

Binance attribution at 0.90 confidence with an amount split, archived from
earlier today. Use it as a fallback, or as the closing argument for why cases
are preserved: **evidence has to be kept as it stood when it was taken.**

---

## Before presenting

```bash
cd ~/tracechain/backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000
cd ~/tracechain/frontend && npm run dev
```

Open <http://localhost:5173> — use `localhost`, not `127.0.0.1`.
Check the status line reads **3 chains** before you start.
