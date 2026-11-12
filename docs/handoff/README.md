# Handoff files

One file per feature, named `<feature>.md` and copied from
[TEMPLATE.md](TEMPLATE.md). It is how one person's Claude tells the other's
where a piece of work stands, since neither can see the other's conversations.

**Claim rule.** Before starting a feature, check its "Current" line. If it says
"nobody" (or there is no file yet), put your name there, assign yourself the
GitHub issue, and commit and push that first. If it names someone else, do not
work on it; talk to that person.

**Start of a session.** Pull `main`, check open pull requests and this folder,
then read `CLAUDE.md`, the issue and the feature's handoff file. Summarise where
the work stands before writing code.

**End of a session.** Update the file: Done, Decisions, Next, Open questions,
Files mid-change, and "Last worked on". Set "Current" to "nobody" if you are
stopping. Commit and push the branch. Never skip this.
