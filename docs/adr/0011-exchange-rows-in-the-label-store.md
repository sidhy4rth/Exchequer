# ADR-0011: Exchange rows in the label store live in their own table

**Date**: 2026-11-15
**Status**: accepted; amended by [ADR-0012](0012-deposit-rows-in-the-label-store.md) (a row may be a deposit address, if it states its basis)
**Deciders**: Sidhyarth

## Context

OKX publishes, every month, a proof-of-reserves file listing the addresses it
says are its own, each signed with that address's key ("I am an OKX address").
Its 1 Nov 2026 file lists 474,530 Tron addresses. In the JSON label file that
is 91 MB, and loading it held 220 MB of a 512 MB host (PR #221), so the owner
decided (15 Nov) that these rows go into the label store, not the JSON files.

The store's schema (version 1, `backend/app/label_store.py`) has one `labels`
table, one row per address and chain, with a free-text `category`. Adding the
value `"exchange"` would change no column, but it would change what a row
means to every reader that exists today: `LabelStore.lookup` returns any row
that is not an instant exchanger or a mixer as a risk match, so the code now
live (and main before this change) would show an OKX reserves wallet as a
risk flag of category "exchange", the opposite of what the row says. And the
one-row-per-address key means an exchange row and a risk row for the same
address could not both be kept; the build would silently drop one.

## Decision

- Exchange rows (category `exchange`: an address an exchange itself publishes
  as its own) are kept in a separate, optional table, `exchange_rows`
  (address, chain, exchange, label, type, basis, source), never in `labels`.
  `schema_version` stays 1, on purpose and written down here: a store without
  the table reads exactly as before, and a reader older than this change
  never opens the table. `LabelStore.lookup` also never returns a `labels`
  row of category `exchange`, should one ever be written there.
- The table is added to a built store by `backend/scripts/add_store_exchange_rows.py`
  from a CSV of parsed rows. That script refuses a burn or system address, a
  token contract, a DEX router, a casino wallet in a gambling file and any
  address on a never-flag list given to it; an address a source the matcher
  reads first already names (the chain's label file, the instant-exchanger
  seed, a store instant-exchanger row) is left to that source (the same name:
  corroborated; another: a conflict, listed). Every row's type is
  `exchange_wallet` (blank reads as it): the list names the exchange's own
  wallets, never a customer's deposit address, so a CSV with any other type
  is refused whole. The lookup applies the same never-flag refusals again at
  run time.
- The exchange matcher reads the rows behind the flag
  `EXCHEQUER_STORE_EXCHANGE_ROWS` (off by default), in this order: the
  curated JSON files (and the instant-exchanger seed), then a store exchange
  row, then a store instant-exchanger row. JSON always wins.
- Once a store row attributes an address, it is an exchange wallet to every
  existing precedence rule, as a JSON row is (`never_flag.kind` asks the same
  matcher): store risk rows on it are hidden, an issuer's freeze on it is
  refused (`never_flag.freeze_refusal`), and the curated risk files still
  flag it.
- A match read from such a row carries `matches[].attribution_basis`
  (`kind`: "exchange's own published list (PoR)", and `source`: the list's id,
  URL, publication and retrieval dates and the SHA-256 of the file read), so
  a report can say what the attribution stands on (contract change, PR for
  #222).
- ADR-0006 asks every exchange wallet to prove itself on chain. For a row
  OKX signed with the address's own key and listed with a balance, the
  signature shows a key holder (so not a contract) and the balance an account
  that exists; a reproducible random sample (150) is still checked on chain
  before a source is used, and one failure stops the source
  (`import_por_tron_labels.py`).

## Alternatives Considered

### A new category value in `labels`
- **Pros**: no new table; the instant-exchanger rows already live there.
- **Why not**: the live code would read the rows as risk flags, and an
  exchange row would displace a risk row for the same address at build time.

### Bump `schema_version` to 2
- **Pros**: an old reader could not misread the file.
- **Why not**: an old reader refuses a store of another version outright, so
  the image would screen with the JSON files only. A separate table keeps
  both directions working without that.

### A sorted file of raw addresses next to the JSON files
- **Pros**: about 10 MB, binary search.
- **Why not**: a second store format to build, ship and verify, beside the
  one the release pipeline already builds, checks and pins by SHA-256.

## Consequences

### Positive
- OKX's Tron wallets can name the exchange a trace reached, at the cost of
  disk, not memory: one index probe per lookup.
- A store with the table works with the code live today, and the code after
  this change works with the live store (no table: nothing changes).

### Negative
- The store now holds attributions as well as risk rows, so a release must
  be checked for both (the add script's refusals and its report).

### Risks
- Turning the flag on changes the traces that pass these addresses: 5 OKX
  addresses appear in `backend/data/recorded_demos.json`, so that demo is
  re-recorded (by its script) in the same change that turns the flag on.
