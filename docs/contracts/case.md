# Case contract v2

A **case** is the result of one trace: the dict `pipeline.run_trace` returns and
the case store keeps. Lane A produces it; Lane B (report, letters, exports) and
Lane C (case store, correlation, interface) read it. This page is the promise
between them.

**Owner:** Lane A. **Changes:** adding an optional field needs the model, this
page and the fixtures updated in one PR. Renaming, removing or changing the
meaning of a field needs a new `contract_version` and approval from both other
lanes.

## How to read a case

```python
from app.contracts import read_case

case = read_case(result)          # result: a stored case or a fresh trace
case.attribution.kind             # "deposit_label" | "deposit_inferred" | "exchange_wallet"
case.reported_amount              # None for an address-only trace
case.transfers[0].block
```

`read_case` upgrades a case stored before v2, so readers never check versions
and nothing in the store needs migrating. Use it instead of reading these
fields from the raw dict.

## What v2 adds

Every v1 field is still there, unchanged. v2 adds:

| Field | Type | Meaning |
|---|---|---|
| `contract_version` | `2` | This contract. |
| `intake.mode` | `"address"` or `"payment"` | `address`: the trace followed a wallet's history from an address. `payment`: it started from the victim's payment transactions (R1, behind the flag `EXCHEQUER_TX_INTAKE`; send `payments` and optionally `ncrp_ack` with `POST /trace`). |
| `intake.payments[]` | list | Each payment: `tx_hash`, `chain`, `asset`, `amount`, `from`, `to`, `block`, `timestamp`, `found_by` (`victim` or `officer_search`). Empty in address mode. |
| `intake.ncrp_ack` | string or null | The NCRP complaint acknowledgement number, when known. |
| `reported_amount` | number or null | What the victim paid, in the traced asset. **Null in address mode**: nobody reported an amount, so nothing may be described as "the reported funds". |
| `attribution` | object or null | What the exchange address is. Null when the trace reached no exchange. |
| `attribution.kind` | see below | Whether the exchange can tie the address to a customer. |
| `attribution.source` | `label_file`, `inference`, `live_tag` | Where the attribution came from: a label file, the deposit-sweep inference, or an explorer tag read at trace time (TronScan). Independent of the kind. |
| `attribution.exchange`, `.address`, `.label` | strings | As in the v1 `exchange`, `exchange_address`, `exchange_label`. |
| `attribution.wallet_type` | string or null | The matcher's own type (`hot_wallet`, `cold_wallet`, `exchange_wallet`, `contract_wallet`, `deposit_wallet`, `inferred_deposit`), kept so nothing is lost. |
| `attribution.depth` | int or null | Hops from the reported address. |
| `estimates.prorata` | number or null | Pro-rata estimate of the traced funds reaching the exchange (the v1 `prorata.estimated`). |
| `estimates.fifo`, `.libr` | number or null | FIFO (money leaves in the order it arrived) and LIBR (the victim's money leaves only when the balance falls below it), R4. Filled only when the flag `EXCHEQUER_TRACING_METHODS` is on and the wallets' windows could be read in full; null otherwise and in older cases. The per-wallet working is in `tracing_methods` (v1-style, beside `prorata`); worked examples in `backend/app/tracing_methods.py`. |
| `estimates.conservative` | number or null | The smallest available estimate across the three methods. **The figure a letter states.** With the flag off it equals `estimates.prorata`. |
| `transfers[].block` | int or null | The block the transfer is in. Filled for every new trace; null in cases stored before v2. |
| `transfers[].log_index` | int or null | A token transfer's event position in its transaction. **Null in a trace, by design**: none of the providers' transfer lists (Etherscan `tokentx`, NodeReal, TronGrid TRC-20) returns it, and reading every receipt would roughly double a trace's API calls. Identify a transfer by `hash`, `from`, `to` and `value_native`; `verify_case` (R18, Lane B) may fill `log_index` from the receipt of each transfer a letter cites. |

Each trace in `follow_ons[].result` (the money after a swap) is a full v2 case
of its own, with its own `attribution` and `estimates` in its own asset.

## Attribution kinds

| `kind` | What it is | What a request letter can ask |
|---|---|---|
| `deposit_label` | A deposit address an explorer labels as the exchange's (for example Etherscan's "Bitget Dep" tags). | The account holder, KYC and statement for that address. |
| `deposit_inferred` | An unlabelled address whose every outflow swept to one exchange wallet: probably a customer deposit address. | First, whether the exchange issued the address; then the same as above. |
| `exchange_wallet` | The exchange's own wallet: hot, cold, a contract, or a label that doesn't say which. It belongs to no customer. | **Not** KYC for the wallet. List the transfers by hash, amount and time, and ask which customer accounts they were credited to. |

A `live_tag` source means the address was attributed from the explorer's tag at
trace time, not from a checked label file: the letter asks the exchange to
confirm the address is theirs before anything else.

## Fixtures

`backend/tests/fixtures/contract/` holds one real recorded trace per kind and
source, upgraded to v2: `deposit_inferred.json` (demo 3), `exchange_wallet.json`
(demo 9, Binance-Hot 7), `exchange_wallet.live_tag.json` (demo 12, Flipster) and
`no_attribution.json` (demo 1). `index.json` says which demo each came from.

They are generated by `python -m scripts.build_contract_fixtures` (from
`backend/`), never edited by hand, and a test fails if they go stale. No recorded
demo ends at a labelled deposit address, so `deposit_label` has no fixture; the
index lists it under `kinds_without_a_recorded_example`. Don't invent one: record
a real trace that reaches a "Dep" label and re-run the script.
