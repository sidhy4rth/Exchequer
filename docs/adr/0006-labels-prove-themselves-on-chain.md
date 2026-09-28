# ADR-0006: No address is accepted on its label alone

**Date**: 2026-09-22
**Status**: accepted
**Deciders**: Sidhyarth

## Context

Public label sets are noisy. An exchange's name appears on its token
contracts, its DEX router and unrelated registry entries. A trace that "reaches
OKX" through the OKX DEX router has found a trade, not a deposit.

## Decision

Every candidate proves itself against live chain data before it enters a label
file (`backend/scripts/import_eth_labels.py` and the other importers): an
exchange wallet must have received value, and a second pass rejects anything
with contract bytecode, since a hot wallet is an externally owned account.

## Alternatives Considered

### Import label sets as published
- **Pros**: more labels, less work.
- **Why not**: one mislabelled router turns a swap into a false attribution.

## Consequences

### Positive
- The 22 Sep import checked 724 Ethereum candidates and accepted 690; the bytecode pass caught three token contracts and the OKX DEX router.

### Negative
- Imports are slow on free keys: every candidate costs live requests. The large deposit-address imports are resumable from a checkpoint for that reason.

### Risks
- A dormant but real exchange wallet with no inbound value is left out. That only costs coverage, never a wrong answer.
