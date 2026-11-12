# ADR-0010: The team shares context through the repository

**Date**: 2026-11-12
**Status**: accepted
**Deciders**: Sidhyarth, Barenyam

## Context

Two people work on Exchequer, each with their own Claude Code. A Claude
session cannot see another person's conversation, and it forgets its own once
it ends, so anything not written down is lost between sessions. The earlier
setup split the code into three fixed lanes with owners; with two people that
leaves whole areas with nobody to pick them up, and work stalls whenever the
owner of a file is away. And because GitHub counts every `Co-Authored-By`
trailer as a contributor, an AI assistant was one config default away from
the contributors list of a public repository.

## Decision

Everything the team needs to share lives in the repository:

- **`CLAUDE.md` at the root** is the working agreement every session reads.
  Its 11 rules keep their numbers, so old commits that cite them still make
  sense; the lane names are gone from them.
- **No fixed ownership.** Anyone works on any feature, and the team agrees
  priorities between themselves.
- **One handoff file per feature** in `docs/handoff/`, from `TEMPLATE.md`. A
  feature is claimed by putting your name in "Current" and committing that
  before any code. Each session ends by updating the file and pushing.
- **Decisions that reach beyond one feature are ADRs** here, numbered and
  indexed.
- **Commits are people's.** `.github/scripts/check_no_ai_attribution.sh`, a
  step in the "commit e-mails" CI job, fails any new commit whose author or
  committer is an AI assistant, or whose message carries a co-author,
  "generated with" or session trailer for one. A committed
  `.claude/settings.json`, if adopted, stops Claude Code adding those lines in
  the first place.

## Alternatives Considered

### Rely on chat history
- **Why not**: neither person's Claude can read the other's chats, and a
  summary pasted from one into the other is out of date the moment it is sent.

### Keep fixed lanes
- **Why not**: with two people, three lanes means one area has no owner, and
  "stay in your lane" blocks a fix whenever its owner is away.

## Consequences

### Positive
- A fresh session on either machine can tell from the repository what is in
  progress, who is on it, and what to do next.
- The contributors list stays the team, enforced by CI and not by memory.

### Negative
- Two rituals to keep: claim before starting, update the handoff file before
  stopping. A skipped end-of-session update leaves the next person guessing.
- A claim commit before any code adds a small commit to every feature.

### Risks
- A stale "Current" line can block a feature after someone stops without
  clearing it; the fix is to ask that person, not to work around the claim.
