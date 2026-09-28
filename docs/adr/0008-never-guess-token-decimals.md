# ADR-0008: Never guess a token's decimals

**Date**: 2026-09-28
**Status**: accepted
**Deciders**: Sidhyarth

## Context

A token amount is an integer that has to be divided by 10^decimals. USDT is 6
decimals on Ethereum and 18 on BNB Smart Chain. Both token parsers fell back to
18 when a record arrived without its decimals, which would shrink a USDT
transfer to a trillionth of itself and flow straight into the pro-rata figure
and the letters without anything failing.

## Decision

`resolve_decimals` in `app/etherscan_client.py` takes the record's own figure
first, then the traced token's precision confirmed on-chain in `config.py`, and
otherwise drops the record with a warning. The native coin stays 18 by
definition. Tested in `tests/test_token_decimals.py`.

## Alternatives Considered

### Keep the default of 18
- **Why not**: silently wrong by twelve orders of magnitude for the most-traced token.

### Look decimals up on-chain for every record
- **Why not**: an extra request per record on a free key, for a value config already holds.

## Consequences

### Positive
- A missing field can no longer produce a wrong amount; at worst a record is skipped and logged.

### Negative
- A token not in config with a record missing its decimals is dropped rather than shown.
