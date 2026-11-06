# ADR-0003: One request pacer and response cache per API key

**Date**: 2026-09-15
**Status**: accepted
**Deciders**: Sidhyarth

## Context

On the free tiers a trace is slow because it waits on the provider, not
because of anything Exchequer computes. Etherscan's free key answers roughly two
useful requests a second however hard it is asked; pushing harder turns
answers into "max rate limit reached", each costing a backoff. Two traces with
their own throttles together doubled the rate and got the key limited.

## Decision

`app/api_budget.py` keeps one `SharedPacer` and one `ResponseCache` per
credential, process-wide. The pacer is adaptive: it widens on refusal and
recovers slowly on success. Repeat lookups of the same address are answered
from the cache.

This covers every provider, not only Etherscan: NodeReal, TronGrid (keyed, or
"anon" per server without a key) and TronScan each share one pacer per
credential. NodeReal meters compute units per second, so its pacer weighs each
request by its cost (250 CU for a transfer read, 5 for the block number) between
`NODEREAL_CUPS_FLOOR` and `NODEREAL_CUPS`. The cache bounds itself in bytes
(memory and disk) and keeps each entry for as long as that kind of answer stays
true: a day for a closed block range, minutes for a read up to the chain's tip,
never for `latest` state such as a balance.

NodeReal and TronGrid answers are cached too, each in a smaller byte-bounded
cache shared by every key. NodeReal's block windows end on multiples of
100,000, so the same range is the same request from one trace to the next; a
window below the indexed head keeps the day, the one at the head minutes. A
TronGrid read is cached whole (every page it took) or not at all, because a
fingerprint belongs to the read that made it: a settled time range keeps the
day, a read up to the newest records minutes.

## Alternatives Considered

### A fixed interval per client
- **Pros**: simple.
- **Cons**: even a nominally safe 2.9 req/s drew refusals, because the limit is enforced in bursts.
- **Why not**: no constant is right for a limit you cannot see.

### A paid API tier
- **Why not**: the project runs on free tiers only.

## Consequences

### Positive
- Concurrent traces share the budget instead of fighting over it.
- Demo addresses traced once are near-instant afterwards; startup warms them.

### Negative
- The cache can serve slightly old chain data within its lifetime.

### Risks
- A cache on the volume survives redeploys, which is the point, but it has to be cleared by hand if a provider returned bad data.
