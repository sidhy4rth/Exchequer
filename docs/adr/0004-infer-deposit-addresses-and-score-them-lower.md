# ADR-0004: Infer deposit addresses, and score them lower

**Date**: 2026-09-15
**Status**: accepted
**Deciders**: Sidhyarth

## Context

Most cash-outs do not land on a labelled exchange hot wallet. They land on an
unlabelled *deposit address* that the exchange later sweeps. That deposit
address is the one a lawful request has to name; a hot wallet receives from
thousands of customers and identifies nobody.

## Decision

`app/deposit_inference.py` calls an unlabelled wallet a probable deposit
address of exchange E when it made at least two outgoing transfers and every
one went to the same labelled E wallet and nowhere else. An inference scores
0.5 for match directness instead of 1.0, is marked `attribution_inferred`, and
the report prints the evidence and the sentence that would confirm it.

## Alternatives Considered

### Only exact label matches
- **Pros**: never wrong about ownership.
- **Cons**: names the hot wallet, which is useless in a request letter.
- **Why not**: it answers the question nobody asked.

### Treat an inference like a label
- **Why not**: it can be wrong, and the score must say so.

## Consequences

### Positive
- The letter names the address the exchange can act on.
- Where the explorer's own deposit-address label is held (24,018 Bitget and Binance addresses), the match is exact instead.

### Negative
- An exchange's own consolidation wallet has the same shape (harmless: same owner).

### Risks
- A person who genuinely sent everything, twice, to one hot wallet would be misnamed. Measured: 0 false positives on 48 control wallets.
