# Judge Q&A — fifteen questions and the answers the repo can back

Every answer below is grounded in code that is in the repository or a number
that was measured in it. Sources for the factual claims are in
[RESEARCH.md](RESEARCH.md); the measurements are in the README section
*Validation against real wallets* and regenerate with one command. If a
question goes beyond what is written here, the honest answer is "we have not
measured that" — say so.

---

**1. You point out money laundering. What research supports that?**

Two kinds. For the *claims*, RESEARCH.md lists each statement the README makes
and the primary source read for it: Chainalysis measured stablecoins at 63% of
illicit transaction volume in 2024 and 84% in 2025; TRM Labs put 58% of 2024
illicit volume on Tron; the UN Office on Drugs and Crime calls USDT on Tron the
"preferred choice" of the Southeast-Asian cyber-fraud industry; the peel chain
was named by Meiklejohn et al. at IMC 2013. For the *rules*, we built a corpus
of 40 wallets publicly documented as fraud proceeds and 48 ordinary wallets,
traced all of them with the real pipeline, and published how often each rule
fires on each. Where the README used to say more than the sources support —
"dominant cash-out rail for Indian scam proceeds" — it now says less.

**2. How do you know a flagged wallet is laundering and not normal use?**

We do not, and the tool never says it is. A pattern finding is a fixed
arithmetic shape — four or more recipients, 90–102% of the inflow passed
straight through, no recipient taking more than 60% — and the README and every
report call it a reason to look closer, never a verdict. The measurement shows
why that wording is necessary: the same shape appears within three hops of 11%
of ordinary high-volume wallets. What the tool establishes with confidence is
different and narrower: that funds reached a wallet published in an exchange
label file, which is an exact match a human can re-check.

**3. What is your false-positive rate?**

Measured, not guessed. On 47 ordinary active wallets — funds, mining pools,
charities, payment processors, OTC desks — traced three hops deep, the
amount-split rule at its current thresholds fired on 5 (11%), and at the
thresholds we shipped with a week ago it fired on 19 (40%), which is why the
thresholds changed. The peel-chain rule fired on 2, both mining-pool payouts.
The deposit-address inference fired on 0 of 48. Exchange attribution itself is
an exact match against a published label, so its false-positive rate is the
label file's error rate; every label was verified on chain before entry, and
four wrongly labelled contracts were removed by that check.

**4. And the true-positive side — how often does it catch the launderer?**

On 32 active wallets documented as holding fraud or theft proceeds, the amount
split fired on 6 and the peel chain on 2. We report that plainly rather than
tuning until it looks good. Two things temper it: a wallet documented as
*holding* stolen funds is not thereby documented as laundering them in one of
these two shapes, so this is not recall against ground truth; and 19 of those
32 wallets reached a labelled exchange within three hops, which is the finding
that actually matters for a lawful request. If asked: 35 of the 47 ordinary
wallets reached one too. Reaching an exchange is not a sign of fraud — almost
everyone's money passes through one — it is the *attribution* the tool exists
to make once a wallet has been reported. The fraud is established by the
complaint; the tool establishes where the money went.

**5. What did you validate against, and can we check it?**

`backend/data/validation/corpus.json`: 20 addresses from the OFAC SDN list
(Lazarus Group and other designated individuals), 17 carrying Etherscan's own
"Phish / Hack" label, and the three WazirX-hack attacker addresses named in
CloudSEK's write-up, against 48 controls from the same pinned public label
dataset our exchange importer uses. Every address was fetched by script from
the source recorded on it and checked on chain for contract bytecode; none
was typed by hand. Every provider response is snapshotted, so
`python -m scripts.validate_patterns` reproduces the table offline in seconds.

**6. Why did you change the thresholds — isn't that fitting to your data?**

Partly, and the README says so. The original values flagged 40% of ordinary
wallets, which is unusable in a report that names people. We moved to the grid
point with the fewest control firings that still fired on any positive, and
wrote down that it is an estimate from 79 wallets. No point in the 68-point
grid brought control firings to zero. The honest conclusion is that these two
shapes do not by themselves separate illicit from legitimate high-volume
activity, and the tool's design already assumed that: patterns are caveats,
they never move the confidence score.

**7. What happens when the funds hit a mixer?**

The trace stops and says so. A tumbler pays out from a commingled pool, so a
transfer leaving it has no established link to the deposit that arrived;
following it would manufacture a trail. That stop is a correctness rule, not a
limitation, and it is tested. Tornado Cash left the OFAC list in March 2025 and
every mixer OFAC still lists is a Bitcoin service, so the mixer list is built
from Etherscan's own tags instead: 40 pools and routers on Ethereum, 14 on BSC
(Tornado Cash, Typhoon, Privacy Pools). The alert names that source, not a
government. DEMO.md trace 6 is a live hit: 10 ETH into Tornado Cash, three hops
out.

