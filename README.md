# TraceChain

**Traces cryptocurrency fraud from a victim-reported wallet address to the exchange it was cashed out through.**

Built for Smart India Hackathon 2026 — problem statement **SIH26183** (Ministry of Home Affairs).

A victim reports one wallet address. TraceChain follows the money outward hop by hop, flags known laundering patterns along the way, identifies the exchange where the funds landed, and produces a report an investigator can attach to a legal request.

It traces **three chains** — Ethereum (ETH, USDT, USDC), BNB Smart Chain (BNB, USDT, USDC) and Tron (TRX, USDT) — because most laundering moves as stablecoins rather than native currency, and USDT-TRC20 on Tron is the dominant cash-out rail for scam proceeds out of India.

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
3. Name it anything (e.g. `tracechain`) and copy the key.

The free tier allows ~5 requests/second and 100,000 requests/day. TraceChain self-throttles below that limit and backs off automatically, so a demo will not die mid-trace.

> TraceChain uses Etherscan's **V2** multi-chain endpoint (`api.etherscan.io/v2/api?chainid=1`). The old V1 per-chain hosts have been retired, so a key issued for V1 still works but the old URLs do not.

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

Open **<http://localhost:5173>**.

> Use `localhost`, not `127.0.0.1`. Vite binds to IPv6 `[::1]` by default, so `http://127.0.0.1:5173` will not connect. Run `npm run dev -- --host 127.0.0.1` if you need IPv4.

The frontend calls `/api/*`, which Vite proxies to the backend on port 8000 — so no URL is hardcoded and nothing needs configuring.

---

## Try it

Real mainnet addresses that produce real attributions. Pick the **chain** and **asset** to match the row.

| Chain / asset | Address | What you get |
|---|---|---|
| Ethereum · ETH | `0x60d02e0956e2f3795167c15ba61ab452c85c2533` | **Best demo.** ~138 addresses at 4 hops, reaches **Binance** in 2, confidence ≈ 0.90, plus an amount-split flag |
| Ethereum · ETH | `0x536c4921d1aafde6a5cda882fb5ca046f3601c65` | **Laundering demo, ~10s.** 617 ETH fanned across 10 recipients — 11 red bubbles, no exchange match |
| Ethereum · USDT | `0x0b2fdf416cf2951499de9a1adac65c8e9907c8c2` | Stablecoin cash-out — **Binance 14** in 1 hop, 102.8M USDT, confidence 1.00 |
| BSC · USDT | `0x32d03f46ba2857c8e6a920ab3fed1f24d35d85d1` | **BNB Smart Chain** — Binance Hot Wallet 6 in 1 hop, 19.3M USDT |
| BSC · BNB | `0x8894e0a0c962cb723c1976a4421c95949be2d4e3` | Native BNB fan-out from a Binance hot wallet |
| Ethereum · ETH | `0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045` | vitalik.eth — busy wallet, exercises the fan-out limits |

Start at **2–3 hops** for a demo. A 4-hop trace on a busy Ethereum wallet takes ~3 minutes and ~60 API calls because of free-tier rate limiting.

---

## API

### `POST /trace`

