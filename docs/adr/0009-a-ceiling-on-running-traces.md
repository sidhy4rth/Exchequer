# ADR-0009: A ceiling on traces running at once

**Date**: 2026-09-28
**Status**: accepted
**Deciders**: Sidhyarth

## Context

The hosted site is public and has to answer whenever a judge opens it. Each
trace holds a worker thread for as long as it takes, minutes on a busy wallet,
and `POST /trace` had no limit, so a handful of simultaneous requests could
leave the next visitor waiting on a site that looked down.

## Decision

A server-wide semaphore in `app/routes/cases.py` lets four traces run at once
(`EXCHEQUER_MAX_RUNNING_TRACES`). Past that, the request is answered 429 at
once with `Retry-After: 30` and a message the console shows as-is. The slot is
released whether the trace succeeds or fails.

## Alternatives Considered

### Per-IP rate limiting
- **Why not**: a room of judges on one college network shares an IP, and would lock each other out.

### Queue the extra requests
- **Why not**: a queued request looks exactly like a hung site.

## Consequences

### Positive
- Stored cases, the console and /health stay responsive under load.

### Negative
- A fifth simultaneous investigator is asked to wait.

### Risks
- Four is a guess for one small Railway instance; the environment variable changes it without a deploy of new code.