**8. Why not Bitcoin?**

Because the evidence points at stablecoins on account-based chains: 84% of
illicit volume in 2025 was stablecoins, and the largest share by chain in 2024
was Tron. Bitcoin uses a different transaction model (unspent outputs and
change addresses) and needs its own adapter; the README lists it as the first
item on the upgrade path rather than pretending the current code covers it.

**9. Why not machine learning?**

Because a conclusion that reaches a courtroom has to be one an officer can
re-check by hand from public transaction data. Every attribution is an exact
lookup in a file you can open; every pattern finding prints the thresholds it
applied and the amounts it compared. A model score cannot be cross-examined,
and a false accusation is the expensive failure here. We also now have the
measurement that would be needed to train one, and it shows the labelled
corpora are small and the shapes overlap — a model trained on them would
overfit and hide that.

**10. What if the exchange is not in your list?**

Then the trace returns `exchange: null` with a message, never a guess.
`GET /exchanges` shows exactly what is covered — 20,047 Ethereum addresses
(1,020 exchange wallets across 92 exchanges plus 19,027 Bitget customer deposit
addresses), 38 on BSC and 41 on Tron, every one read from the explorer's own
label and checked on chain. The new deposit-address inference narrows the gap from the
other side: when an unlabelled wallet's entire outgoing history is sweeps into
one labelled hot wallet, the tool names it as a *probable* deposit address of
that exchange, scores it lower than a label match, and says what would confirm
it. Adding a label is a script that fetches from the explorer and verifies on
chain — CoinDCX (29 wallets on Ethereum, and BSC) and Delta Exchange were added
that way; WazirX and ZebPay were not because no source met the standard.

**11. How would this be used under PMLA?**

A cyber-fraud complaint starts at the state police or the National Cyber Crime
Reporting Portal; the Enforcement Directorate opens a PMLA case on the
predicate FIR. Since the notification of 7 March 2023, exchanges are reporting
entities that must register with FIU-IND and keep records that "enable it to
reconstruct individual transactions" and identify the customer (PMLA s.12).
The ED obtains those under s.50; state police by notice. Exchequer's output is
the input to that request: the deposit address, the transaction hashes,
amounts and times, in a form the exchange's compliance team can match. The
report says on every attribution that only the exchange can link an address
to a person.

**12. What is the biggest thing it gets wrong?**

Until this week, time. It followed every transfer a wallet ever made,
including ones made before the victim's money arrived, so a busy wallet's
unrelated history could be reported as where the victim's funds went. That is
fixed and tested: only transfers at or after the traced funds arrived are
followed. A swap from ETH to USDT or USDC at a labelled DEX router no longer
ends the trail: the stablecoin is traced onward from the moment of the swap as
a linked trace, each keeping its own score. The biggest remaining gap is that
the fan-out limit follows the ten largest recipients, so a launderer who sends the real
money as the eleventh-largest transfer is not followed. Both are in the
README's Limitations.

**13. Can a launderer defeat it?**

Yes, and the README lists how: split into eleven or more outputs, swap into
the native coin or an obscure token (a swap into USDT or USDC is now followed),
bridge to a chain we do not cover, or use a wallet with more than
200 transfers so the relevant one is beyond what we read. We document these
rather than hide them because the tool's value is in what it *can* establish
cheaply and reproducibly, and an investigator has to know where its edge is.

**14. How confident is the confidence score, and why is it sometimes null?**

It is a plain weighted sum of three inputs — distance in hops (40%), how much
of the value survived the route (35%), and whether the match was a label or an
inference (25%) — and the report prints all three with their explanations.
Patterns and truncation never change the number; they are printed beside it.
It is null, not zero, when nothing was attributed, because a zero would read as
"we are sure this is worthless" about a trace that may have mapped ten
candidate victims perfectly well.

**15. How big is the problem you are addressing?**

By the Ministry of Home Affairs' own figures, tabled in the Lok Sabha on
2 December 2025: citizens reported losses of ₹2,290 crore to cyber fraud in
2022, ₹7,465 crore in 2023 and ₹22,845.73 crore in 2024, from 2.27 million
incidents on the National Cyber Crime Reporting Portal that year. An
Enforcement Directorate case reported in July 2026 traced ₹303 crore from fake
job, investment and gaming scams through 216 mule accounts into cryptocurrency
and froze 160,339 USDT. Those are the cases this tool is built to start.
