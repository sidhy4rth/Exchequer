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
| `intake.payments[]` | list | One entry per transfer into the reported wallet: `tx_hash`, `chain`, `asset`, `amount`, `from`, `to`, `block`, `timestamp`, `found_by` (`victim` or `officer_search`, as stated by the requester; not checked by Exchequer). A hash that carried several transfers has one entry for each, with `leg` (0, 1, …); `leg` is absent on a one-transfer payment. Count distinct `tx_hash` values for the number of payments. Empty in address mode. `from` (the victim's wallet), `tx_hash`, `block` and `timestamp` are null unless the case is read by the browser that traced it: a payment's hash, block or time leads a block explorer to the victim's wallet. `amount` is always given. |
| `intake.payments[].payer_label` | string or null | The sender's label when a label file names it: an exchange wallet (the victim withdrew from an exchange account) or a router or other contract. Payment mode only. |
| `intake.payments[].payer_is_victim` | bool or null | Whether the sender is the victim's own wallet given with the complaint (`intake.victim_address`); null when none was given. A payment from another wallet also adds a warning to the case, naming no address. Payment mode only. |
| `intake.ncrp_ack` | string or null | The NCRP complaint acknowledgement number as entered by the requester (10 to 20 digits), when known. Null unless the case is read by the browser that traced it (`backend/app/case_privacy.py`). |
| `intake.case_ref` | string or null, only when traced signed in | The case a signed-in officer traced under (an FIR, NCRP or GD number, as entered; `backend/app/case_refs.py`), required of an officer and never kept for a demo caller. Null unless read by the browser that traced it or an officer of its unit. |
| `intake.victim_address` | string or absent | The victim's own paying wallet, when the complaint gives it (`victim_address` with `POST /trace`). A particular of the complaint, like `from`: never printed in the report, and null unless the case is read by the browser that traced it. |
| `redacted` | list, only when something was withheld | The fields emptied for this reader: `intake.ncrp_ack`, `intake.victim_address`, `intake.payments[].from`, `intake.case_ref`, and on a payment case also `intake.payments[].tx_hash`, `.block` and `.timestamp`, `statement.credits` (its incoming rows list the same transfers and their senders), `statement.window_start` and the reported wallet's `graph.nodes[].window_start` (the first payment's time), and the payment hashes and first-payment date quoted in `warnings`. The reports, graph exports, letters and job status are made from the same redacted copy. A case link still opens the case for anyone holding it, since letters print the case id. |
| `reported_amount` | number or null | What the victim paid, in the traced asset: the sum over every entry in `intake.payments`. **Null in address mode**: nobody reported an amount, so nothing may be described as "the reported funds". |
| `attribution` | object or null | What the exchange address is. Null when the trace reached no exchange. |
| `attribution.kind` | see below | Whether the exchange can tie the address to a customer. |
| `attribution.source` | `label_file`, `inference`, `live_tag` | Where the attribution came from: a label file, the deposit-sweep inference, or an explorer tag read at trace time (TronScan). Independent of the kind. |
| `attribution.exchange`, `.address`, `.label` | strings | As in the v1 `exchange`, `exchange_address`, `exchange_label`. |
| `attribution.wallet_type` | string or null | The matcher's own type (`hot_wallet`, `cold_wallet`, `exchange_wallet`, `contract_wallet`, `deposit_wallet`, `inferred_deposit`), kept so nothing is lost. |
| `attribution.depth` | int or null | Hops from the reported address. |
| `estimates.prorata` | number or null | Pro-rata estimate of the traced funds reaching the exchange (the v1 `prorata.estimated`). |
| `estimates.fifo`, `.libr` | number or null | FIFO (money leaves in the order it arrived) and LIBR (the victim's money leaves only when the balance falls below it), R4. Filled only when the flag `EXCHEQUER_TRACING_METHODS` is on and the wallets' windows could be read in full; null otherwise and in older cases. The per-wallet working is in `tracing_methods` (v1-style, beside `prorata`); worked examples in `backend/app/tracing_methods.py`. |
| `estimates.conservative` | number or null | The smallest available estimate across the three methods. **The figure a letter states.** With the flag off it equals `estimates.prorata`. Every method starts from at most `reported_amount` on a payment trace, and at most `follow_ons[].cap.amount` on a follow-on (`prorata.seed_cap`), and the letter applies the same cap to an older case. |
| `transfers[].block` | int or null | The block the transfer is in. Filled for every new trace; null in cases stored before v2. |
| `transfers_total`, `transfers_omitted`, `transfers_sha256` | int, int, string; absent in older cases | The appendix lists at most `EXCHEQUER_TRANSFERS_APPENDIX_MAX` (2,000) transfers: every one out of (on a reverse trace, into) the reported address, on the route to the exchange and into each matched or inferred exchange address, then the largest of the rest by value, in time order. `transfers_total` is how many the trace had, `transfers_omitted` how many are not listed, and `transfers_sha256` the SHA-256 over all of them: one JSON line per transfer (`json.dumps(row, sort_keys=True, separators=(",", ":"))`, the fields `hash`, `from`, `to`, `value_native`, `timestamp`, `internal`, `block` as the trace produced them, before `log_index` is added), joined by `\n`, in time-then-hash order. |
| `transfers[].log_index` | int or null | A token transfer's event position in its transaction. **Null in a trace, by design**: none of the providers' transfer lists (Etherscan `tokentx`, NodeReal, TronGrid TRC-20) returns it, and reading every receipt would roughly double a trace's API calls. Identify a transfer by `hash`, `from`, `to` and `value_native`; `verify_case` (R18, Lane B) may fill `log_index` from the receipt of each transfer a letter cites. |
| `matches[].category`, `inferred_deposits[].category`, `graph.nodes[].exchange_category` | string, absent or null | `instant_exchanger` when the wallet is a no-KYC swap service's (`data/instant_exchangers.json` or a label-store row), or a deposit address that sweeps into one; absent (null on a node) for an ordinary exchange. Additive: a case stored before it reads as an ordinary exchange. |
| `victim_flow` | object or null | Where the victim's share went on every branch the trace followed (`backend/app/victim_flow.py`), for the case's Flow view. `version` is the build that made it (`victim_flow.VERSION`, an int). `status` is `estimated`, `not_applicable` (a reverse trace; or, with a `reason`, an outgoing trace in which the reported wallet sent nothing the trace saw) or `unavailable` (with a `reason`). An estimated flow has `nodes[]` (`address`, `role`, `victim_in`, `share`, `basis`, `left`), `links[]` (`source`, `target`, `gross`, `victim`, `style`: `solid`, `dashed` for an upper bound or an inferred deposit, `faded` for a diluted share), `buckets[]` (`kind` is `exchange`, `instant_exchanger` (a no-KYC swap service, or a deposit address that sweeps into one; its `action` is `draft_letter` too), `held`, `left`, `risk`, `beyond_limit`, `not_followed` or `other`, with `amount`, `share`, `addresses`, `action` and `bounded_amount`, the part of `amount` that came through a wallet whose share is an upper bound; not the same as the `dashed` links, since an inferred deposit's link is dashed without being a bound), which add up to `totals.denominator` within the rounding of the stored amounts (a gap that small is not money left in a wallet); `held` is money at a wallet its issuer froze or that was seized, while money at a sanctioned wallet is `left` there, `lead` (`path`, the route to the exchange, and `reached`, what arrived along it), `passed_through[]` (frozen, sanctioned or seized wallets the money passed through), `notes[]` and `stops[]`, where the trace stopped following the money and why: `kind` is `hop_limit` (wallets at `max_depth`), `fanout_limit` (money `untraced` or a fan-out reason left unfollowed), `mixer`, `bridge` or `privacy` (the money ends there, in the `risk` bucket), `exchange`, `instant_exchanger`, or `no_outflow` (a wallet the walk read that sent nothing on), with `addresses`, `amount` (the victim's share that stopped there), a plain-English `note` ("The trace stopped at 2 hops.") and `inferred`: true only on an `exchange` or `instant_exchanger` stop for probable deposit addresses (inferred, not confirmed), which is listed apart from a labelled exchange's and says so in its note. **A display only: letters and the score state `estimates.conservative`, never these figures.** A new trace stores one built from every transfer it saw, before the appendix is trimmed. A case or `follow_ons[].result` stored without one, or with an older `version`, gets one built on read (`upgrade`, `GET /trace/{id}` from the copy that reader may see, `GET /demos/recorded/{n}`) from the case as stored, whose transfers may be trimmed; the stored case is never rewritten. A current flow the case carries is kept. |
| `risk_matches[].frozen_on`, `.event_tx` | string or null, on a `frozen` match | The day the issuer froze the address (ISO date, from its label: "USDT frozen by Tether on 2026-09-11") and the hash of the freeze event (from its source: "…AddedBlackList event, tx …"). Null where the label or source does not say, as for a label-store freeze, whose "sample tx" is a transfer, not the freeze. A new trace records both; a case stored before them gets them on read (`upgrade`, `GET /trace/{id}`, `GET /demos/recorded/{n}`), and what a match already says is kept. |
| `graph.nodes[].expanded` | bool | Whether the walk read the wallet's transfers (its outflows; its inflows on a reverse trace). True at a service contract (WETH, a pool, a router): the walk read its payouts and then did not follow them. False at the depth limit, at an end of the walk (an exchange, a mixer pool) and where the read failed. A new trace records it; a case stored before it gets it on read where the case can tell, and goes without it on a node the clock, a budget or the node cap may have left unread. |

Each trace in `follow_ons[].result` (the money after a swap) is a full v2 case
of its own, with its own `attribution` and `estimates` in its own asset.
Its figures are capped by `follow_ons[].cap`: `swap_output` is what every swap
by that wallet into that asset returned (`swaps` of them, listed in
`follow_ons[].swaps` when more than one), and `amount` is that, or, when the
traced money can have been only part of the `swap_input` (`traced_in` of it,
`share`), that share of it (`basis` `swap_share`). `share` is null where the
reported wallet of an address-only trace swapped itself.

Two v1-style fields hold the working behind these figures; read them as data,
they are not typed by the model. `tracing_methods` (R4) is FIFO's and LIBR's
per-wallet working, null when the flag is off. `untraced` (R5) lists, per
address, the value the walk did not follow: `{address, counterparties,
value_native, share_of_outflow, rule}`, where `rule` is `top_n` (the ten
largest destinations, the default) or `min_share` (flag
`EXCHEQUER_TAINT_EXPANSION`). An empty list means nothing above dust was left
behind. A report that states where the money went should state this too.

What a trace cost and what stopped it (v1-style, read with `.get`, absent in
older cases): `provider_units` is, per provider, `{requests, units, unit,
case_limit}` for this trace's own network requests (follow-ons report theirs;
`units` are compute units on NodeReal, requests elsewhere; cache hits cost
nothing; `case_limit` is the whole case's, follow-ons included).
`api_calls` is the total of those requests (in cases stored before November
2026 it counted addresses read), and `addresses_read` how many addresses'
transfers were fetched: a level is read in batches and stops at the node cap,
so at most one batch is read past it.
`stopped_by` is `"time"` or `"budget"` when the clock or a request budget cut
the trace short, and `addresses_unexpanded_by_budget` counts the addresses a
budget left unread; `truncation_reasons` names the budget either way.

A read that stopped at its record limit (Etherscan's page, the 1,000-record
scan on Tron and NodeReal; zero-value spam counts toward both) sets
`history_capped: true` on that `graph.nodes[]` entry and adds a "history read
limit at …" reason to `truncation_reasons`, so a trace that read nothing it
could follow never says the address sent nothing.

A transfer from an address to itself moves nothing, so it is never an edge or
a branch: each `graph.nodes[]` entry carries `self_transfer_count` and
`self_transfer_value_native` (0 when none, absent in older cases) instead,
and the report lists where they were ignored.

`provenance` (v1-style, optional, read with `.get`) is what the trace ran with,
so a report rendered after a deploy can say so (`backend/app/provenance.py`):
`tool_version`, `captured_at`, `lists` (for each screening and label list: its
`file`, `sha256` and the `_meta` dates the report prints), `label_store`, and
`settings` (`follow_swaps`, `max_follow_ons`, `live_tags`, `tx_intake`,
`taint_expansion`, `tracing_methods`). Absent in cases stored before it; their
reports say their version and lists were not recorded.

## Attribution kinds

| `kind` | What it is | What a request letter can ask |
|---|---|---|
| `deposit_label` | A deposit address the checked label file names as the exchange's (for example Etherscan's "Bitget Dep" tags, imported into it). Never from a live explorer tag. | The account holder, KYC and statement for that address. |
| `deposit_inferred` | An unlabelled address whose every outflow swept to one exchange wallet: probably a customer deposit address. | First, whether the exchange issued the address; then the same as above. |
| `exchange_wallet` | The exchange's own wallet: hot, cold, a contract, or a label that doesn't say which. It belongs to no customer. | **Not** KYC for the wallet. List the transfers by hash, amount and time, and ask which customer accounts they were credited to. |

A `live_tag` source means the address was attributed from the explorer's tag at
trace time, not from a checked label file: the letter asks the exchange to
confirm the address is theirs before anything else. Its `kind` is always
`exchange_wallet`, even when the tag reads "Deposit" (`wallet_type` keeps
`deposit_wallet`): an explorer's word never supports a request for the
customer. The report calls this pair `explorer_tag`.

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
