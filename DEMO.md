# Exchequer — demo addresses

Eleven traces. The first ten were re-verified **cold** (empty cache) on **23 September 2026**,
after the label files grew (1,020 Ethereum exchange wallets across 92
exchanges, up from 337 across 18) and screening gained other governments'
sanctions lists, mixer pools and stolen-funds wallets. Every request count and
time below is from that run. Traces 1–3, 6–7 and 10 run at **depth 3** on
**Ethereum / ETH** and complete in 3–13 seconds; traces 4–5 are reverse traces
at **1 hop** and return in about a second on one request each. The README's
flagship address at **4 hops** takes ~28 seconds and 31 requests.

Four of the ten came out differently from the 15 September run, and each
difference is explained in its section: trace 2's pattern no longer fires,
trace 3 now reaches an exchange again (a newly labelled one), trace 6 now also
reaches a mixer, and the flagship now ends at a probable Bitget deposit
address one hop out. None of them changed because a rule was loosened.

Since that run the Ethereum file also carries 19,027 Bitget deposit
addresses and screening carries ~8,900 reported scam wallets; all ten traces
were re-checked afterwards and attribute exactly as below — the only change
is the phishing flags noted in traces 6 and 10.

Those are cold numbers. On the hosted instance the backend traces this list
in the background at startup and keeps the responses on disk, so on the day
each of these answers from cache in well under a second — say "20–40 seconds
cold, instant cached", and `GET /health` → `warm_cache` shows whether the
warm-up has finished.

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
Ethereum · ETH · 3 hops · **~4 seconds, 5 API calls**

| | |
|---|---|
| Addresses traced | 7 |
| Exchange | none matched |
| Confidence | not applicable — nothing attributed |
| Patterns | none |
| Screening | no hit |
| Transfers excluded by the time rule | 18 |

The funds were followed for three hops and never reached a labelled exchange,
and no laundering rule matched. Note what the tool does here: the confidence
panel reads **"Not applicable — no exchange attributed"** rather than 0%.
Finding nothing is a legitimate result, not a failure — and it held with three
times as many exchange labels loaded, which makes it a stronger "nothing" than
it was.

---

## 2 — The pattern that stopped firing

```
0xbc1ada2e98dd0087cf4cc0c8bd0e6276c82fadc9
```
Ethereum · ETH · 3 hops · **~7 seconds, 12 API calls**

| | |
|---|---|
| Addresses traced | 26 (31 on 15 September) |
| Exchange | none matched |
| Confidence | not applicable |
| Patterns | **none** (15 September: amount split) |

On 15 September a wallet downstream of this address fanned what it received
across four or more recipients, passing 90–102% straight through, and the
amount-split rule fired. On 23 September, run cold, it does not: the graph is
five addresses smaller and the fan-out no longer meets the thresholds. The
rule did not change; the transactions around these wallets did — the
traversal keeps the ten largest counterparties of each address, so new
activity changes which wallets are followed.

This is no longer the demo it was, and it is better used as the answer to a
question than as a slide: *"why should I trust a pattern?"* — because the tool
never scored one, and here is a case of one appearing and disappearing on the
same address as the chain moved. See *If a live trace disappoints* below. For
the running order, skip it and go 1 → 3.

---

## 3 — The attribution that was lost, then found again

```
0x536c4921d1aafde6a5cda882fb5ca046f3601c65
```
Ethereum · ETH · 3 hops · **~11 seconds, 25 API calls**

| | |
|---|---|
| Addresses traced | 34 |
| Exchange | **Uphold** — exact label `0x1c727a55…6de5d`, **2 hops**, 53.28 ETH received |
| Confidence | **0.82** |
| History | 4 Sep: Binance at 0.65 · 15 Sep: **none** · 23 Sep: **Uphold at 0.82** |
| Patterns | **peel chain** |
| Transfers excluded by the time rule | **636** |

This trace has now changed twice, each time for a reason you can state.

