# Exchequer — demo addresses

Ten traces, all re-verified **cold** (empty cache) on **15 September 2026**
after the time rule, the new amount-split thresholds, internal transactions
and the service-contract brake landed. Every request count and time below is
from that run. Traces 1–3, 6–7 and 10 run at **depth 3** on **Ethereum / ETH**
and complete in 4–20 seconds; traces 4–5 are reverse traces at **1 hop** and
return in two seconds on two requests each. The README's flagship address at
**4 hops** takes ~40 seconds and 73 requests.

---

## What these labels mean

Exchequer establishes two things and no more:

1. whether funds reached a wallet published in an exchange label file (or a
   wallet inferred, with evidence, to be that exchange's deposit address), and
2. whether the transfers matched fixed arithmetic thresholds.

It does **not** establish that anyone committed a crime. An amount split means
funds were fanned across many recipients — launderers do that, and so do
exchanges, payment processors and market makers; the README's validation
section measured it firing on 11% of ordinary high-volume wallets. Describe
these as *findings*, not verdicts. That is also the strongest position to
argue from: every number below is re-checkable by hand from public
transaction data.

---

## 1 — No cash-out found

```
0x7c3e9bab6715e4040f013e865b193b0209642e36
```
Ethereum · ETH · 3 hops · **~4 seconds, 6 API calls**

| | |
|---|---|
| Addresses traced | 7 |
| Exchange | none matched |
| Confidence | not applicable — nothing attributed |
| Patterns | none |
| Transfers excluded by the time rule | 18 |

The funds were followed for three hops and never reached a labelled exchange,
and no laundering rule matched. Note what the tool does here: the confidence
panel reads **"Not applicable — no exchange attributed"** rather than 0%.
Finding nothing is a legitimate result, not a failure. The graph is smaller
than it was a week ago (12 addresses then) because 18 transfers the
intermediate wallets made *before* the traced funds arrived are no longer
followed — see trace 3 for why that matters.

---

## 2 — A pattern fired, but no cash-out

```
0xbc1ada2e98dd0087cf4cc0c8bd0e6276c82fadc9
```
Ethereum · ETH · 3 hops · **~7 seconds, 12 API calls**

| | |
|---|---|
| Addresses traced | 31 |
| Exchange | none matched |
| Confidence | not applicable |
| Patterns | **amount split** |

The ambiguous case, and the most honest one to show. A wallet downstream
fanned what it received across four or more recipients, passing 90–102% of it
straight through — the shape structuring produces — but the money did not
reach any exchange in the label file within three hops. That is a reason to
look closer, not a conclusion. The rail prints the exact thresholds the rule
applied, so a reviewer can decide for themselves. This finding survived the
tightened thresholds; the old ones would have fired on 40% of ordinary
wallets.

---

## 3 — The demo that changed, and why that is the best thing to show

```
0x536c4921d1aafde6a5cda882fb5ca046f3601c65
```
Ethereum · ETH · 3 hops · **~20 seconds, 35 API calls**

| | |
|---|---|
| Addresses traced | 56 |
| Exchange | **none matched** (a week ago: Binance at 0.65) |
| Patterns | **peel chain** |
| Transfers excluded by the time rule | **643** |
| Service contracts recognised and not expanded | 1 |

On 4 September this trace reached Binance with confidence 0.65 and both
patterns fired. On 15 September, with the time rule in place, it reaches no
exchange. The only change to the traversal is that a wallet's transfers made
*before* the traced funds arrived there are no longer followed, and this graph
left out 393 of them. The earlier Binance attribution was reached through
transfers of that kind — money that was never the reported wallet's.

Say this out loud. A tool that reports where the victim's money went has to
be able to lose an attribution when the evidence does not support it, and
this one did. The peel-chain finding remains: single-use wallets forwarding
declining amounts in sequence. One contract in the graph pays out to many
addresses and is marked as a service rather than expanded — the fix that
brought the flagship demo back from four minutes to forty seconds. Switch to
the Graph view for the fan-out from the reported address — 617 ETH across ten
recipients.

---

## 4 — Reverse trace: who paid the offender

```
0x536c4921d1aafde6a5cda882fb5ca046f3601c65
```
Ethereum · ETH · **direction: who sent funds here** · 1 hop · **~2 seconds, 2 API calls**

| | |
|---|---|
| Addresses that funded it | **10** |
| Total received | 248.2094 ETH |
| Largest single sender | 197.7415 ETH |
| Exchanges among the senders | none |

Trace 3 asked the other question. **Ten separate addresses paid money into
it** — and none of them is a labelled exchange, so none is explained away as
a withdrawal. (The totals grew since 7 September because the wallet has kept
receiving; the sender count did not.)

One complaint, ten more addresses that paid the same wallet. Each is a
candidate victim who may hold a separate FIR, and the panel is labelled
*"Funded this address"* rather than *"victims"* on purpose — the transactions
establish that money moved, not who the sender was.

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
| Source exchange | Binance, confidence 1.00 |

Nine addresses funded this wallet, but six of them are exchange hot wallets,
and the panel marks each one **"withdrawal, not a victim"** in the row itself.
A tool that reported "9 victims" here would be wrong by a factor of three, in
the direction that inflates a case. Run this straight after 4.

---

## 6 — New: the deposit address a request has to name

```
0x00000000072d54638c2c2a3da3f715360269eea1
```
Ethereum · ETH · 3 hops · **~13 seconds, 24 API calls**

| | |
|---|---|
| Addresses traced | 32 |
| Attribution | **Binance — probable deposit address (inferred)** `0xd1565e8f…7aa20`, 1 hop |
| Confidence | **0.875** (hop 1.0 · amount 1.0 · directness **0.5**) |
| Evidence | 2 outgoing transfers, 100% of them to **Binance 14**, 2.3201 ETH swept, current balance 0.0183 ETH |
| Also in `matches` | Binance 14 itself, exact label, 2 hops |
| Patterns | amount split |

The reported address carries Etherscan's *Phish / Hack* label. Its funds went
to an unlabelled wallet whose entire outgoing history is two sweeps into
Binance's labelled hot wallet and nothing else — the shape an exchange
produces when it sweeps a customer's deposits. The sidebar reads *"Probable
Binance deposit address (inferred — see evidence)"* and the report prints the
sentence that would confirm it: a lawful request to Binance asking whether
that address is one it issued, and to whom. That is the address the request
has to name; the hot wallet two hops on identifies nobody. Note the directness
component at 0.5: the tool scores an inference below a label-file match, and
the exact match is still listed.

---

## 7 — New: a sanctioned wallet, and an inference that says what it cannot see

```
0x21b8d56bda776bbe68655a16895afd96f5534fed
```
Ethereum · ETH · 3 hops · **~5 seconds, 8 API calls**

| | |
|---|---|
| Addresses traced | 9 |
| Sanctions screening | **hit — the reported address is on the OFAC SDN list** (GAZA NOW, SDGT) |
| Attribution | **Bybit — probable deposit address (inferred)** `0xcd02509d…dcfe9`, 1 hop |
| Confidence | 0.875 |
| Evidence | 4 transfers, 100% to **Bybit 1**, 3.3581 ETH swept, current balance **1.2121 ETH** |

Two things in one small trace. The reported address itself is a published
designation, which the tool reports above everything else. And its funds
reach a wallet inferred to be a Bybit deposit address — with a balance of
1.21 ETH still sitting there. The rule records that balance rather than
hiding it: a deposit that has landed and not yet been swept is still a
deposit address, but a reviewer should see the number and weigh it. If asked
"could this be a personal wallet that happens to send only to Bybit?" — yes,
and the README's section on inferred deposit addresses says exactly that,
which is why it scores lower and names what would confirm it.

---

## 8 — New: the trail changes asset instead of dying

```
0x4655b7ad0b5f5bacb9cf960bbffceb3f0e51f363
```
Ethereum · ETH · 2 hops · **~3 seconds, 5 API calls**

| | |
|---|---|
| Addresses traced | 11 |
| Exchange | none matched |
| Swaps | **1** — 2,000 ETH into **1inch v4: Aggregation Router**, tx `0x5782df21…`, returned as 1,901.31 wstETH (`0x7f39c581…2ca0`) |
| Message | *"…the funds were swapped … re-run it on token 0x7f39c581… from 0x4655b7ad… to follow the money further."* |

This is a control wallet from the validation corpus (an investment fund), not
a fraud case; it is here because it swaps in the open. A week ago the ETH
trace ended at the router with "sent nothing onward". Now the router is
recognised, the transaction's receipt is read, and the response says what the
money became and where to resume. The output token is named by contract
because wstETH is not in the configured token list — the tool prints the raw
units rather than guess the decimals. Note the router bubble is terminal: a
contract has no outgoing transfers of its own, so no API call is spent
expanding it.

---

## 9 — New: Tron, the chain the evidence points at

```
THWYhwUQnBcKpwSxaXjqv18RPtSoK4C5Ph
```
Tron · USDT · 2 hops · **under a second, 1 API call**

| | |
|---|---|
| Addresses traced | 2 |
| Exchange | **Binance** — `Binance-Hot 7`, 1 hop |
| Value received | 26,405.28 USDT |
| Confidence | **1.00** |

A USDT-TRC20 wallet whose every transfer went to Binance's labelled hot
wallet. Found by script on 15 September (the most recent sender of at least
1,000 USDT into `Binance-Hot 7`), not chosen by hand. The point of the demo is
the label file behind it: a week ago Tron had 7 labelled wallets across 4
exchanges, so most Tron traces ended nowhere; it now has 40 across 18, every
one read from TronScan's own tag and checked on chain for bytecode and inbound
value. If asked why this matters more than the Ethereum demos: TRM Labs put
58% of 2024 illicit crypto volume on Tron and UNODC calls USDT on Tron the
"preferred choice" of the cyber-fraud industry — see RESEARCH.md for both.

---

## 10 — New: three complaints, one operation

```
0x000000000532b45f47779fce440748893b257865
```
Ethereum · ETH · 3 hops · **~15 seconds, 30 API calls** (then open the stored case)

| | |
|---|---|
| Addresses traced | 76 |
| Attribution | Binance — probable deposit address (inferred) `0x11b07437…c4663`, 2 hops, confidence 0.74 |
| **Related cases** | **61 shared intermediaries** with two other stored traces (`0x0000000009324…`, `0x00000000bf02…`), four of them inferred Binance deposit addresses |

All three reported addresses carry Etherscan's *Phish / Hack* label, and all
three were traced separately. The *Related cases* panel shows that their money
passes through the same 61 wallets — the same amounts at the same hops — which
is what one operation run from several wallets looks like, and what three
separate complaints would never have shown. Say the line: this is a query over
cases already traced; it costs no API call. Then say the caveat the README
states: the rule excludes what the label files know, so an unlabelled public
contract can appear as a "shared intermediary" too — read a cluster with its
amounts.

---

## Running order

Trace 1, then 2, then 3. The story escalates: nothing found → something odd
but inconclusive → a trace that *lost* its exchange when the time rule was
applied, which is the strongest argument for the tool's honesty you can make
in one screen.

Set the depth selector to **3 hops**.

Then switch the first selector to **"Who sent funds here"** and run 4 and 5 at
**1 hop**. Both return in about two seconds on a single API call, and they
change the scale of the claim: one wallet, ten more people who paid it — and
the tool refusing to overcount on the next.

Finish with 6 (and 7 if there is time): the new capability, an attribution
that names the deposit address the request has to cite, scored as the
inference it is.

---

## If a live trace disappoints

Pattern findings are threshold comparisons against a graph that reshapes as
new transactions arrive. Trace 3 is the proof: a wallet that fires today may
not fire next week — this is a property of the method, not a defect, and it
is worth saying out loud if asked.

Every trace is stored as a case, so a known-good result can be opened
instantly and will look identical every time:

```
http://localhost:5173/case/75e32f8e-a88c-43af-b456-b99278f275cf
```

That is trace 6 as archived on 15 September. Use it as a fallback, or as the
closing argument for why cases are preserved: **evidence has to be kept as it
stood when it was taken.** Its text report
(`GET /trace/75e32f8e-a88c-43af-b456-b99278f275cf/report?format=text`) is the
one to hand a judge who asks what an officer would actually attach to a
request: 415 lines, and the appendix lists every one of the transactions the
32 addresses were connected by.

---

## Before presenting

```bash
cd ~/exchequer/backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000
cd ~/exchequer/frontend && npm run dev
```

Open <http://localhost:5173> — use `localhost`, not `127.0.0.1`.
Check the status line reads **3 chains** before you start.

If asked about the research behind the laundering claims: RESEARCH.md has
every claim, the source read for it, the exact passage and a verdict; the
README's *Validation against real wallets* has the measured numbers; and
JUDGE_QA.md has the fifteen answers. The three sentences to have ready:

1. "Every claim in the README has a source you can open, and where the source
   said less than we did, we changed the README, not the source."
2. "We measured our own rules on 88 real wallets and published the inconvenient
   result: the shapes we look for appear near ordinary high-volume wallets too,
   so a pattern is a reason to look closer and the tool has never scored it as
   more. What it establishes with confidence is the exact-match attribution to
   an exchange, and now the probable deposit address the request should name."
3. "The one thing an evidentiary tool must not do is report money that was
   never the victim's, and we found ours could -- by following transfers made
   before the funds arrived. That is fixed, tested, and written down."

If asked about sanctions screening: every address in every trace is checked
against the OFAC SDN list published 4 September 2026 — 124 Ethereum, 282 Tron
and 1 BSC address. Trace 7 is a live hit; none of the others is listed.

The mixer category is empty, and there is a good answer if it comes up: every
mixer currently on the SDN list is a Bitcoin service, and Tornado Cash was
delisted in March 2025. The stop-at-a-mixer rule is built and tested; the list
simply has nothing on our three chains today.
