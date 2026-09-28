# ADR-0005: The demo sign-in is not access control

**Date**: 2026-09-17
**Status**: accepted (supersedes the earlier officer access code)
**Deciders**: Sidhyarth

## Context

On stage the console needs a threshold to cross: an investigator door and a
citizen door. A real login would need accounts, a user store and password
handling that a demo does not justify. The earlier access code with an HMAC
cookie was removed at my request.

## Decision

`frontend/src/session.js` remembers, per browser tab, which demo door was
passed (admin/admin, user/user). It is front-end only and the README says so.
Chain of custody comes from evidence hashing and the sealed report, not from
knowing who clicked.

## Alternatives Considered

### Real authentication
- **Why not**: accounts and password handling for a demo is cost with no benefit, and a half-done login is worse than an honest none.

## Consequences

### Positive
- No secrets to manage, nothing to break before a demo.

### Negative
- Anyone can use the console and add cases. That is acceptable for a public demo and would not be for a deployment holding real case files.

### Risks
- Someone mistaking it for security. Mitigated by saying plainly in the code and the README that it is not.