On 4 September it reached Binance at 0.65. On 15 September, with the time
rule in place, it reached nothing: the Binance path ran through transfers a
wallet made *before* the traced funds arrived there — money that was never the
reported wallet's. The tool lost an attribution the evidence did not support.

On 23 September it reaches **Uphold**, an exchange and fiat gateway,
two hops out, through a wallet Etherscan tags as Uphold's. That label was
added on 22 September (from the newer published scrape of Etherscan's tags,
and checked on chain before it was accepted); the path itself obeys the time
rule — 636 pre-arrival transfers are still excluded. So the honest summary
is: the tool dropped an unsupported attribution, and later found a supported
one when it learned a wallet it had been walking past. Binance 14 still
appears in the match list, at 3 hops.

Say this out loud: a tool that reports where the victim's money went has to
be able to lose an attribution when the evidence does not support it, and to
say exactly what changed when it gains one. The peel-chain finding remains:
single-use wallets forwarding declining amounts in sequence.

---

## 4 — Reverse trace: who paid the offender

```
0x536c4921d1aafde6a5cda882fb5ca046f3601c65
```
Ethereum · ETH · **direction: who sent funds here** · 1 hop · **~1 second, 1 API call**

| | |
|---|---|
| Addresses that funded it | **10** |
| Total received from them | 43.5207 ETH |
| Largest single sender | 16.9325 ETH |
| Exchanges among the senders | none |

Trace 3 asked the other question. **Ten separate addresses paid money into
it** — and none of them is a labelled exchange, so none is explained away as
a withdrawal, even with three times as many exchange labels loaded. (The
totals are lower than on 15 September — 248 ETH then — because the traversal
keeps the ten largest senders of each address and the set has changed as the
wallet kept receiving; the count did not.)

One complaint, ten more addresses that paid the same wallet. Each is a
candidate victim who may hold a separate FIR, and the panel is labelled
*"Funded this address"* rather than *"victims"* on purpose — the transactions
establish that money moved, not who the sender was.

---

## 5 — Reverse trace: why it is labelled carefully

```
0x60d02e0956e2f3795167c15ba61ab452c85c2533
```
Ethereum · ETH · **direction: who sent funds here** · 1 hop · **~1 second, 1 API call**

| | |
|---|---|
| Addresses that funded it | 10 |
| **Of which labelled exchanges** | **5** — four Binance, one OKX |
| Candidate victims | 5 |
| Source exchange | Binance 17, confidence 1.00 |

Ten addresses funded this wallet, but five of them are exchange hot wallets,
and the panel marks each one **"withdrawal, not a victim"** in the row itself.
A tool that reported "10 victims" here would double the count, in the
direction that inflates a case. Run this straight after 4.

---

## 6 — The deposit address a request has to name — and a mixer

```
0x00000000072d54638c2c2a3da3f715360269eea1
```
Ethereum · ETH · 3 hops · **~11 seconds, 20 API calls**

| | |
|---|---|
| Addresses traced | 32 |
| Attribution | **Binance — probable deposit address (inferred)** `0xd1565e8f…7aa20`, 1 hop |
| Confidence | **0.875** (hop 1.0 · amount 1.0 · directness **0.5**) |
| Evidence | 2 outgoing transfers, 100% of them to **Binance 14**, 2.3201 ETH swept |
| Also in `matches` | Binance 14 itself, exact label, 2 hops |
| **Screening** | the reported address is itself a **reported phishing wallet** (`Fake_Phishing4939`); **mixer — Tornado Cash Proxy** `0x722122df…6b6967`, 3 hops, 10 ETH in; the trace stops there |
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

New since 22 September: another branch of the same money puts **10 ETH into
Tornado Cash** three hops out. The alert says so above the finding, and the
trace stops at the mixer instead of walking its payouts — a mixer pays out of
a commingled pool, so following it would invent a trail. Tornado Cash is no
longer on the OFAC list (delisted March 2025); the mixer label comes from
Etherscan's own tag, and the alert names that source, not a government.

