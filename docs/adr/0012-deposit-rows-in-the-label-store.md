# ADR-0012: A store exchange row may be a deposit address, if it says why

**Date**: 2026-11-15
**Status**: accepted (amends [ADR-0011](0011-exchange-rows-in-the-label-store.md))
**Deciders**: Sidhyarth

## Context

ADR-0011 put exchange rows (an address an exchange publishes as its own) into
the store's `exchange_rows` table, and allowed only one type,
`exchange_wallet`: "the list names the exchange's own wallets, never a
customer's deposit address". That assumption was wrong for OKX.

- **Tron.** A keyless TronGrid sample of 30 of OKX's 474,529 Tron
  proof-of-reserves (PoR) addresses (15 Nov 2026, issue #264): 22 hold dust
  and forward every token transfer they made to
  `TLaGjwhvA8XQYSxFAcAXy7Dvuue9eGYitv`, which the Tron label file already
  names "OKX Hot Wallet 8"; the other 8 had made no outgoing transfer.
- **Ethereum.** The release's on-chain classification of OKX's 17,046
  Ethereum PoR rows found 236 that look like OKX's own wallets, 5,207 that
  look like swept deposit addresses, 9,667 unswept ones (nonce 0, a small
  balance: low confidence) and 1,936 it could not class.

A PoR file lists every address whose key the exchange holds, and the exchange
holds the keys of the deposit addresses it issues to customers. Being listed
shows that the exchange controls an address, not that the address is the
exchange's own wallet rather than one customer's.

The type decides the letter. With `EXCHEQUER_STORE_EXCHANGE_ROWS` on, a trace
stops at such an address and the report says "the exchange's own wallet (not
one customer's account)". The letter then asks OKX about the transactions and
for no customer details, which says more than OKX's list does. With the flag
off, the trace goes one hop further to the hot wallet, and deposit inference
(ADR-0004) calls the address a probable OKX deposit and asks OKX to name the
customer. That is the right letter. The row's `attribution_basis` (which list,
and its dates) was also printed nowhere: not in the report, the letters or the UI.

## Decision

1. **Two types, each stated per row.** A store exchange row is either
   - an **own-wallet row**: `exchange_wallet` (as in ADR-0011), read exactly as
     before (the exchange's own wallet; a JSON label of type `hot_wallet`,
     `cold_wallet` or `contract_wallet` is unaffected too); or
   - a **deposit row**: `deposit_wallet`, held only with its basis in the row:
     `sweeps_to` (the wallet it swept to), `sweep_tx` (the hash of one such
     sweep) and `checked_on` (the date the builder read it). `sweeps_to` must
     be a wallet the chain's curated label file names as the *same* exchange's
     hot, cold or exchange wallet (or a contract wallet in one of those roles),
     the same destinations deposit inference accepts. A PoR listing alone is not
     enough for this, because the listing is the claim being checked.
     `backend/scripts/add_store_exchange_rows.py` refuses the whole CSV if a
     `deposit_wallet` row has no basis. It leaves out (and lists) a row whose
     `sweeps_to` is not such a wallet, and an own-wallet row that states a sweep.
     The basis is kept in a second optional table, `exchange_deposits`, beside
     `exchange_rows`. `schema_version` stays 1, for ADR-0011's reasons, and a
     store without that table reads as before. A `deposit_wallet` row with no
     basis row is never read.
2. **A deposit row means "probable deposit at <exchange>; ask the exchange to
   name the customer"**, never "the exchange's own wallet". Its match takes the
   path a deposit inference takes: `wallet_type` `inferred_deposit`, scored
   lower (ADR-0004), `attribution.kind` `deposit_inferred`, and the report
   kind "a probable deposit address (inferred: only the exchange can confirm
   it)". The letter asks the exchange to confirm the address is a deposit
   address it issued and, if so, for the account holder. The trace stops
   there, as at any exchange address: it is the address a request must name.
   To the never-flag rules it is a deposit address (`never_flag.DEPOSIT`), as a
   labelled one is: store risk rows on it are hidden, and an issuer's freeze
   on it stands, because the issuer acted on one account.
3. **The basis is shown.** For every match read from a store exchange row, the
   report's FINDING and the exchange letter state what it stands on: the list
   (id, URL, publication and retrieval dates, SHA-256), and for a deposit row
   the sweep (`sweeps_to`, `sweep_tx`, `checked_on`). It travels as
   `matches[].attribution_basis` (`kind`, `source`, and for a deposit row
   `deposit`; contract change, `docs/contracts/case.md`).
4. **What the builder emits.** A row from an exchange's published list is
   `exchange_wallet` only when the builder's own check classes it as the
   exchange's wallet (as the Ethereum classification's `exchange_wallet`
   class does). It is `deposit_wallet` only with an observed sweep, as in (1).
   A row with neither, such as a listed address that never sent anything
   (Tron's 8 of 30, Ethereum's 9,667 "unswept" and 1,936 "unclassified"), is
   not added. A trace that reaches one then finds no attribution there. That
   costs coverage, never a wrong claim, which is ADR-0006's trade. A row typed
   `exchange_wallet` before this ADR and not classified since (the 474,529 OKX
   Tron rows in `labels-2026-11-15`) must be classified again before the flag is
   turned on.

Everything here is behind `EXCHEQUER_STORE_EXCHANGE_ROWS`, which stays off.
With the flag off, no trace, report or letter changes.

## Alternatives Considered

### Keep exchange rows own-wallet only, and leave deposits to inference
- **Pros**: no change; inference already writes the right letter when it fires.
- **Why not**: the trace stops at a listed address, so inference never sees
  it, and the letter claims the address is OKX's own wallet. Leaving all
  deposit-shaped rows out of the store gives the same letter as the flag off,
  but drops the list's evidence that OKX controls the address.

### A deposit marker in the label text only
- **Why not**: the report and letters read a deposit from the type
  (`report.derived_kind`), not from a store row's label, so the letter would
  still call a customer's address the exchange's own.

### Type the row `deposit_wallet` and read it as a labelled deposit
- **Why not**: a labelled deposit ("one customer's account") is the
  explorer's own deposit-address label, a stronger claim than a sweep the
  builder saw. The row is evidence for an inference, so it is scored and
  worded as one.

### Store the basis as text in `texts`
- **Why not**: the reader loads every text into memory, and each deposit row's
  sweep is unique (hundreds of thousands of strings on a 512 MB host). The
  basis is kept as raw bytes in its own table, as `labels` keeps a sample tx.

## Consequences

### Positive
- A letter about a listed deposit address asks the exchange for the customer,
  as one about an inferred deposit does, and says what the claim stands on.
- An issuer's freeze on a listed deposit address is shown, not refused.

### Negative
- The release pipeline must classify each PoR row on chain before adding it,
  and rows that cannot be classified are left out.

### Risks
- An exchange's own consolidation wallet that sweeps to its hot wallet looks
  like a deposit (as with ADR-0004). It is harmless, because the owner is the
  same and the letter only asks the exchange to confirm.
- The `labels-2026-11-15` store holds OKX's Tron rows typed `exchange_wallet`
  from before this decision. Turning the flag on with that store would make the
  overclaim this ADR is about, so the flag needs a store built under (4).
