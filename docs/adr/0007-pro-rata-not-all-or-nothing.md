# ADR-0007: Pro-rata estimates, not all-or-nothing taint

**Date**: 2026-09-23
**Status**: accepted
**Deciders**: Sidhyarth

## Context

A path shows *that* money ran from the reported address to an exchange, not
*how much* of what arrived was the victim's. 40 USDT of a victim's can join
961 USDT from elsewhere and leave as 1,001.50; saying "1,001.50 reached
Binance" overstates the claim by 25 times.

## Decision

`app/prorata.py` carries the victim's share forward at every wallet on the
path: share = victim funds in ÷ all funds in (read from the chain for the
window, not just the transfers the trace followed); victim onward = amount
sent on × share. The result is shown as its own figure, feeds the amount
correlation part of the score, and a share under 25% at any wallet is called
out. Where a wallet's incoming history could not be read in full, the case
says "not estimated" instead of guessing.

## Alternatives Considered

### Poison (all-or-nothing) taint
- **Pros**: simple; any contact taints everything downstream.
- **Why not**: it inflates amounts in exactly the mixed-funds cases that matter.

### FIFO / LIFO ordering
- **Why not**: needs a full balance history per wallet, which free keys cannot afford, and is no easier to check by hand.

## Consequences

### Positive
- The letters carry a defensible amount. On the demos it changed nothing where money moved cleanly and lowered the scores of the diluted paths, among them two of DEMO.md trace 10's three phishing wallets.

### Negative
- Money a wallet held before the funds arrived is not counted, so the estimate is an upper bound.

### Risks
- A very busy intermediate wallet cannot be read in full; that path reports "not estimated" rather than a wrong number.