---

## 7 — A wallet three governments have acted against

```
0x21b8d56bda776bbe68655a16895afd96f5534fed
```
Ethereum · ETH · 3 hops · **~5 seconds, 6 API calls**

| | |
|---|---|
| Addresses traced | 9 |
| Sanctions screening | **hit — the reported address itself** (GAZA NOW): OFAC SDN list, **and** the UK Sanctions List (counter-terrorism, CTD0004), **and** an Israeli NBCTF seizure order (ASO 2/24) |
| Attribution | **Bybit — probable deposit address (inferred)** `0xcd02509d…dcfe9`, 1 hop |
| Confidence | 0.875 |
| Evidence | 4 transfers, 100% to **Bybit 1**, 3.3581 ETH swept |

Two things in one small trace. The reported address is designated not by one
government but by three, and the alert lists all three with the entry that
names it — a finding a report can quote. And its funds reach a wallet inferred
to be a Bybit deposit address. If asked "could this be a personal wallet that
happens to send only to Bybit?" — yes, and the README's section on inferred
deposit addresses says exactly that, which is why it scores lower and names
what would confirm it.

---

## 8 — The trail changes asset instead of dying

```
0x4655b7ad0b5f5bacb9cf960bbffceb3f0e51f363
```
Ethereum · ETH · 2 hops · **~3 seconds, 4 API calls**

| | |
|---|---|
| Addresses traced | 11 |
| Exchange | none matched |
| Swaps | **1** — 2,000 ETH into **1inch v4: Aggregation Router**, returned as wstETH (`0x7f39c581…2ca0`) |
| Message | *"…the funds were swapped … re-run it on token 0x7f39c581… to follow the money further."* |

This is a control wallet from the validation corpus (an investment fund), not
a fraud case; it is here because it swaps in the open. The router is
recognised, the transaction's receipt is read, and the response says what the
money became and where to resume. The output token is named by contract
because wstETH is not in the configured token list — the tool prints the raw
units rather than guess the decimals. The router bubble is terminal: a
contract has no outgoing transfers of its own, so no API call is spent
expanding it.

---

## 9 — Tron, the chain the evidence points at

```
THWYhwUQnBcKpwSxaXjqv18RPtSoK4C5Ph
```
Tron · USDT · 2 hops · **under a second, 1 API call**

| | |
|---|---|
| Addresses traced | 2 |
| Exchange | **Binance** — `Binance-Hot 7`, 1 hop |
| Confidence | **1.00** |

A USDT-TRC20 wallet whose every transfer went to Binance's labelled hot
wallet. Found by script on 15 September (the most recent sender of at least
1,000 USDT into `Binance-Hot 7`), not chosen by hand. The point of the demo is
the label file behind it: Tron has 41 labelled exchange wallets across 19
exchanges, every one read from TronScan's own tag and checked on chain for
bytecode and inbound value — and Tron is where screening grew most: **915
sanctioned or seized addresses**, 585 of them from Israel's counter-terror
seizure orders, almost all USDT. If asked why this matters more than the
Ethereum demos: TRM Labs put 58% of 2024 illicit crypto volume on Tron and
UNODC calls USDT on Tron the "preferred choice" of the cyber-fraud industry —
see RESEARCH.md for both.

---

## 10 — Three complaints, one operation

```
0x000000000532b45f47779fce440748893b257865
```
Ethereum · ETH · 3 hops · **~3 seconds, 26 API calls** (then open the stored case)

| | |
|---|---|
| Addresses traced | 76 |
| Attribution | Binance — probable deposit address (inferred) `0x11b07437…c4663`, 2 hops, confidence 0.74 |
| **Related cases** | **60 shared intermediaries** with `0x0000000009324…` and **46** with `0x00000000bf02…`, four of them inferred Binance deposit addresses |
| **Screening** | all three reported addresses are on Etherscan's phishing list, and **all three reach the same reported phishing wallet** (`Fake_Phishing4645`) at 3 hops |