```json
{ "address": "0x...", "chain": "bsc", "asset": "USDT", "max_depth": 4,
  "direction": "outgoing" }
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
| `GET /trace/{case_id}/report?format=text` | Downloadable report (`format=json` for structured) |
| `GET /cases` | History of past traces |
| `GET /exchanges?chain=bsc` | What that chain's exchange label database covers |
| `GET /risk-labels?chain=bsc` | What that chain's sanctions/mixer screening covers |
| `GET /health` | Liveness, plus per-chain readiness, assets and label counts |

---

## The heuristics, in plain English

Both rules live in `backend/app/pattern_detection.py`, and every threshold is a named constant in one `PatternConfig` dataclass at the top. Each finding reports the thresholds it applied, so it can be re-checked by hand.

### Peel chain

Stolen funds walked through a series of throwaway wallets, with a little skimmed off at each hop.

1. Find wallets with exactly one source and one destination in the trace, appearing in **at most 3 transfers** (single-use).
2. Join consecutive such wallets into a run; keep runs of **2 or more**.
3. Amounts must **never grow** along the run (2% tolerance for gas noise).
4. The run must **end lower than it started** — that is the "peel".
5. Each hop must forward **at least 50%** of what it received. A hop that keeps half the money is a split, and the other rule handles it.

### Amount split (structuring)

One address receives a sum and immediately fans it out to hide the trail.

1. Sent to **3 or more** distinct recipients.
2. Between **50% and 110%** of what came in went straight back out — it forwarded, it did not keep.
3. No single recipient took more than **90%** of the total, so the money was genuinely divided rather than passed along whole with dust attached.
4. The address is **not itself a known exchange** — exchanges fan out to thousands of customers by design.

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

Two categories, carrying the same evidentiary weight but different investigative meaning:

| Category | Meaning | Effect on the trace |
|---|---|---|
| `sanctioned` | The address belongs to a designated entity | None — it is an ordinary wallet whose transfers mean what they say |
| `mixer` | The address is a tumbler | **The trace stops here** |

The mixer rule is the important one, and it is a correctness rule rather than a presentational one.
A tumbler pays out from a commingled pool, so transfers leaving it have no established relationship
to the deposit the trace arrived on. Following them would not follow the money — it would manufacture
a trail the transactions do not support and hand an investigator a confident-looking graph built on a
false premise. Stopping and saying so is the honest answer, and a trace that ends at a mixer reports
that as a substantive finding rather than as a failed search for an exchange.

Every address in these files is sanctioned; `mixer` marks the subset that are tumblers, which is this
project's own editorial classification of the designated entity's name and is recorded as such. The
sanctions fact itself is never editorial.

> Screening degrades safely. With no label file present the trace still runs and still attributes an
> exchange — it simply reports that it was not screened.

---

## Exchange labels

Labels are **per chain and never shared between them**. Binance's hot wallet on Ethereum and Binance's
hot wallet on BSC are different addresses; matching one chain's address against the other's labels would
manufacture an attribution no transaction supports.

| File | Coverage |
|---|---|
| `backend/data/exchange_labels.json` | **337 addresses / 18 exchanges** — Binance, Coinbase, Kraken, OKX, Bitfinex, Huobi/HTX, KuCoin, Gate.io, Crypto.com, Bybit, Bitstamp, HitBTC, Gemini, Bithumb, Bittrex, Poloniex, Upbit, Remitano |
| `backend/data/exchange_labels_bsc.json` | **30 addresses / 9 exchanges** — Binance, Gate.io, KuCoin, Huobi/HTX, MEXC, BitMart, **CoinDCX**, Azbit, FixedFloat |
| `backend/data/exchange_labels_tron.json` | **7 addresses / 4 exchanges** — Binance, OKX, Bybit, Bitfinex |
| `backend/data/risk_labels*.json` | Sanctioned and mixer addresses per chain, generated from OFAC's SDN list — see [Sanctions and mixer screening](#sanctions-and-mixer-screening) |

**374 verified exchange wallets in total, across three chains.**

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
TronScan's own API** (`/api/account` → `addressTag`), which is the strongest provenance available for free
anywhere in this project — the label comes from the explorer that assigns it.

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

### Indian exchanges

**CoinDCX is now covered on BSC** (`0x8c7efd5b…c88973e`), imported from BscScan's own labels and verified
on-chain. WazirX and ZebPay remain absent: their hot wallets could not be sourced to a standard
appropriate for an attribution tool, and guessing one would mean falsely naming a real company in a
law-enforcement report.

To add one properly:

1. Find the wallet on <https://etherscan.io/accounts/label/> or <https://bscscan.com/accounts/label/> and confirm the label on the explorer itself.
2. Add it to the relevant `labels` object, lowercased:
   ```json
   "0xabc...": { "exchange": "WazirX", "label": "WazirX 1", "type": "hot_wallet" }
   ```
3. Run the verifier for that chain and confirm it passes.
4. Restart the backend (labels are cached at startup).

---

## Limitations

Stated plainly, and repeated in every exported report:

- **One asset per trace.** ETH, USDT and USDC are each traced separately; a launderer who *swaps* between assets, or bridges to a chain TraceChain does not cover, is not followed across that hop.
- **Internal contract transactions are not traced.** Value moved by a contract call rather than a direct transfer is invisible.
- **BSC covers a recent window, not all history.** NodeReal caps one query at 100,000 blocks (~3.5 days), so history is walked backwards in windows — 500,000 blocks (~17 days) by default. Raise `NODEREAL_LOOKBACK_BLOCKS` to widen it, at proportionally more API calls. Ethereum has no such limit.
- **An exchange match identifies where funds arrived, not who controls the account.** Only the exchange can link a deposit address to a customer identity, via a lawful request.
- **The graph is a sample, not a complete picture.** Depth, fan-out and node limits mean funds may also have reached other exchanges along paths that were not expanded.
- **Attribution is only as good as the label file.** A null result may mean the exchange is simply absent from it — check `GET /exchanges`.
- **A trace stops at a mixer, and cannot resume past one.** This is deliberate rather than a gap to close: the link between a tumbler's deposits and its payouts does not exist in the transaction data, so no amount of further traversal could recover it.
- **Screening covers the OFAC SDN list only.** An address absent from it is not thereby established as legitimate, and the designation carries no automatic force in Indian law — it is a lead and an escalation trigger, not a verdict.
- **`direct_senders` lists addresses that funded the reported one, not confirmed victims.** A sender may be the offender's own wallet, an exchange withdrawal, or an unrelated payment; only the exchanges among them can be identified from chain data alone.

---

## Project structure

```
tracechain/
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
│   │   ├── scoring.py            confidence score
│   │   ├── models.py             SQLite (SQLAlchemy) case storage
│   │   └── report.py             exportable report
│   ├── data/
│   │   ├── exchange_labels.json      337 verified Ethereum exchange wallets
│   │   ├── exchange_labels_bsc.json   30 verified BSC exchange wallets
│   │   ├── exchange_labels_tron.json   7 verified Tron exchange wallets
│   │   └── risk_labels*.json          OFAC SDN addresses, per chain
│   ├── scripts/
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
│   │   │   ├── Home.jsx           landing form, chain/asset/direction
│   │   │   └── TraceView.jsx      console: feed, graph, evidence rail
│   │   └── components/
│   │       ├── GraphView.jsx      force graph, label-collision aware
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
| `test_graph_builder.py` | All four traversal brakes, both directions, seed-vs-deeper fetch failures, depth stability |
| `test_ofac_import.py` | Chain assignment from OFAC's own idType, and that a Bitcoin address is skipped rather than misfiled |

