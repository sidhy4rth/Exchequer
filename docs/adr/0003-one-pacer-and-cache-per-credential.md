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