All three reported addresses carry Etherscan's *Phish / Hack* label, and all
three were traced separately. The *Related cases* panel shows that their money
passes through the same wallets — the same amounts at the same hops — which
is what one operation run from several wallets looks like, and what three
separate complaints would never have shown. Say the line: this is a query over
cases already traced; it costs no API call. Then say the caveat the README
states: the rule excludes what the label files know, so an unlabelled public
contract can appear as a "shared intermediary" too — read a cluster with its
amounts.

New since the scam lists went in: the same known phishing wallet appears three
hops out in all three traces. It is labelled now, so it is flagged in each
case rather than counted as a shared intermediary (hence 60 and 46, where the
15 September run counted 61 and 47) — and a labelled scam wallet common to
three complaints is a stronger link than an unlabelled one.

---

## 11 — Frozen by Tether, on the chain that matters

```
TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts
```
Tron · USDT · 2 hops · **~3 seconds, 10 API calls**

| | |
|---|---|
| Addresses traced | 30 |
| **Screening** | the reported address — **USDT frozen by Tether on 11 September 2026** — and the wallet it paid next, frozen the same day |
| Exchange | **Binance** — `Binance-Hot 7`, exact label, 2 hops, 45,968.32 USDT received |
| Confidence | **0.80** |
| Patterns | amount split |

Tether can freeze an address on its USDT contract, and it does — after a
sanctions match, a law-enforcement request or a theft. It publishes nothing but
the act, and the act is on chain: every freeze is an `AddedBlackList` event on
the USDT contract. Exchequer replays those events and keeps the addresses
frozen today — 7,597 on Tron and 2,780 on Ethereum as of 23 September, a random
sample checked against the contract's own `isBlackListed()` with no
disagreement. No dataset sits between the chain and the label.

Say what the freeze means and what it does not: the issuer acted on this
wallet twelve days ago, and on the wallet it paid, the same day — a reason to
ask Tether what it knows, on a lawful request. It does not say why, and the
alert says so. Meanwhile 45,968 USDT reached Binance's hot wallet two hops
out, split across several wallets on the way: the request to Binance is the
second letter. This is the demo for "why Tron", in three seconds.

---

## Present mode

On any case, press **P** (or the Present button). The case becomes four screens sized for the projector: the finding alone, the route alone, four numbers for what was left out, the handoff. Arrow keys step; **Esc** drops back to the console with everything still there — use Present for the walk-through, the console for questions.

## Running order

Trace 1, then 3. The story escalates: nothing found → a trace that *lost*
its exchange when the time rule was applied and later found a different one
when a wallet was labelled, which is the strongest argument for the tool's
honesty you can make in one screen. Keep trace 2 in reserve for the question
"why should I trust a pattern?".

Set the depth selector to **3 hops**.

Then switch the first selector to **"Who sent funds here"** and run 4 and 5 at
**1 hop**. Both return in about a second on a single API call, and they
change the scale of the claim: one wallet, ten more people who paid it — and
the tool refusing to overcount on the next.

Finish with 6 and 7: an attribution that names the deposit address the
request has to cite, scored as the inference it is; a mixer the trace refuses
to walk through; and a wallet three governments have acted against. If the
room asks "why Tron?", run 11: three seconds, and Tether's own freeze on the
screen.

---

## Letting a judge pick a live address

Do not let them pick from Etherscan's front page. "Latest transactions" is
bots, swaps and gas top-ups; a random one is a wallet with two counterparties
and nothing to say. Let them pick at random **from a list of reported fraud
wallets** — their choice, our population.

**The list:** Etherscan's Phish / Hack tags, mirrored on GitHub (the same
source the validation corpus and demos 6 and 10 came from), 5,594 addresses:

    https://raw.githubusercontent.com/dappcenter/etherscan-labels/d547040b8bf65577945bcc53cec62a96945cc705/src/hack-addresses.json

