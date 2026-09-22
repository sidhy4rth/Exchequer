# Exchequer

[![tests](https://github.com/sidhy4rth/Exchequer/actions/workflows/test.yml/badge.svg)](https://github.com/sidhy4rth/Exchequer/actions/workflows/test.yml)

**Traces cryptocurrency fraud from a victim-reported wallet address to the exchange it was cashed out through.**

Built for Smart India Hackathon 2026 — problem statement **SIH26183** (Ministry of Home Affairs).

A victim reports one wallet address. Exchequer follows the money outward hop by hop, flags known laundering patterns along the way, identifies the exchange where the funds landed, and produces a report an investigator can attach to a legal request.

It traces **three chains** — Ethereum (ETH, USDT, USDC), BNB Smart Chain (BNB, USDT, USDC) and Tron (TRX, USDT). The choice follows the published evidence rather than a hunch: Chainalysis measured stablecoins at 63% of illicit transaction volume in 2024 and 84% in 2025; TRM Labs measured 58% of 2024 illicit volume on Tron (a share that halved in 2025); and the UN Office on Drugs and Crime describes USDT on Tron as the "preferred choice" of the Southeast-Asian cyber-fraud operations that target Indian victims. No published source measures the cash-out rails for Indian scam proceeds specifically, so this README does not claim one. Every figure above is quoted from the source it came from in [RESEARCH.md](RESEARCH.md).

The design principle throughout is **auditability**. Every attribution is an exact match against a published exchange wallet in a data file you can open and read. Every laundering finding is a handful of arithmetic comparisons that reports the thresholds it applied. There is no model, no clustering, and no proprietary score — because a conclusion that reaches a courtroom has to be one a human can re-check by hand.

---

## How it works

```
  reported address
        │
        ▼
  ┌───────────────┐   Picks the provider for the chosen chain + asset
  │ chain_data.py │   Ethereum → Etherscan  BSC → NodeReal  Tron → TronGrid
  └───────┬───────┘   All rate-limit aware, retrying with backoff
          ▼
  ┌───────────────┐   BFS, depth-limited (default 4 hops), in either direction
  │ graph_        │   outgoing → where the money went (default)
  │ builder.py    │   incoming → who funded this address
  └───────┬───────┘   Highest-value branches first; drops dust
          ▼
  ┌───────────────┐   Exact lookup against that chain's own label file
  │ exchange_     │   (labels are never shared between chains)
  │ matcher.py    │
  └───────┬───────┘
          ▼
  ┌───────────────┐   Exact lookup against OFAC's published SDN list
  │ risk_         │   Stops the trace at a mixer — its payouts are
  │ matcher.py    │   uncorrelated with its deposits
  └───────┬───────┘
          ▼
  ┌───────────────┐   Peel chain + amount split, as explainable fixed rules
  │ pattern_      │
  │ detection.py  │
  └───────┬───────┘
          ▼
  ┌───────────────┐   hop proximity (40%) + amount correlation (35%)
  │ scoring.py    │   + match directness (25%)
  └───────┬───────┘
          ▼
   graph + exchange + confidence + flags  ─────►  SQLite  ─────►  report
```

---

## Prerequisites

- **Python 3.11+**
- **Node.js 20+** and npm
- A free **Etherscan API key** (Ethereum)
- A free **NodeReal API key** (BNB Smart Chain) — optional; without it Ethereum still works and BSC reports itself unavailable
- A free **TronGrid API key** (Tron) — optional; Tron works without one, but keyless requests are throttled to roughly one every 1.2 seconds

---

## Setup

### 1. Get an Etherscan API key

1. Go to <https://etherscan.io/apis> and create a free account.
2. Sign in, open **API Keys** in the left sidebar, click **Add**.
3. Name it anything (e.g. `exchequer`) and copy the key.

The free tier allows ~5 requests/second and 100,000 requests/day. Exchequer self-throttles below that limit and backs off automatically, so a demo will not die mid-trace.

> Exchequer uses Etherscan's **V2** multi-chain endpoint (`api.etherscan.io/v2/api?chainid=1`). The old V1 per-chain hosts have been retired, so a key issued for V1 still works but the old URLs do not.

### 2. Backend

```bash
cd backend

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# open .env and paste your keys after ETHERSCAN_API_KEY= and NODEREAL_API_KEY=
```

Confirm the API integration works before anything else — this prints real transactions from the chain:

```bash
python -m scripts.check_etherscan
```

You should see a table of live transactions and `OK: Etherscan integration confirmed against real chain data.`

Then start the server:

```bash
uvicorn app.main:app --reload --port 8000
```

Check it: <http://127.0.0.1:8000/health> — `etherscan_key_configured` must be `true`.
Interactive API docs: <http://127.0.0.1:8000/docs>

### 3. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

> **Building the UI to be served by FastAPI instead** (one origin, no Vite):
> ```bash
> cd frontend && VITE_API_BASE="" npm run build
> ```
> The empty base makes the bundle call `/health` and `/trace` directly. A plain
> `npm run build` bakes in the dev-mode `/api` prefix, which only the Vite proxy
> rewrites — served by FastAPI those calls return the SPA's own HTML and the UI
> reports the backend as unreachable. The Dockerfile sets this variable already.

Open **<http://localhost:5173>**.

The first screen is a sign-in page: **username `admin`, password `admin`**. It is a front door for the
demonstration, not access control — the backend has no accounts and the API answers without it; the
page remembers, for the browser tab, that the door was crossed. Behind the form drifts the ledger the
tool knows (`GET /ledger`): every address real — the OFAC list in red, each exchange's wallets in its
own colour, probable deposit addresses dotted, the stored cases' intermediaries in grey. The cursor
resolves the ones near it, nothing ever overlaps, and clicking an address traces it across the ledger
to the nearest exchange wallet — or says no exchange was within reach.

The mark is a chequer. The Exchequer was named for the chequered cloth on which the Crown's money was
counted, square by square; one square is red — the sum being traced.

The interface answers first and shows evidence on demand. The home page is the address form with the ten `DEMO.md` traces in a dropdown, one line of coverage per chain, and the stored cases. A case opens as: a red sanctions banner if any address is listed; one finding bar — where the money went, the address to cite, how sure (the score with its three inputs; the working one click away); then the money flow drawn by hop, the reported address on the left and whatever it reached on the right, the attributed path the one bold green line, every other transfer thin (the force-directed bubble view is a toggle); beneath it only the transfers that matter — the attributed path, anything flagged or sanctioned, any swap — with the full list one click away; and on the right, one folded section each for inferred deposit addresses, patterns, swaps, related cases, funders and scope, opening only when they hold something. **Present** (or the P key) shows the same case as four screens sized for a projector — the finding alone, the route alone, four numbers for what was left out, the handoff — stepped with the arrow keys; Esc returns to the console with everything still there. Every address copies itself when clicked. Dark console skin by default; the paper case-file skin is one click away and remembered per browser.

> Use `localhost`, not `127.0.0.1`. Vite binds to IPv6 `[::1]` by default, so `http://127.0.0.1:5173` will not connect. Run `npm run dev -- --host 127.0.0.1` if you need IPv4.

The frontend calls `/api/*`, which Vite proxies to the backend on port 8000 — so no URL is hardcoded and nothing needs configuring.

---

## Try it

Real mainnet addresses that produce real attributions. Pick the **chain** and **asset** to match the row.

| Chain / asset | Address | What you get |
|---|---|---|
| Ethereum · ETH | `0x60d02e0956e2f3795167c15ba61ab452c85c2533` | **Best demo.** 48 addresses at 4 hops in ~28 s / 31 requests (23 Sep, cold); reaches a **probable Bitget deposit address** in 1 hop, confidence 0.875 (it sweeps 100% to Bitget 6), with **Binance 14**, OKX 24 and Bitget 6 as exact matches at 2 hops; one swap detected |
| Ethereum · ETH | `0x536c4921d1aafde6a5cda882fb5ca046f3601c65` | **Laundering demo, ~10s.** 617 ETH fanned across 10 recipients — 11 red bubbles, no exchange match |
| Ethereum · USDT | `0x0b2fdf416cf2951499de9a1adac65c8e9907c8c2` | Stablecoin cash-out — **Binance 14** in 1 hop, 102.8M USDT, confidence 1.00 |
| BSC · USDT | `0x32d03f46ba2857c8e6a920ab3fed1f24d35d85d1` | **BNB Smart Chain** — Binance Hot Wallet 6 in 1 hop, 19.3M USDT |
| BSC · BNB | `0x8894e0a0c962cb723c1976a4421c95949be2d4e3` | Native BNB fan-out from a Binance hot wallet |
| Ethereum · ETH | `0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045` | vitalik.eth — busy wallet, exercises the fan-out limits |

Start at **2–3 hops** for a demo: those return in roughly 20 seconds. A 4-hop trace on a busy Ethereum wallet takes about 40 seconds and ~44 API calls.

Addresses at the same depth are fetched concurrently (`TRACE_CONCURRENCY`, default 6). Providers answer in ~5 seconds on the free tiers and almost all of that is network wait, so fetching a level serially left a trace idle most of the time. The clients' own throttles still cap the request *rate*, so this shortens a trace without increasing load on the API — and the graph is unchanged, because results are reassembled in address order rather than completion order.

---

## API

### `POST /trace`

```json
{ "address": "0x...", "chain": "bsc", "asset": "USDT", "max_depth": 4,
  "direction": "outgoing", "time_budget_seconds": 90 }
```

`chain` is `ethereum` (default) or `bsc`. `asset` is the chain's native symbol or a stablecoin —
`ETH`/`USDT`/`USDC` on Ethereum, `BNB`/`USDT`/`USDC` on BSC.

**One asset per trace, deliberately.** 1 BNB and 1 USDT are not comparable quantities, so a graph
mixing them could not be scored — the amount-correlation component would be meaningless. Following a
single asset keeps every threshold and weight valid without change.

The chain is never inferred from the address: an EVM address is valid on every EVM chain, and the same
address can hold unrelated funds on both.

`direction` is `outgoing` (default) or `incoming`, and it changes the question being asked.

| Direction | Question | What comes back |
|---|---|---|
| `outgoing` | Where did the victim's money go? | The exchange it was cashed out at, with a confidence score |
| `incoming` | Who sent money to this address? | `direct_senders` — every address that funded it, largest first |

A reverse trace is what turns one complaint into a picture of a campaign. If the reported address
belongs to an offender, the addresses that paid it are candidate victims of the same operation, each
of whom may hold a separate FIR. The field is named `direct_senders` rather than "victims" on purpose:
a sender may equally be the offender's own wallet, an exchange withdrawal, or an unrelated payment,
and the response marks the ones that are labelled exchanges so that reading is not left to the reader.

Edges always point the way the money moved, whichever direction the walk ran — so a reverse trace's
graph, patterns and amounts are read exactly like a forward one's.

`time_budget_seconds` (optional, 10–600) is a wall-clock cap. Without it a trace runs until the depth,
fan-out and size limits stop it — on a busy wallet at 4 hops that can be three minutes on the free
tier. With it, the walk stops expanding once the time is spent and returns what it has: the addresses
it reached but never read are counted in `addresses_unexpanded_by_time`, the truncation reason names
the budget, and `seconds_elapsed` says how long it actually took. The overshoot is at most one batch of
concurrent requests (a few seconds). The interface offers this as a **Stop after 1:30** switch beside the
address form, off by default; the demos never need it, a judge's random pick might.

```json
{
  "case_id": "uuid",
  "graph": { "nodes": [...], "edges": [...] },
  "exchange": "Binance",
  "confidence": 0.9,
  "flags": ["peel_chain", "amount_split"],
  "hop_count": 2
}
```

The response also carries supporting detail used by the sidebar and the report: `confidence_detail` (the full per-component working), `findings` (each pattern with its evidence and thresholds), `trace_path`, `matches`, `truncation_reasons` and `warnings`.

| Status | Meaning |
|---|---|
| `400` | Malformed address, unknown chain, or an asset that chain does not carry |
| `429` | Provider rate limit survived all retries — wait and retry |
| `502` | Could not reach the blockchain data provider |
| `503` | No API key configured for the requested chain |

A wallet with no outgoing transfers, or one that reaches no known exchange, returns **200** with `exchange: null` and a plain-English `message` — those are findings, not errors.

### Other endpoints

| Endpoint | Purpose |
|---|---|
| `GET /trace/{case_id}` | Retrieve a stored case |
| `GET /trace/{case_id}/report?format=text` | The investigator's report (`format=json` for structured) — header with the tool version (`git describe` locally; the deployed commit in the image), a one-paragraph plain-English summary, the finding and its basis (label match or inference), the path hop by hop with amounts, times and hashes, every pattern with the thresholds it applied, every inferred address with its evidence and what would confirm it, the limitations, and an appendix of every address and transaction hash so anything in it can be re-checked on a public explorer. Cases traced before 15 September 2026 lack the stored hashes and say so |
| `GET /cases` | History of past traces |
| `GET /cases/correlate` | Intermediary addresses shared by two or more stored cases — the campaign view. `?case_id=` narrows it to one case; see [Cross-case correlation](#cross-case-correlation) |
| `GET /exchanges?chain=bsc` | What that chain's exchange label database covers |
| `GET /risk-labels?chain=bsc` | What that chain's sanctions/mixer screening covers |
| `GET /health` | Liveness, plus per-chain readiness, assets and label counts |

---

## The heuristics, in plain English

Both rules live in `backend/app/pattern_detection.py`, and every threshold is a named constant in one `PatternConfig` dataclass at the top. Each finding reports the thresholds it applied, so it can be re-checked by hand.

Where the rules come from, stated honestly: the *shapes* come from the literature, the *numbers* do not. The peel chain was named and described by Meiklejohn et al. in 2013 (*A Fistful of Bitcoins*, IMC'13), who also warned in the same paragraph that the shape "extends well beyond criminal activity" — ordinary exchange withdrawals produce it too. The fan-out shape is what Elliptic's 2025 pig-butchering typology describes as moving funds "through dozens of intermediary wallets" before they reach an exchange. **Every numeric threshold below — 3 transfers, 2 intermediates, 50%, 2%, 4 recipients, 90–102%, 60% — is this project's own choice and comes from no paper.** How those choices behave on real wallets is measured in [Validation against real wallets](#validation-against-real-wallets); the sources are in [RESEARCH.md](RESEARCH.md).

### Before either rule: money cannot be forwarded before it arrives

The traversal itself applies one rule about *when*. When the trace reaches a wallet, it knows the moment the traced funds landed there — the earliest transfer on the edge that brought them. Only transfers that wallet made **at or after** that moment can carry the victim's money, so anything it sent earlier is left out of the graph as the wallet's own prior business. Walking backwards the rule mirrors: only money a sender received **at or before** it paid the next hop can have funded that payment.

Without this, a busy wallet that once received the victim's funds would have its entire earlier history reported as where the victim's money went. The reported address itself is not windowed, because the trace starts there and does not know when the victim's funds arrived. Every node in the response carries `window_start` (or `window_end` on a reverse trace) and `excluded_by_time`, and the total is reported as `transfers_excluded_by_time`, so the effect of the rule is visible rather than silent.

### Peel chain

Stolen funds walked through a series of throwaway wallets, with a little skimmed off at each hop.

1. Find wallets with exactly one source and one destination *within the trace*, appearing in **at most 3 transfers** within it. (The trace only sees a wallet's transfers to and from the addresses it followed — see [Limitations](#limitations).)
2. Join consecutive such wallets into a run; keep runs of **2 or more**.
3. Amounts must **never grow** along the run (2% tolerance for gas noise).
4. The run must **end lower than it started** — that is the "peel".
5. Each hop must forward **at least 50%** of what it received. A hop that keeps half the money is a split, and the other rule handles it.

### Amount split

One address receives a sum and fans it out across several recipients, multiplying the paths an investigator must follow. This is sometimes called "structuring", but that word is a legal term for breaking up *currency* transactions to evade a *reporting threshold* (31 CFR § 1010.100(xx)), and there is no reporting threshold on a public blockchain — so the rule here describes a shape, not a statutory offence. The same shape is produced by payroll, exchanges and market makers, which is why the rule is treated as a reason to look closer and never as a verdict.

1. Sent to **4 or more** distinct recipients.
2. Between **90% and 102%** of what came in went back out — it passed the money through, it did not spend it.
3. No single recipient took more than **60%** of the total, so the money was genuinely divided rather than passed along mostly whole.
4. The address is **not itself a known exchange** — exchanges fan out to thousands of customers by design.

These numbers were tightened on 15 September 2026 from the original 3 / 50–110% / 90% after the measurement below: the original values flagged 40% of ordinary high-volume wallets.

### Inferred exchange deposit addresses

Most real cash-outs do not land on a labelled hot wallet. The customer is given a *deposit address* the exchange controls, the money lands there, and the exchange later sweeps it into a hot wallet. The label files know the hot wallet and almost never the deposit address, so a trace reaches an unlabelled wallet one hop before the exchange — and that unlabelled wallet is the one a lawful request has to name, because a hot wallet receives from thousands of customers and identifies nobody.

The rule in `backend/app/deposit_inference.py` says an unlabelled wallet is a **probable deposit address of exchange E** when:

1. It is not the reported address and has no label of its own.
2. It made **at least 2** outgoing transfers.
3. **Every one of them** went to the **same** labelled E wallet (a hot, exchange, contract or cold wallet — never a labelled *deposit* wallet, since deposits sweep to hot wallets) and to nowhere else.
4. Where the provider can answer cheaply, its current balance is recorded as evidence — a swept deposit address holds close to nothing — but a balance is never a requirement, because a deposit that has not yet been swept is still a deposit address.

The tell is the *whole* history, not the last transfer. A personal wallet that deposits to Binance sends to its own deposit address, which is unlabelled, and does other things with its money; a deposit address does one thing, every time, to one place. The rule reads only outgoing transfers, so it cannot measure the delay between a deposit and its sweep, and it cannot see the gas-funding transfer an exchange sends before an ERC-20 sweep. It is strict on what it can see rather than loose on what it cannot.

An inferred address is a **weaker attribution and is scored as one**: `match_directness` is 0.5 instead of 1.0, so at the same distance it scores 0.125 below a labelled wallet. It sits one hop closer than the hot wallet it sweeps to, which hop proximity rewards, so against that particular wallet the two come out within a few hundredths of each other — both appear in `matches`, the response says `attribution_inferred: true`, the sidebar reads *"Probable Binance deposit address (inferred — see evidence)"*, and the report prints the evidence (sweep count, destination, share, balance) and the sentence that would confirm it: a lawful request to the exchange asking whether the address is one of theirs.

Ways it can be wrong, stated plainly: an exchange's *own* internal wallet that consolidates into a hot wallet has the same shape and would be called a deposit address (harmless in practice — it still belongs to that exchange); a wallet whose owner really did send everything, twice, straight to a labelled hot wallet would be misnamed; and the rule only sees the newest 200 transfers, so an address with an older, different history is judged on its recent one. It never fires on a wallet the trace did not expand, so at the depth limit it says nothing rather than guessing. On the validation corpus it fired on **0 of 48** control wallets — see [Validation against real wallets](#validation-against-real-wallets).

### Swaps at a DEX router

A trace follows one asset, so when a wallet sends 10 ETH to a Uniswap router the ETH trail ends there — but the wallet did not lose the money; it got it back as USDT in the same transaction and carried on. Until now the trace reported that as "sent to an address that sent nothing onward", which is true of the ETH and false of the money.

When an outgoing transfer's recipient is in `backend/data/router_labels*.json` (see [Router labels](#router-labels)), the trace stops there — a router contract has no outgoing transfers of its own — fetches the transaction's receipt (one request per transfer, at most two per edge), and reads its ERC-20 `Transfer` events. A transfer whose recipient is the wallet that sent the swap is the swap's output. The edge then carries `swap: {router, asset_in, amount_in, asset_out, amount_out, tx, …}`, the response lists every swap in `swaps` with a plain sentence in `swap_notes`, the report prints them under *Swaps*, and when no exchange was reached the message says where to resume: *"funds were swapped for USDT at Uniswap V3: Router 2; re-run the trace on USDT from 0x…"*.

**The trace is not resumed on the output asset.** Doing that honestly means deciding what amount correlation should mean across 1 ETH → 2,400 USDT, and the one-asset-per-trace rule exists precisely because those are not comparable. A swap that is recorded and re-run keeps every threshold valid; a swap silently crossed does not.

What it cannot see, stated plainly: a swap *into* the chain's native coin leaves no `Transfer` to the sender (the router unwraps WETH and sends ETH internally), so it is reported as "sent to a router; no token output found in the receipt" rather than guessed; a token whose contract is not in the chain's configured token list is named by contract with the amount left in raw units, because guessing its decimals would misstate the figure; and on a *token* trace the transfer into a swap usually lands on a liquidity pool rather than the router, so only transactions sent to a labelled router are recognised.

### Confidence score

Three weighted components. The score is a plain function of these three inputs and nothing else:

| Component | Weight | What it measures |
|---|---|---|
| Hop proximity | 40% | Fewer hops = less room for the trail to be broken by a wallet we cannot see. Decays linearly from 1.0 at a direct deposit. |
| Amount correlation | 35% | How much of the value that left the reported address actually arrived. 99% surviving means it is very likely the same money; 2% may be an incidental transfer that happens to end at an exchange. |
| Match directness | 25% | Exact match against a labelled wallet scores 1.0. Exists as a separate input so future weaker attributions (clustering, deposit-address inference) score lower instead of being blended in silently. |

**No exchange match scores 0.0 and reports "no attribution"** — never a low-but-nonzero number that might get over-read.

Detected laundering patterns and truncated traversals are reported as **caveats** rather than folded into the number, so the score stays reproducible and an investigator is never quietly nudged by a hidden adjustment.

---

## Cross-case correlation

One complaint gives one trace. The problem statement's actual ask is the campaign: many complaints whose money converges on the same wallets. Every trace is stored with its full graph, so `GET /cases/correlate` is a query over what has already been traced — no new API calls, no new tracing, and it answers in milliseconds.

The rule, in plain terms. For every stored case, the *intermediaries* are the addresses in its graph other than the reported address and other than anything with a label of its own — an exchange hot wallet, a DEX router, a sanctioned entity. An intermediary reached by traces of **two or more different reported addresses on the same chain** is a point of convergence, and is returned with the cases that reach it, how far from each reported address it sits, and how much of each case's traced value arrived there. Inferred deposit addresses count and are named as such, because a request to the exchange can then ask about one address on behalf of several complaints. Exchange hot wallets are excluded on purpose: two victims whose money both ended at Binance 14 share a bank, not an offender. The same wallet traced twice is one complaint, not two.

Contracts are never intermediaries either: a contract recognised as a service by the traversal (WETH, a pool — see the fifth brake) is skipped by its flag, and anything in the exchange or router label files is skipped by lookup, which also covers cases stored before the graph carried those flags. The response carries the clusters and, when `case_id` is given, `related_cases`: the same answer grouped by the *other* case, each listing the wallets shared with this one, probable deposit addresses first. That grouping is what the trace view shows as the **Related cases** panel.

The case store is evidence and nothing deletes from it in normal use. Traces run for measurement go through the same endpoint, though, so `scripts/prune_cases.py --keep <id> …` exists to reduce a demo machine's store to the cases that matter; it copies the database aside first and refuses to delete everything.

What it showed on 15 September 2026: three wallets carrying Etherscan's *Phish / Hack* label (`0x000000000532…`, `0x0000000009324…`, `0x00000000bf02…`) share **61 intermediaries**, four of them inferred Binance deposit addresses — the shape of one operation run from several wallets, which three separate complaints would never have shown.

The way it can mislead, stated plainly: the rule can only exclude what the label files know. An unlabelled *public contract* — the Beacon Deposit Contract, a liquid-staking pool, a bridge — is reached by many unrelated traces and appears as a "shared intermediary" with a very large value. Read a cluster with its amounts: money converging on a wallet in sums comparable to the traced values is a lead; a wallet receiving 130,000 ETH inside one trace is a service. The cure is a label for that service, added the way every other label is added.

---

## Sanctions and mixer screening

Every address in a trace is also checked against the digital currency addresses published on the
U.S. Treasury's **Specially Designated Nationals list**. The matching rule is the same exact lookup
the exchange labels use, for the same reason: an address is called sanctioned if and only if a
published government list says so.

Labels are generated straight from Treasury's own XML, and each entry keeps the sanctions programs
and the exact `idType` OFAC recorded, so any label can be checked against the source document:

```bash
cd backend && .venv/bin/python -m scripts.import_ofac_addresses
cd backend && .venv/bin/python -m scripts.import_ofac_addresses --dry-run
```

Current OFAC coverage, from the list published **18 September 2026**:

| File | Coverage |
|---|---|
| `backend/data/risk_labels.json` | **124 addresses / 48 designated entities** on Ethereum |
| `backend/data/risk_labels_tron.json` | **334 addresses** on Tron |
| `backend/data/risk_labels_bsc.json` | **1 address** on BNB Smart Chain |

**Other governments.** OFAC is one government. The UK, the EU, Israel, Japan and France also publish
crypto addresses they have frozen or seized, and several name addresses OFAC does not — Israel's
counter-terror seizure orders alone name 585 Tron wallets, almost all USDT. They are imported into
`intl_sanctions*.json`: the UK Sanctions List and the EU consolidated list read directly (their
addresses sit in free text, and each is filed under the chain the text names before it — `ETH:`,
`BNB:`, `TRX:`), and Israel's NBCTF, Japan's Ministry of Finance and France's DG Trésor through
OpenSanctions, which extracts them from those publishers' documents (CC BY-NC 4.0: non-commercial use).
Only measures still in force count — a wallet named only in lifted seizure orders is left out. An
address several governments list names all of them, because "designated by the US, the UK and Israel"
is a stronger finding than any one alone. Canada, Australia, Switzerland and the UN publish no crypto
addresses; I checked all 95 official lists OpenSanctions carries.

```bash
cd backend && .venv/bin/python -m scripts.import_intl_sanctions
```

Sanctioned addresses screened, all governments together: **915 on Tron, 139 on Ethereum, 7 on BSC**.

Three categories, with different investigative meaning and different authority behind them:

| Category | Meaning | Source | Effect on the trace |
|---|---|---|---|
| `sanctioned` | The address is on a government sanctions or seizure list | OFAC, UK, EU, Israel, Japan, France | None — it is an ordinary wallet whose transfers mean what they say |
| `mixer` | The address is a tumbler's pool or router | Etherscan / BscScan tags | **The trace stops here** |
| `stolen` | The address is tagged as a hacker's or reported as a phishing / scam wallet | Etherscan / BscScan tags, ScamSniffer | None — where the thief moved the money is the point |

The mixer rule is the important one, and it is a correctness rule rather than a presentational one.
A tumbler pays out from a commingled pool, so transfers leaving it have no established relationship
to the deposit the trace arrived on. Following them would not follow the money — it would manufacture
a trail the transactions do not support and hand an investigator a confident-looking graph built on a
false premise. Stopping and saying so is the honest answer, and a trace that ends at a mixer reports
that as a substantive finding rather than as a failed search for an exchange.

**Mixers and stolen funds come from the explorer, not a government, and every finding says so.** Tornado
Cash, the mixer that mattered on Ethereum, left the SDN list in March 2025 following *Van Loon v.
Treasury*, and every mixer OFAC still lists is a Bitcoin service — so a sanctions-only screen would never
stop at a mixer on these chains. `scripts/import_threat_labels.py` takes the pools and routers of Tornado
Cash, Typhoon and Privacy Pools (40 on Ethereum, 14 on BSC; never their governance, token or vesting
contracts) and the wallets Etherscan tags as a thief's (the WazirX, Bybit, BingX, Ronin and other exploiters), each
checked to exist and to have been used on chain. `--scam-lists` then adds reported phishing and scam
wallets from ScamSniffer's published blacklist and Etherscan's Phish/Hack label (two pinned mirrors),
filed under each chain they have been used on — 1,604 with no history on either chain were left out.
Stolen-funds coverage: **8,393 on Ethereum, 560 on BSC**. A wallet on a scam list is that list's
accusation, and the finding says whose. They sit in `threat_labels*.json`, below the government lists: where an address is on both, the
government entry is the one reported.

```bash
cd backend && .venv/bin/python -m scripts.import_threat_labels
cd backend && .venv/bin/python -m scripts.import_threat_labels --scam-lists
```

> Screening degrades safely. With no label file present the trace still runs and still attributes an
> exchange — it simply reports that it was not screened. `GET /risk-labels` reports `screened` so a
> null result is never ambiguous.

---

## Exchange labels

Labels are **per chain and never shared between them**. Binance's hot wallet on Ethereum and Binance's
hot wallet on BSC are different addresses; matching one chain's address against the other's labels would
manufacture an attribution no transaction supports.

| File | Coverage |
|---|---|
| `backend/data/exchange_labels.json` | **20,047 addresses / 92 exchanges**: 1,020 exchange wallets plus **19,027 Bitget per-customer deposit addresses** — the largest: Huobi/HTX, Coinbase, Binance, Kraken, Bitfinex, Nexo, OKX, Bithumb, KuCoin, **CoinDCX** (29), Bitget, Poloniex; also **Delta Exchange** |
| `backend/data/exchange_labels_bsc.json` | **38 addresses / 13 exchanges** — Binance, MaskEX, Gate.io, KuCoin, Huobi/HTX, MEXC, BitMart, Hotbit, **CoinDCX**, AscendEX, Crypto.com, Azbit, FixedFloat |
| `backend/data/exchange_labels_tron.json` | **41 addresses / 19 exchanges** — Binance, Huobi/HTX, KuCoin, MEXC, Poloniex, OKX, Bybit, Bitfinex, Bitget, Gate.io, Kraken, Upbit, Bithumb, Coinone, Bitpanda, CoinSpot, FixedFloat, UEEx, Heleket |
| `backend/data/risk_labels*.json`, `intl_sanctions*.json`, `threat_labels*.json` | Sanctioned, mixer and stolen-funds addresses per chain — see [Sanctions and mixer screening](#sanctions-and-mixer-screening) |

**20,126 verified exchange addresses in total, across three chains**, of which 19,027 are Bitget deposit addresses. A deposit address is the most useful label there is: it names one customer account, which is exactly what a lawful request to the exchange asks about. They come from Etherscan's "Bitget Dep" tags (`import_eth_labels.py --deposits Bitget`), and every one was confirmed on chain to have at least one transaction or token transfer — all 19,027 passed. The Ethereum and BSC files grew on
22 September from a newer published scrape of the same explorer tags (`scripts/import_eth_labels.py`,
dawsbot/eth-labels, pinned), every new address checked on chain the same way; the original importer's
dataset stops in 2023, before Bitget, MEXC and CoinDCX were well covered.

Both files are generated, not hand-typed, and both are reproducible:

```bash
cd backend
python -m scripts.import_exchange_labels    # Ethereum: import + verify
python -m scripts.audit_label_contracts     # Ethereum: strip non-custody contracts
python -m scripts.seed_bsc_labels           # BSC: import + verify
python -m scripts.seed_tron_labels          # Tron: import + verify
python -m scripts.verify_labels             # re-check the Ethereum file on demand
```

Addresses originate from the explorers' own published label pages. Ethereum and BSC are imported from a
dataset pinned to a specific commit, so a re-run reproduces the same input. Tron labels are read **live from
TronScan's own API** (the `addressTag` on its largest-holder listings), which is the strongest provenance
available for free anywhere in this project — the label comes from the explorer that assigns it. The Tron
importer inspects the 600 largest USDT-TRC20 holders and 300 largest TRX accounts, keeps only tags that name a
known centralised exchange (unrecognised tags are printed for review, never kept), and then applies the same
two on-chain checks as Ethereum: no contract bytecode (TronGrid `wallet/getcontract`) and at least one received
transfer. On the 15 September 2026 run: 48 tagged candidates, 40 kept, 0 rejected on chain, 6 listed for review
(a payment processor, a gambling site, an asset manager, a DeFi vault).

### Nothing is accepted on the label alone

Every address must prove itself against live chain data before it enters the file. The metric is
**inbound value**, not nonce — an exchange deposit wallet receives constantly and may almost never send,
so a low nonce proves nothing, whereas zero lifetime value means the address is not handling customer
funds. On the most recent run this rejected **37 of 332** Ethereum candidates and **18 of 48** BSC
candidates.

A second pass then checks for contract bytecode, because an exchange hot wallet is an externally-owned
account. That removed four addresses carrying an exchange's name but doing something else entirely:

| Address | Labelled | Actually |
|---|---|---|
| `0x75231f58…42a86c` | OKX | OKB **token contract** |
| `0x056fd409…6d5cd` | Gemini | GUSD **token contract** |
| `0xed03ed87…9464aa` | Bitfinex | Tether MXNt **token contract** |
| `0x3b3ae790…fb6790` | OKX | OKX DEX **aggregation router** |

The router mattered most: funds passing through a swap router have been *traded*, not deposited, so
attributing that as a cash-out would have named a company that never took custody. Exchange-operated
contract wallets (multisig, deposit forwarders) were kept and typed `contract_wallet`, since funds
reaching those really have reached the exchange.

### Router labels

`backend/data/router_labels.json` (**20 routers, 9 protocols** — Uniswap V2, V3 and Universal Router, 1inch v2–v5, 0x Exchange Proxy, KyberSwap, Metamask Swap Router, OKX DEX, THORSwap, and two smaller ones) and `router_labels_bsc.json` (**4 routers**) come from the same pinned dataset as the exchange labels, restricted to entries whose explorer name ends in "Router" (or is 0x's Exchange Proxy) — executors, governors and allowance targets carry a protocol's name but are not where a swap is sent. Verification is the mirror image of the exchange check: a router **must** carry contract bytecode, and every entry did. PancakeSwap's category is empty in the pinned dataset and SunSwap has no Etherscan-style label source, so BSC and Tron coverage is thin and says so.

```bash
cd backend && .venv/bin/python -m scripts.seed_router_labels
```

### Indian exchanges

**CoinDCX is now covered on BSC** (`0x8c7efd5b…c88973e`), imported from BscScan's own labels and verified
on-chain. WazirX and ZebPay remain absent: their hot wallets could not be sourced to a standard
appropriate for an attribution tool, and guessing one would mean falsely naming a real company in a
law-enforcement report. On Tron, none of the 900 largest accounts inspected carries a TronScan tag for
CoinDCX, WazirX, ZebPay or Giottus — the importer looks for them and would keep them if the explorer tagged
one — so an Indian exchange's Tron deposit can currently only be reached through the
[inferred deposit address](#inferred-exchange-deposit-addresses) rule if it sweeps to a labelled wallet, or
not at all.

To add one properly:

1. Find the wallet on <https://etherscan.io/accounts/label/> or <https://bscscan.com/accounts/label/> and confirm the label on the explorer itself.
2. Add it to the relevant `labels` object, lowercased:
   ```json
   "0xabc...": { "exchange": "WazirX", "label": "WazirX 1", "type": "hot_wallet" }
   ```
3. Run the verifier for that chain and confirm it passes.
4. Restart the backend (labels are cached at startup).

---

## Evidence integrity

A finding can be re-derived from the report — the arithmetic is on the page. What
cannot be re-derived is the input: the provider's answer to each query, at the
moment it was given. So every response a trace is computed from is hashed
(SHA-256) as it arrives, with the request that produced it — credential removed,
parameters in a fixed order — and the UTC time, and the set is stored with the
case as an evidence manifest. One hash over all of them, computed over the
sorted records so it does not depend on the order concurrent fetches finished,
is the manifest hash. The text report prints the whole manifest as Appendix C
and ends with a content hash over every byte above it.

What this establishes: that the bytes hashed are the bytes the tool used. A
reviewer who re-issues a request and obtains the same hash has shown the input
was unchanged; a different hash means the chain — or the provider — has moved
on, which for append-only history means newer transactions exist. It does not
make a response tamper-proof; it makes tampering detectable, and it lets the
document that leaves this tool be checked against the document that reaches a
court:

```
$ head -c -N report.txt | shasum -a 256     # everything above the CONTENT HASH line
```

A response served from the process cache is the same bytes retrieved earlier,
so it is recorded with its original hash and time and marked `cached` — it is
not presented as a second retrieval. Cases stored before this was added carry
no manifest, and the report says so rather than inventing one.

---

## Limitations

Stated plainly, and repeated in every exported report:

- **One asset per trace.** ETH, USDT and USDC are each traced separately. A swap at a labelled DEX router is now *detected* — the trace records what asset came back and tells you where to re-run — but it is not followed automatically, and a swap whose output is the native coin, a swap sent to a liquidity pool rather than a router, or a bridge to a chain Exchequer does not cover, still ends the trail.
- **Internal contract transactions are traced on Ethereum only, at double the request cost.** Value moved by a contract call — a multisig paying out, a smart-contract wallet, a router returning ETH — comes from Etherscan's separate `txlistinternal` endpoint, read on a forward trace only for addresses with no signed outflow (a contract), and on a reverse trace for every address (`ETHERSCAN_INCLUDE_INTERNAL=false` turns it off). Each such transfer is tagged `internal` and edges report `internal_tx_count`. On BSC and Tron, and on every token trace, contract-moved value is still invisible. Reading these adds a fifth brake: an address with **no signed outgoing transfer but contract-originated ones is a contract** (a wallet cannot start an internal transfer), and a contract that pays out to **more than 3 distinct addresses** is a service — WETH, a liquidity pool, a router — whose payouts are other people's money, so it is marked `is_service_contract`, noted as a truncation, and not expanded. A multisig forwarding to one or two recipients still is. Without this brake the flagship address at 4 hops expanded WETH and nine pools: 249 requests and 127 s instead of 41 and 22 s.
- **BSC covers a recent window, not all history.** NodeReal caps one query at 100,000 blocks (~3.5 days), so history is walked backwards in windows — 500,000 blocks (~17 days) by default. Raise `NODEREAL_LOOKBACK_BLOCKS` to widen it, at proportionally more API calls. Ethereum has no such limit.
- **An exchange match identifies where funds arrived, not who controls the account.** Only the exchange can link a deposit address to a customer identity, via a lawful request.
- **The graph is a sample, not a complete picture.** Depth, fan-out and node limits mean funds may also have reached other exchanges along paths that were not expanded.
- **The fan-out limit can be evaded on purpose.** Only the 10 highest-value counterparties of each address are followed. A launderer who splits funds into eleven or more parts knows the smallest will not be followed, and one who sends the real money as the eleventh-largest transfer defeats the walk. Raising `max_branches_per_node` narrows this at a geometric cost in API calls; it does not remove it.
- **Only the most recent 200 transfers of each address are read** (`TRACE_MAX_TXS_PER_ADDRESS`). On a busy wallet, older transfers — including the one that carried the victim's money — may lie beyond that window and go unseen. The trace reports nothing when this happens because the provider does not say how many transfers were not returned.
- **"Single-use" means single-use within the trace.** The peel-chain rule sees only a wallet's transfers to and from the addresses the trace followed. A wallet with one inbound and one outbound transfer *in the graph* may have hundreds of other transfers the trace never fetched, so a peel-chain finding is a statement about the shape of the traced path, not about the wallet's whole history.
- **The amount-split rule has no time window and counts only followed branches.** It compares what a wallet received from the trace with what it sent onward at any later time, so a wallet that received funds and then, over months, paid three unrelated recipients has the same shape as one that fanned them out within the hour. And because only the top 10 counterparties are followed, the forwarded fraction is computed over those, never over the wallet's full outflow.
- **Amount correlation is capped at 100%.** If 1 ETH left the reported address and 100 ETH later arrived at the exchange along the same route, the component scores 1.0, because all of the traced value could have arrived — but most of what reached the exchange was then somebody else's. The explanation text prints both figures so the dilution is visible; the number alone does not show it.
- **The time rule resolves to the second, not to the position within a block.** Transfers carry a block timestamp; a transfer that left an address earlier *in the same block* as the traced funds arrived is followed as if it came after, because "at or after" is judged on the timestamp. This can admit one transfer per address that predates the arrival by a few seconds; it cannot admit anything from an earlier block.
- **The reported address is not time-windowed.** The trace does not know when the victim's funds arrived at the address they reported, so all of its outflows are followed, including any made before the fraud. Every later hop is windowed (see [Before either rule](#before-either-rule-money-cannot-be-forwarded-before-it-arrives)).
- **Attribution is only as good as the label file.** A null result may mean the exchange is simply absent from it — check `GET /exchanges`.
- **A trace stops at a mixer, and cannot resume past one.** This is deliberate rather than a gap to close: the link between a tumbler's deposits and its payouts does not exist in the transaction data, so no amount of further traversal could recover it.
- **Screening covers the OFAC SDN list only.** An address absent from it is not thereby established as legitimate, and the designation carries no automatic force in Indian law — it is a lead and an escalation trigger, not a verdict.
- **`direct_senders` lists addresses that funded the reported one, not confirmed victims.** A sender may be the offender's own wallet, an exchange withdrawal, or an unrelated payment; only the exchanges among them can be identified from chain data alone.
- **A first-time trace is as fast as the free tier allows, and no faster.** See below.

---

## Validation against real wallets

The two pattern rules were measured against real Ethereum wallets, because a threshold that was chosen rather than derived has to be shown to behave. Two corpora, every address fetched by script from a named source and checked on chain for contract bytecode (none typed by hand; provenance for each entry is in `backend/data/validation/corpus.json`):

- **40 positives** — wallets publicly documented as fraud or theft proceeds: 20 from the OFAC SDN list already in the repo (Lazarus Group and other designated individuals; exchanges and OTC services excluded), 17 carrying Etherscan's own *Phish / Hack* label, and the 3 WazirX-hack attacker addresses named in CloudSEK's write-up of 19 July 2024.
- **48 controls** — ordinary wallets with no fraud association, from the same pinned label dataset the exchange importer uses: investment funds, mining-pool payout wallets, charities, payment processors, OTC desks, trading firms, company treasuries and airdrop distributors. The pools, processors and distributors are there on purpose: they fan out by design, so they are the wallets most likely to trip the amount-split rule.

Each wallet was traced forward at depth 3 with the real pipeline (1,416 provider requests in total, 37 addresses per trace on average), and a rule counts as *fired* if it produced a finding anywhere in that graph — which is what an investigator running the tool would see. 32 positives and 47 controls had at least one outgoing ETH transfer; the rest hold and never send, and are excluded because nothing can fire on an empty graph.

| Rule | Thresholds | Fired on positives (of 32) | Fired on controls (of 47) |
|---|---|---|---|
| Peel chain | 3 transfers, 2 intermediates, 50% retention (defaults) | **2** | **2** |
| Peel chain | any retention 0.3–0.9, any activity cap 2–6 | 2 | 1–2 |
| Peel chain | 3 intermediates | 0 | 0 |
| Amount split | **previous defaults**: 3 recipients, 50–110% forwarded, 90% cap | 12 | **19** |
| Amount split | 3 recipients, 90–102%, 60% cap | 8 | 9 |
| Amount split | 4 recipients, 90–102%, 90% cap | 7 | 8 |
| Amount split | **current defaults**: 4 recipients, 90–102%, 60% cap | **6** | **5** |
| Amount split | 5 recipients, 90–102%, 60% cap | 3 | 5 |
| Deposit-address inference | 2 sweeps, 100% to one labelled wallet | — | **0 of 48 control seeds** |

What the numbers establish, and what they do not. **Neither rule separates documented-illicit wallets from ordinary high-volume ones within three hops**, and no point in the 68-point threshold grid brought control firings to zero while still firing on any positive. The peel chain almost never fires; both control hits are mining-pool payouts, which is precisely the legitimate shape Meiklejohn et al. warned produces it. The amount split at its old defaults flagged 40% of ordinary wallets, so the defaults were moved to the grid point with the fewest control firings that still fired on positives — 11% of controls, 19% of positives — and that is an estimate from 79 wallets, not a law. Read a pattern finding as the tool has always asked you to: a reason to look closer, never a verdict. The measurement also does not test recall against ground truth, since a wallet documented as holding stolen funds is not thereby documented as laundering them in one of these two shapes. The deposit-address rule fired on none of the 48 control seeds, which are wallets known not to be exchange deposit addresses; it also marked 69 deeper, unknown wallets across 20 control traces, about which nothing is known either way.

Only Ethereum / ETH was measured. Tron and BSC positives exist (OFAC lists 334 Tron addresses) but no scripted source of Tron *controls* with the same provenance discipline was found, so no number is claimed for those chains.

Regenerate the table (offline, from the committed snapshot; add `--refresh` to re-fetch):

```bash
cd backend && .venv/bin/python -m scripts.build_validation_corpus   # only to rebuild the corpus
cd backend && .venv/bin/python -m scripts.validate_patterns
```

---

## Why a trace takes the time it does

Almost none of it is Exchequer. The graph walk, the pattern rules and the
scoring together take milliseconds; a trace's wall time is very nearly *the
number of provider requests it makes*, and on a free key those arrive at
roughly one and a half to two per second. A depth-3 trace expands ~35
addresses, which is where ~20 seconds comes from.

Measured against a live Etherscan free key, the documented "5 requests/second"
is not what is granted in practice:

| Spacing | Offered | Refused | Useful throughput |
| --- | --- | --- | --- |
| 0.20s | 4.8/s | **67%** | 1.61/s |
| 0.34s | 2.7/s | **54%** | 1.21/s |
| **0.50s** | **1.6/s** | **4%** | **1.56/s** |
| 0.70s | 1.3/s | 0% | 1.28/s |

Every refusal costs a retry with exponential backoff, so asking faster returned
*less* usable data than asking slower. `ETHERSCAN_MIN_INTERVAL` therefore
defaults to **0.50s** -- the measured optimum, not the documented one.

Reading internal transactions adds a second request (`txlistinternal`) only for
an address whose signed list shows no outgoing transfer — a wallet that signs
transactions cannot originate an internal one, so for an ordinary wallet the
second request could return nothing. Measured on the flagship address at
4 hops: asking unconditionally cost 110 requests, asking only for
contract-shaped addresses costs 73, and the pre-internal-transaction trace
cost 41. Reverse traces ask both questions for every address, since a
contract's payout *into* a wallet is exactly what they look for.

Since the ceiling is per *second* while the daily quota goes barely touched (a
trace costs well under 100 of 100,000 calls/day), the only lever that shortens
a trace is making fewer requests. So responses are cached per credential for
`API_CACHE_TTL_SECONDS` (default a day). On-chain history is append-only, so a
cached answer can lag the newest blocks but never contradict them -- traces are
byte-identical warm and cold, and the evidence manifest records for every
cached response when it was originally retrieved, so the report never hides
how old the data was. The effect:

| | Requests | Time |
| --- | --- | --- |
| First trace of an address | ~35 | ~20s |
| Either direction, again | **0** | **0.03s** |

Both traversal directions read the provider's one combined transaction list, so
a reverse trace of an address already traced forward reuses what is in hand.

`GET /health` reports `api_budget` -- a high `rate_limit_penalties` means the
key is being refused, a high cache `hit_rate` means repeat work is already free.

The cache is also written to disk (`API_CACHE_PATH`, a SQLite file beside the
case store; `off` for memory only), so a restart or a redeploy does not forget
every response. And with `EXCHEQUER_WARM_CACHE=1` -- on in the Docker image --
the backend traces the `DEMO.md` addresses (`backend/data/demo_traces.json`)
in a background thread at startup, storing no case, and again at three
quarters of the TTL, so the demos never go cold on a hosted instance. A trace
made while that first pass is running shares the key's rate with it;
`GET /health` reports `warm_cache.in_progress` so you can tell.

**If cold traces are still too slow**, the remaining lever is fan-out: the
traversal follows the 10 highest-value counterparties per address
(`max_branches_per_node`). Lowering it cuts requests roughly geometrically with
depth -- but it is an investigative choice, not a performance knob, because a
narrower walk can miss a path the funds actually took.

---

## Project structure

```
exchequer/
├── backend/
│   ├── app/
│   │   ├── main.py               FastAPI app and routes
│   │   ├── config.py             environment configuration
│   │   ├── chain_data.py         picks the provider for a chain + asset
│   │   ├── etherscan_client.py   Etherscan wrapper (native + ERC-20)
│   │   ├── nodereal_client.py    NodeReal wrapper for BNB Smart Chain
│   │   ├── tron_client.py        TronGrid wrapper for Tron (TRC-20 + TRX)
│   │   ├── graph_builder.py      BFS traversal (both directions) → NetworkX graph
│   │   ├── exchange_matcher.py   exact-match attribution
│   │   ├── risk_matcher.py       sanctions + mixer screening
│   │   ├── pattern_detection.py  peel chain + amount split
│   │   ├── deposit_inference.py  probable exchange deposit addresses
│   │   ├── swap_detection.py     swaps at DEX routers, from receipts
│   │   ├── scoring.py            confidence score
│   │   ├── models.py             SQLite (SQLAlchemy) case storage
│   │   ├── report.py             exportable report
│   │   ├── evidence.py           hash-and-timestamp of every provider response
│   │   ├── api_budget.py         shared request pacer + response cache (memory and disk)
│   │   └── warmup.py             traces the demo addresses at startup so they are cached
│   ├── data/
│   │   ├── exchange_labels.json      1,020 Ethereum exchange wallets + 19,027 Bitget deposit addresses
│   │   ├── exchange_labels_bsc.json   38 verified BSC exchange wallets
│   │   ├── exchange_labels_tron.json  41 verified Tron exchange wallets
│   │   ├── risk_labels*.json          OFAC SDN addresses, per chain
│   │   ├── intl_sanctions*.json       UK, EU, Israel, Japan, France sanctions/seizure addresses
│   │   ├── threat_labels*.json        mixer pools and hack/phishing wallets (explorer tags)
│   │   ├── router_labels*.json        verified DEX routers, per chain
│   │   ├── demo_traces.json           the DEMO.md traces, as requests; read by the warm-up and the seed script
│   │   └── validation/                corpus, snapshot and results of the rule measurement
│   ├── scripts/
│   │   ├── seed_router_labels.py      imports + verifies DEX routers
│   │   ├── build_validation_corpus.py builds the measurement corpus by script
│   │   ├── validate_patterns.py       measures the rules; offline from the snapshot; stores nothing
│   │   ├── prune_cases.py             reduces the case store to named cases, with a backup
│   │   ├── seed_hosted.py             replays the demo traces against a hosted instance
│   │   ├── scout.py                   tries candidate addresses for a live demo, storing nothing
│   │   ├── check_etherscan.py         live API smoke test
│   │   ├── verify_labels.py           re-checks every Ethereum label
│   │   ├── import_exchange_labels.py  imports + verifies Ethereum labels
│   │   ├── audit_label_contracts.py   removes non-custody contracts
│   │   ├── seed_bsc_labels.py         imports + verifies BSC labels
│   │   ├── seed_tron_labels.py        imports Tron labels from TronScan tags
│   │   └── import_ofac_addresses.py   builds risk labels from OFAC's SDN XML
│   ├── tests/                         pure-function suite, no network or keys
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── api.js
│   │   ├── styles.css
│   │   ├── routes/
│   │   │   ├── SignIn.jsx         the demo front door (admin / admin), over the lattice
│   │   │   ├── Home.jsx           intake: address form, the ten DEMO.md traces, coverage, stored cases
│   │   │   └── TraceView.jsx      case view: sanctions banner, finding bar, flow, feed, folded evidence rail
│   │   └── components/
│   │       ├── Present.jsx        the case as four big screens, for the room
│   │       ├── Ledger.jsx         sign-in backdrop: the real ledger, coloured by what the tool knows
│   │       ├── Mark.jsx           the chequer mark
│   │       ├── FlowView.jsx       the money flow by hop: layered SVG, attributed path bold
│   │       ├── GraphView.jsx      force graph, label-collision aware (the "Bubbles" toggle)
│   │       └── ExportButton.jsx
│   ├── vite.config.js
│   └── package.json
├── Dockerfile                    one image: Node builds the UI, FastAPI serves it
├── DEMO.md                       verified demo addresses
└── README.md
```

---

## Tests

The rules that decide what an investigator is told are pure functions over a graph, so the suite
needs no API key, no network and no database:

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

Coverage is deliberately two-sided. Every heuristic is tested both for firing on the shape it
describes *and* for staying silent on ordinary activity, because a false accusation is the expensive
failure here.

| File | What it pins down |
|---|---|
| `test_pattern_detection.py` | Peel chain and amount split, their thresholds, the exchange exemption, graph tagging |
| `test_scoring.py` | Each weighted component, band boundaries, and that patterns and truncation add caveats without moving the number |
| `test_exchange_matcher.py` | Both label-file shapes, case-insensitive lookup, closest-match preference, degrading to "no attribution" on a missing or corrupt file |
| `test_risk_matcher.py` | Both categories, that a mixer ends a trace and a sanctioned address does not, unknown categories dropped rather than guessed |
| `test_graph_builder.py` | All six traversal brakes (including the time budget: unchanged when unspent, stops and counts what it cut when spent, always reads the seed), both directions, seed-vs-deeper fetch failures, depth stability |
| `test_ofac_import.py` | Chain assignment from OFAC's own idType, and that a Bitcoin address is skipped rather than misfiled |
| `test_deposit_inference.py` | The sweep shape fires; one deposit, a wallet that also spends, sweeps to an unlabelled or a labelled *deposit* wallet, dust, the seed and unexpanded wallets all stay silent; an inference scores below a label match |
| `test_swap_detection.py` | Swap outputs read from a real 1inch receipt; native-coin outputs reported as unreadable, never guessed; receipts capped per edge; a failed receipt cannot kill a trace |
| `test_correlation.py` | Two complaints on one unlabelled wallet cluster; a shared hot wallet, router or sanctioned entity never does; the same wallet traced twice is one complaint; chains never mix |
| `test_internal_transactions.py` | Contract-moved value is merged and tagged at exactly one extra request, never on a token trace, and never displaces signed transfers |
| `test_report.py` | Every section an officer needs is present, times and hashes included; the evidence manifest prints and the content hash verifies; a case stored by an earlier version still renders |
| `test_evidence.py` | A response is hashed as received with the credential stripped; a cache hit re-uses the original hash and time; the manifest hash ignores arrival order; a sealed report stops verifying if one byte changes |
| `test_api_budget.py` | The cache distinguishes a miss from a cached None, expires, evicts LRU; a disk-backed cache survives a new instance with the original retrieval metadata and expires on the same clock; the pacer widens on refusal and narrows on success |
| `test_warmup.py` | Every demo is traced and no case is stored; one failing demo does not stop the rest; off unless configured; the shipped demo list is valid requests |

---

## Deployment

A single Docker image builds the frontend with Node and serves it from FastAPI, so
the UI and API share one origin — no CORS, no second deployment, and no backend
URL baked into the bundle.

```bash
docker build -t exchequer .
docker run -p 8000:8000 --env-file backend/.env -v exchequer-data:/data exchequer
```

Then open <http://localhost:8000>. The same image runs on Railway, Fly, Render or
any VM; `railway.json` adds a health check on `/health`. Mount a volume at `/data`
so the case store survives a redeploy.

On Railway specifically: `railway init`, `railway add --service exchequer`,
`railway variables --set KEY=value …` for the three provider keys,
`railway volume add --mount-path /data`, `railway up`, `railway domain`. A
fresh instance has an empty case store; `python -m scripts.seed_hosted
https://<host>` replays the `DEMO.md` traces so the related-cases demo has
something to relate to. `railway down` removes the deployment but keeps the
project, variables and volume, so it can be brought back in two minutes.

**A note on hosting this publicly.** The free API tiers allow roughly three
requests per second *across the whole deployment*, and one trace makes 12–60
calls. Two people tracing at once will throttle each other, so a public instance
is fine for evaluation and not for concurrent use.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/health` shows `etherscan_key_configured: false` | `backend/.env` is missing or has no key. Copy `.env.example`, add the key, restart. |
| Frontend says "Cannot reach the Exchequer backend" | The backend is not running on port 8000. Start it with `uvicorn app.main:app --reload`. |
| The UI loads from port 8000 but every request fails | The bundle was built without `VITE_API_BASE`, so it calls `/api/health` while FastAPI serves `/health` — the request falls through to the SPA catch-all and returns HTML. Rebuild with `VITE_API_BASE="" npm run build`. Only affects a bundle served by FastAPI; the Vite dev server proxies `/api` and is unaffected. |
| `http://127.0.0.1:5173` refuses to connect | Vite binds to IPv6. Use `http://localhost:5173`. |
| Trace returns 429 | Provider rate limit. Wait a few seconds; reduce the hop count. |
| BSC shows "unavailable" in the chain selector | `NODEREAL_API_KEY` is not set in `backend/.env`. Ethereum is unaffected. |
| BSC trace finds nothing on an address you know is active | Its activity may predate the lookback window. Raise `NODEREAL_LOOKBACK_BLOCKS`. |
| `blockNum not reached` in the logs | NodeReal's index trails the chain head by a few blocks. Handled automatically; safe to ignore. |
| Traces feel slow in general | Expected on a free key — a trace is provider-bound, not compute-bound. Check `api_budget` in `GET /health`: `rate_limit_penalties` climbing means the key is being refused (raise `ETHERSCAN_MIN_INTERVAL`), and re-running the same address should be instant from cache. See [Why a trace takes the time it does](#why-a-trace-takes-the-time-it-does). |
| Traces got slower after several runs | The pacer widens itself when the provider refuses, and narrows back as requests succeed. A widened `interval` in `/health` means the key is under pressure — from another tool sharing it, or from a burst of traces. |
| A trace returns stale data | Responses are cached for `API_CACHE_TTL_SECONDS` (default a day), on disk as well as in memory. Lower it, or delete `backend/provider_cache.db`, if you need to see a transfer made seconds ago; the report's evidence section shows when each response was retrieved. |
| Trace is slow on a busy wallet | Partly expected — requests are throttled to stay under the free-tier cap. A level of addresses is fetched concurrently, so if traces feel serial check `TRACE_CONCURRENCY` has not been set to 1. Use 2–3 hops for a demo. |
| Exchange is `null` on a real address | The funds may not have reached an exchange within the hop limit, or that exchange is not in the label file. Check `GET /exchanges`. |

---

## Upgrade path

- **Bitcoin** — a different model entirely (UTXO rather than accounts), so it needs its own adapter rather than another entry in the chain registry.
- **Postgres** — `models.py` uses SQLAlchemy, so it is a connection-string change.
- **More chains** — `chain_data.py` is the only seam that knows where data comes from. Adding a chain needs three things: a transfer-history API (not just an RPC node), verified token contracts, and its own label file. Etherscan's **Lite plan ($49/mo)** unlocks Polygon, Arbitrum, Optimism, Base and Avalanche through the code already present — all of which have published labels.
- **More label coverage** — the matcher is the only component that decides attribution, and it reads one JSON file per chain.
- **Deposit-address clustering** — `match_directness` already exists as a separate scoring input so weaker inferred attributions score lower than exact matches.
- **Cross-case correlation** — every trace is already stored, so finding reported addresses that converge on a shared intermediary is a query over the case table rather than new tracing machinery. This is what scales a reverse trace from one campaign to a national picture.
- **Cross-asset following** — swaps at labelled routers are detected and the output asset named; resuming the trace on that asset automatically needs a defensible definition of amount correlation across two assets, which does not exist yet.
- **PDF reports** — `report.py` already emits structured JSON and plain text, so this is a renderer, not new analysis.