---

## Deployment

A single Docker image builds the frontend with Node and serves it from FastAPI, so
the UI and API share one origin — no CORS, no second deployment, and no backend
URL baked into the bundle.

```bash
docker build -t tracechain .
docker run -p 8000:8000 --env-file backend/.env -v tracechain-data:/data tracechain
```

Then open <http://localhost:8000>. The same image runs on Railway, Fly, Render or
any VM; `railway.json` adds a health check on `/health`. Mount a volume at `/data`
so the case store survives a redeploy.

**A note on hosting this publicly.** The free API tiers allow roughly three
requests per second *across the whole deployment*, and one trace makes 12–60
calls. Two people tracing at once will throttle each other, so a public instance
is fine for evaluation and not for concurrent use.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/health` shows `etherscan_key_configured: false` | `backend/.env` is missing or has no key. Copy `.env.example`, add the key, restart. |
| Frontend says "Cannot reach the TraceChain backend" | The backend is not running on port 8000. Start it with `uvicorn app.main:app --reload`. |
| `http://127.0.0.1:5173` refuses to connect | Vite binds to IPv6. Use `http://localhost:5173`. |
| Trace returns 429 | Provider rate limit. Wait a few seconds; reduce the hop count. |
| BSC shows "unavailable" in the chain selector | `NODEREAL_API_KEY` is not set in `backend/.env`. Ethereum is unaffected. |
| BSC trace finds nothing on an address you know is active | Its activity may predate the lookback window. Raise `NODEREAL_LOOKBACK_BLOCKS`. |
| `blockNum not reached` in the logs | NodeReal's index trails the chain head by a few blocks. Handled automatically; safe to ignore. |
| Trace is slow on a busy wallet | Expected — requests are throttled to stay under the free-tier cap. Use 2–3 hops for a demo. |
| Exchange is `null` on a real address | The funds may not have reached an exchange within the hop limit, or that exchange is not in the label file. Check `GET /exchanges`. |

---

## Upgrade path

- **Bitcoin** — a different model entirely (UTXO rather than accounts), so it needs its own adapter rather than another entry in the chain registry.
- **Postgres** — `models.py` uses SQLAlchemy, so it is a connection-string change.
- **More chains** — `chain_data.py` is the only seam that knows where data comes from. Adding a chain needs three things: a transfer-history API (not just an RPC node), verified token contracts, and its own label file. Etherscan's **Lite plan ($49/mo)** unlocks Polygon, Arbitrum, Optimism, Base and Avalanche through the code already present — all of which have published labels.
- **More label coverage** — the matcher is the only component that decides attribution, and it reads one JSON file per chain.
- **Deposit-address clustering** — `match_directness` already exists as a separate scoring input so weaker inferred attributions score lower than exact matches.
- **Cross-case correlation** — every trace is already stored, so finding reported addresses that converge on a shared intermediary is a query over the case table rather than new tracing machinery. This is what scales a reverse trace from one campaign to a national picture.
- **Cross-asset following** — the sharpest remaining limitation. A launderer who swaps ETH for USDT at a DEX breaks the trail; detecting a deposit into a known router and resuming on the output asset would close it.
- **PDF reports** — `report.py` already emits structured JSON and plain text, so this is a renderer, not new analysis.