(The raw view: 850 KB, 33,566 lines, six per entry, so GitHub's normal file
view refuses to render it.) Many entries carry Etherscan's name tag —
`"Akropolis Hacker 1"` — which reads better than bare hex; one with a
`txnCount` of a few dozen is a fuller trace than one with two. Open it on
the judges' side, ask for a line number, paste the address,
**Where funds went · Ethereum · ETH · 3 hops**. Depth 3, not 4: 4 can take
40 s cold, 3 is usually under 20.

**What that population produces.** 16 picked at random on 16 September 2026,
3 hops, cold: six reached an exchange (Bitfinex 0.88 via an inferred deposit
address and an amount split; Poloniex 0.95; Remitano 0.74; Binance 0.74 after
a swap; Bittrex 0.68; Coinbase 0.47), six traced but reached nothing within
3 hops, four had never sent ETH or USDT (receive-only or contract
addresses). So roughly 40% land on an exchange, and a quarter are dead ends
by nature. Say the sentence before pressing Trace: *"We have not seen this
one. If it finds nothing, that is a finding — the tool never guesses."*

**Scout the night before.** `scripts/scout.py` runs addresses through the
same code as `POST /trace` and prints one line each, storing no case:

    cd backend && .venv/bin/python -m scripts.scout --file candidates.txt
    cd backend && .venv/bin/python -m scripts.scout 0x… --depth 3 --direction incoming

Whatever it touches is cached, so an address scouted on the hosted instance
traces in under a second on the day. The six above are ready-made fallbacks;
`0x414bca67…` (→ Poloniex 0.95, one hop, 2 addresses) is the fastest.

**If the pick is thin**, re-run it as *Who sent funds here*: on a scam
wallet the funders are almost always the fuller picture, and the exchanges
among them are marked as withdrawals.

Two lists that do *not* work for this: Etherscan's per-incident exploit
pages (e.g. `etherscan.io/accounts/label/wazirx-exploit` — the WazirX hack
proceeds went into Tornado Cash, so each trace flags the reported address as
a stolen-funds wallet and then stops at a mixer: a correct finding, but a
short one that never reaches an exchange), and the old umbrella `phish-hack` label
page, which Etherscan has emptied.

---

## If a live trace disappoints

Pattern findings are threshold comparisons against a graph that reshapes as
new transactions arrive. Trace 2 is the proof: its amount split fired on 15
September and not on 23 September — a property of the method, not a defect,
and worth saying out loud if asked. Attributions move too, for stated reasons:
trace 3 lost one to the time rule and gained another from a new label.

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
against six governments' lists — the OFAC SDN list published 18 September
2026, the UK Sanctions List, the EU consolidated list, Israel's NBCTF
counter-terror seizure orders, Japan's Ministry of Finance list and France's
asset-freeze register: 915 Tron, 139 Ethereum and 7 BSC addresses. Only
measures still in force count; a lifted Israeli seizure order is left out.
Trace 7 is a live hit on three of those lists at once.

Three more categories sit beside the sanctions lists, and the alert always says
which source a hit came from. **Frozen by Tether** (2,780 Ethereum, 7,597 Tron
before overlap) — every address whose USDT Tether has frozen, replayed from the
USDT contract's own blacklist events; trace 11 is a live hit. **Mixers** (40 Ethereum, 14 BSC: Tornado Cash,
Typhoon, Privacy Pools pools and routers) — Tornado Cash left the OFAC list in
March 2025, so these come from Etherscan's own tags, and a trace still stops at
one; trace 6 is a live hit. **Stolen funds** (8,393 Ethereum, 560 BSC) — the
WazirX, Bybit, BingX, Ronin and other exploiters Etherscan tags, plus reported
phishing and scam wallets from ScamSniffer's blacklist and Etherscan's
Phish/Hack list, each checked on chain. A trace flags those and keeps going,
because where the thief moved the money is the point. Traces 6 and 10 start
at one: their reported addresses are on the phishing list.
