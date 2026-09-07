# TraceChain — demo addresses

Five Ethereum mainnet traces over four addresses. Traces 1-3 were verified on
4 September 2026, traces 4-5 on 7 September 2026; each was run **twice back to
back** and returned identical findings both times.

Traces 1-3 run at **depth 3** on **Ethereum / ETH** and complete in under 20
seconds. Traces 4-5 are reverse traces at **1 hop** and return in about two
seconds each, so the whole set can be run live.

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

## 4 — Reverse trace: who paid the offender

```
0x536c4921d1aafde6a5cda882fb5ca046f3601c65
```
Ethereum · ETH · **direction: who sent funds here** · 1 hop · **~2 seconds, 1 API call**

| | |
|---|---|
| Addresses that funded it | **10** |
| Total received | 195.6203 ETH |
| Largest single sender | 139.2700 ETH |
| Exchanges among the senders | none |

This is address 2 again, asked the other question. Forwards, it fans 617 ETH
across ten recipients and fires the laundering rules. Backwards, **ten separate
addresses paid money into it** — and none of them is a labelled exchange, so
none is explained away as a withdrawal.

Say the number out loud: one complaint, ten more addresses that paid the same
wallet. Each is a candidate victim who may hold a separate FIR, and the panel
is labelled *"Funded this address"* rather than *"victims"* on purpose — the
transactions establish that money moved, not who the sender was.

---

## 5 — Reverse trace: why it is labelled carefully

```
0x60d02e0956e2f3795167c15ba61ab452c85c2533
```
Ethereum · ETH · **direction: who sent funds here** · 1 hop · **~2 seconds**

| | |
|---|---|
| Addresses that funded it | 9 |
| **Of which labelled exchanges** | **6** — five Binance, one OKX |
| Candidate victims | 3 |

The demo for the honesty of the tool. Nine addresses funded this wallet, but
six of them are exchange hot wallets, and the panel marks each one
**"withdrawal, not a victim"** in the row itself. A tool that reported "9
victims" here would be wrong by a factor of three, and it would be wrong in the
direction that inflates a case.

Run this straight after 4. The contrast is the argument: the same feature, on
one address producing ten leads and on another quietly discarding six false
ones.

---

## Running order

Trace 1, then 2, then 3. The story escalates: nothing found → something odd but
inconclusive → money located at an exchange with two independent patterns.

Set the depth selector to **3 hops**. Two hops is faster but none of the
patterns fire there; four hops takes about three minutes and adds nothing to
the argument.

Then switch the first selector to **"Who sent funds here"** and run 4 and 5 at
**1 hop**. Both return in about two seconds on a single API call, so they cost
almost no stage time, and they change the scale of the claim: the first three
traces follow one victim's money, while 4 finds ten more people who paid the
same wallet and 5 shows the tool refusing to overcount them.

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

If asked about sanctions screening: every address in every trace is checked
against the OFAC SDN list published 4 September 2026 — 124 Ethereum, 282 Tron
and 1 BSC address. None of the demo addresses is listed, and that is worth
saying plainly. `GET /risk-labels` shows exactly what the screening covers, so
"no hit" can always be told apart from "not screened".

The mixer category is empty, and there is a good answer if it comes up: every
mixer currently on the SDN list is a Bitcoin service, and Tornado Cash was
delisted in March 2025. The stop-at-a-mixer rule is built and tested; the list
simply has nothing on our three chains today.
