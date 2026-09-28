# Architecture decisions

Short records of the choices that shape Exchequer: what I decided, what I
turned down, and what it costs. Each one is a few minutes' read and points at
the code that carries it out. If you are wondering "why does it do it this
way?", the answer is probably here.

| # | Decision | Date |
|---|---|---|
| [0001](0001-one-image-one-origin.md) | One Docker image serves both the API and the UI | 2026-09-05 |
| [0002](0002-a-stored-case-is-never-re-traced.md) | A stored case is never re-traced | 2026-09-05 |
| [0003](0003-one-pacer-and-cache-per-credential.md) | One request pacer and response cache per API key | 2026-09-15 |
| [0004](0004-infer-deposit-addresses-and-score-them-lower.md) | Infer deposit addresses, and score them lower | 2026-09-15 |
| [0005](0005-demo-sign-in-is-not-access-control.md) | The demo sign-in is not access control | 2026-09-17 |
| [0006](0006-labels-prove-themselves-on-chain.md) | No address is accepted on its label alone | 2026-09-22 |
| [0007](0007-pro-rata-not-all-or-nothing.md) | Pro-rata estimates, not all-or-nothing taint | 2026-09-23 |
| [0008](0008-never-guess-token-decimals.md) | Never guess a token's decimals | 2026-09-28 |
| [0009](0009-a-ceiling-on-running-traces.md) | A ceiling on traces running at once | 2026-09-28 |

New decisions get the next number. A decision that is replaced is marked
superseded rather than deleted, so the history of why stays readable.
