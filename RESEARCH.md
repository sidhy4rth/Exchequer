# What the README claims, and what the sources actually say

Exchequer's pitch is that every attribution can be traced to a published label
file. This document applies the same standard to the *claims* the README makes
about laundering: each one is listed with the source that supports it, the exact
passage, and a verdict. Where the README said more than the evidence supports,
the README has been rewritten to say what the sources say.

Rules followed here: every source below was fetched and read during the session
of 15 September 2026, and the quoted passages are copied from the document, not
paraphrased from memory. Two primary sources could not be retrieved (marked as
such); where that happened a secondary source that was read is cited instead,
and it is labelled secondary. Nothing is cited that was not read.

Verdicts: **supported** · **partially supported (README overstated)** ·
**not supported**.

---

## Claim 1 — "Most laundering moves as stablecoins rather than native currency"

**Source A.** Chainalysis, *2026 Crypto Crime Report — Introduction*, 8 January
2026. <https://www.chainalysis.com/blog/2026-crypto-crime-report-introduction/>

> "stablecoins have come to dominate the landscape of illicit transactions, and
> now account for 84% of all illicit transaction volume"
>
> "illicit cryptocurrency addresses received at least $154 billion in 2025 …
> This represents a 162% increase year-over-year (YoY), primarily driven by a
> dramatic 694% increase in the value received by sanctioned entities"

**Source B.** Chainalysis, *2025 Crypto Crime Trends*, 15 January 2025.
<https://www.chainalysis.com/blog/2025-crypto-crime-report-introduction/>

> "stablecoins now occupying the majority of all illicit transaction volume
> (63% of all illicit transactions)"

**Source C.** TRM Labs, *2026 Crypto Crime Report — Key Insights*, 10 January
2026. <https://www.trmlabs.com/resources/blog/2026-crypto-crime-report-key-insights-trm-identifies-record-usd-158-billion-in-illicit-crypto-flows-in-2025-reversing-a-multi-year-decline>

> "Inflows to sanctioned entities were predominantly using stablecoins."
> "Stablecoins served as the primary layer for value transfer across sanctioned
> jurisdictions, underground banking networks, and illicit service providers."
> "Top stablecoins included USDT and Russia's ruble-pegged A7A5."

**Source D (secondary — the FATF page itself returned HTTP 403 on every
attempt).** CNP Law, *FATF Identifies Stablecoins as a Major Risk in Illicit Use
of Virtual Assets*, 11 August 2025, summarising FATF's sixth Targeted Update on
Virtual Assets and VASPs of 26 June 2025.
<https://www.cnplaw.com/fatf-identifies-stablecoins-as-a-major-risk-in-illicit-use-of-virtual-assets/>

> "The FATF noted that this trend has continued to grow since the 2024 Targeted
> Update, and that most on-chain illicit activity now involves stablecoins."

**Verdict: supported**, with one honest caveat the README now carries. The
figures are for *illicit transaction volume* as measured by two analytics firms,
and the 2025 jump is driven by sanctioned entities, not by consumer fraud. The
README sentence was rewritten to quote the figures and their scope rather than
to assert "most laundering".

---

## Claim 2 — "USDT-TRC20 on Tron is the dominant cash-out rail for scam proceeds out of India"

**Source E.** UNODC, *Casinos, Money Laundering, Underground Banking, and
Transnational Organized Crime in East and Southeast Asia: A Hidden and
Accelerating Threat*, January 2024, pp. 20 and 65.
<https://www.unodc.org/roseap/uploads/documents/Publications/2024/Casino_Underground_Banking_Report_2024.pdf>

> p. 65: "USDT on the TRON blockchain has become a preferred choice for regional
> cyberfraud operations and money launderers alike due to its stability and the
> ease, anonymity, and low fees of its Transactions."
>
> p. 20, note 26: "As of June 2023, TRON had over 165.5 million total user
> accounts, more than 5.81 billion total transactions, and over US $11.79
> billion in total value locked (TVL), hosting the largest circulating supply of
> Tether (USDT) globally since April 2021."

**Source F.** TRM Labs, *2025 Crypto Crime Report* (covering 2024), p. 6.
<https://cdn.prod.website-files.com/6082dc5b670562507b3587b4/67f7132b33d3535ca28a54a4_TRM_2025%20Crypto%20Crime%20Report.pdf>

> "In 2024, the largest percentage of illicit crypto activity occurred on the
> TRON blockchain (58% of illicit volume), followed by Ethereum (24% of illicit
> volume), Bitcoin (12% of illicit volume), Binance Smart Chain (3% of illicit
> volume), and Polygon (3% of illicit volume), reflecting continued preference
> for blockchains that have low transaction fees, smart contracts, and popular
> stablecoins."
>
> "However, of all the blockchains analyzed, TRON saw the most significant
> decline in illicit volume, dropping by USD 6 billion and halving its proportion
> of illicit volume."

**Source G.** Elliptic, *Typologies Report: Detecting the money flows behind
the global pig butchering ecosystem*, 16 October 2025.
<https://www.elliptic.co/blog/elliptics-typologies-report-detecting-the-money-flows-behind-the-global-pig-butchering-ecosystem>

> "At this stage, the money launderers will send the funds to a VASP, where as
> many as dozens of money mules may be employed to help convert the funds into
> fiat currencies."

**Source H (press coverage of an ED case; no ED press release could be located
on the ED website).** The Week, *ED uncovers ₹303-crore transnational cyber
fraud syndicate; 10 arrested, crypto trail traced to Dubai*, 13 July 2026.
<https://www.theweek.in/news/india/2026/07/13/ed-uncovers-indian-rs-303-crore-transnational-cyber-fraud-syndicate-10-arrested-crypto-trail-traced-to-dubai.html>

> "converted into cryptocurrency using exchanges such as Binance, GetBit and
> Carretx. The cryptocurrency was then transferred to private digital wallets
> allegedly controlled by foreign beneficiaries."
>
> "freezing of around 1,60,339 USDT, 118.73 SOL and 563 ETH"
>
> "The probe was initiated under the Prevention of Money Laundering Act (PMLA)
> in March 2024 on the basis of two CBI FIRs relating to large-scale cyber
> fraud."

**Verdict: partially supported (README overstated).** What the sources
establish: USDT on Tron is the rail the UN describes as the "preferred choice"
of the Southeast-Asian cyber-fraud industry; Tron carried the majority of
measured illicit volume in 2024 and that share halved in 2025; an Indian ED case
against a ₹303 crore cyber-fraud syndicate ended in USDT being frozen. What no
source establishes: a measurement of *India-specific* cash-out rails, or the
word "dominant" for India. The ED coverage names USDT but not the blockchain.
The README sentence was rewritten to say exactly this. The `tron_client.py` and
`config.py` docstrings, which repeated the claim, were rewritten the same way.

---

## Claim 3 — "Peel chains are a known laundering pattern"

**Source I.** S. Meiklejohn, M. Pomarole, G. Jordan, K. Levchenko, D. McCoy,
G. M. Voelker, S. Savage, *A Fistful of Bitcoins: Characterizing Payments Among
Men with No Names*, Proceedings of the ACM Internet Measurement Conference
(IMC'13), Barcelona, 23–25 October 2013, §5.2 and §6.
<https://cseweb.ucsd.edu/~smeiklejohn/files/imc13.pdf>

> "we focus on an idiom of use that we call a 'peeling chain.' The usage of
> this pattern extends well beyond criminal activity, and is seen (for example)
> in the withdrawals for many banks and exchanges, as well as in the payouts for
> some of the larger mining pools. In a peeling chain, a single address begins
> with a relatively large amount of bitcoins … A smaller amount is then 'peeled'
> off this larger amount, creating a transaction in which a small amount is
> transferred to one address … and the remainder is transferred to a one-time
> change address. This process is repeated"
>
> On tracing a theft through peeling chains: "54 out of 300 peels went to
> exchanges alone … the evidence that the deposited bitcoins were the direct
> result of either a Ponzi scheme or the sale of drugs might motivate Mt. Gox or
> any exchange (e.g., in response to a subpoena) to reveal the account owner
> corresponding to the deposit address in the peel"

**Source G again** (Elliptic, 2025): laundered pig-butchering proceeds
"move the funds through dozens of intermediary wallets - a process known as
['chain-peeling']".

**Verdict: supported — with a warning the README now states.** The pattern
and its name come from the 2013 Bitcoin de-anonymisation literature, and
Elliptic still describes it in 2025 as a step in laundering scam proceeds. But
the paper that coined the term says in the same paragraph that the shape
"extends well beyond criminal activity" and is seen in ordinary exchange
withdrawals and mining payouts. Exchequer's rule adapts the idea to an
account-based chain (there are no change addresses on Ethereum or Tron, so
"one-time change address" becomes "single-use intermediate wallet"). **The
numeric thresholds — at most 3 transfers, at least 2 intermediates, at least
50% forwarded per hop, 2% growth tolerance — are this project's own choices and
come from no paper.** Their behaviour on real wallets is measured in the README
section *Validation against real wallets*.

---

## Claim 4 — "Amount split (structuring) is a known laundering pattern"

**Source J.** 31 CFR § 1010.100(xx), U.S. Treasury / FinCEN definitions, read at
<https://www.law.cornell.edu/cfr/text/31/1010.100>

> "a person structures a transaction if that person, acting alone, or in
> conjunction with, or on behalf of, other persons, conducts or attempts to
> conduct one or more transactions in currency, in any amount, at one or more
> financial institutions, on one or more days, in any manner, for the purpose of
> evading the reporting requirements … 'In any manner' includes, but is not
> limited to, the breaking down of a single sum of currency exceeding $10,000
> into smaller sums"

**Source G again** (Elliptic, 2025): funds are moved "through dozens of
intermediary wallets" before reaching a VASP where "dozens of money mules may
be employed".

**Verdict: partially supported (README overstated).** "Structuring" is a
defined legal term about *currency* transactions broken up to evade a
*reporting threshold*. There is no reporting threshold on a public blockchain,
so the on-chain version — one wallet fanning a received sum out across several
recipients — is a laundering *shape* described by analytics firms, not
structuring in the statutory sense. The README and the `pattern_detection.py`
docstring no longer say the split is done "to stay under reporting
thresholds"; they say what is observable: the sum was divided to multiply the
paths an investigator must follow, and the same shape is produced by payroll,
exchanges and market makers. **The thresholds — 3 or more recipients, 50–110%
forwarded, no single recipient above 90% — are this project's own choices.**

---

## Claim 5 — "Laundering hops that matter happen close to the source; past ~4 hops the graph is mostly unrelated exchange traffic" (graph_builder.py)

**No source.** This is an engineering judgement about where to stop a
breadth-first walk, and the docstring now says so. The only related evidence
read is Meiklejohn et al. following peeling chains for 100 hops (Source I),
which shows the opposite can be true on Bitcoin. The depth limit is a cost
control that the README's Limitations section describes as such.

**Verdict: not supported as a claim about laundering; retained as a documented
cost limit.**

---

## Claim 6 — "A mixer pays out from a commingled pool, so its outputs have no established link to a deposit"

**Source I** (Meiklejohn et al., §6) describes mixing services as pooling
inputs so that following the change link no longer follows one user's money;
this is the reason the paper's own peeling-chain tracking stops at them.

**Verdict: supported** at the level the README uses it (a reason to stop the
walk, not a quantitative claim).

---

## Claim 7 — Scale of the problem in India (DEMO.md and JUDGE_QA.md)

**Source K (primary).** Government of India, Ministry of Home Affairs, Lok
Sabha Unstarred Question No. 432, answered 2 December 2025 by the Minister of
State for Home Affairs (Shri Bandi Sanjay Kumar).
<https://www.mha.gov.in/MHA1/Par2017/pdfs/par2025-pdfs/LS02122025/432.pdf>

> "As per NCRP & CFCFRMS operated by I4C, total amount of losses incurred by
> citizens due to cyber frauds in the entire country including Bihar from the
> year 2022 to 2024 are as under: 2022 — 2290.24; 2023 — 7465.18; 2024 —
> 22845.73 (₹ in crore)"
>
> Incidents registered on the NCRP: "2022 1029026 … 2023 1596493 … 2024
> 2268346"

**Verdict: supported** (these figures are new to the project and are quoted
exactly).

---

## Claim 8 — "Tether / exchanges freeze addresses tied to scams" and cooperation with law enforcement

**Source L.** Tether, *T3 Financial Crime Unit Marks Enforcement Victory:
$100 Million in Criminal Assets Frozen Across Five Continents*, 2 January 2025.
<https://tether.io/news/t3-financial-crime-unit-marks-enforcement-victory-100-million-in-criminal-assets-frozen-across-five-continents/>

> "frozen more than $100 million in criminal assets globally" … cases involving
> "money laundering, investment fraud, blackmail operations, terrorism
> financing, and other serious financial crimes" … "Launched in August 2024".

**Source M (press coverage, secondary).** The Crypto Times, *India Police
Seize ₹40L in Tether from Nationwide Fraud*, 30 January 2025, citing the
Hyderabad City Police on X.
<https://www.cryptotimes.io/2025/01/30/india-police-seize-%E2%82%B940l-in-tether-from-nationwide-fraud/>

> "The Hyderabad Police have successfully uncovered a nationwide cyber fraud
> ring" … "the police have also seized the ₹40 lakh worth of Tether".

**Verdict: partially supported.** USDT tied to fraud is frozen at scale by the
issuer on request of law enforcement, and Indian police have seized USDT in
cyber-fraud cases. **No Tether announcement naming an Indian scam specifically
could be found**, so the project makes no such claim.

---

## What the Indian legal framework needs from a tool like this

This section grounds the report's "what would confirm this" language in the
process an investigator actually follows.

**The offence and the agency.** The Prevention of Money-Laundering Act, 2002
(PMLA) is enforced by the Directorate of Enforcement (ED). An ED investigation
is opened on the basis of a predicate offence — in the ₹303 crore case above,
"two CBI FIRs relating to large-scale cyber fraud" (Source H). A cyber-fraud
complaint therefore starts at the state police or the National Cyber Crime
Reporting Portal (Source K), and reaches the PMLA route through an FIR.

**Exchanges are reporting entities.** By a Ministry of Finance notification
dated 7 March 2023, entities providing services in virtual digital assets
(exchange between VDAs and fiat, exchange between VDAs, transfer, custody, and
financial services around issuance) were designated as persons carrying on a
designated business under section 2(1)(sa)(vi) of the PMLA, which makes them
*reporting entities*. Sources read: AZB & Partners, *The Indian Anti-Money
Laundering Regime: New Compliance Obligations Around Virtual Digital Assets*
<https://www.azbpartners.com/bank/the-indian-anti-money-laundering-regime-new-compliance-obligations-around-virtual-digital-assets-2/>;
Oxford Business Law Blog, *Digital Assets & the Indian Anti-Money Laundering
Regime*, July 2023
<https://blogs.law.ox.ac.uk/oblb/blog-post/2023/07/digital-assets-indian-anti-money-laundering-regime>:

> "the Central Government, via a notification dated March 07, 2023
> ('Notification'), has brought activities involving or relating to virtual
> digital assets ('VDA'), including cryptocurrencies and NFTs under the purview
> of the PMLA."

**Registration and the guidelines.** FIU-IND, *AML & CFT Guidelines for
Reporting Entities Providing Services Related to Virtual Digital Assets*,
effective 10 March 2023, §5.1
<https://fiuindia.gov.in/pdfs/AML_legislation/AMLCFTguidelines10032023.pdf>:

> "In terms of Rule 2 (wa) read with Rule 2 (sa) of PMLA, all SPs are required
> to register as Reporting Entities with FIU-IND."

**What the exchange must hold.** PMLA section 12(1), read at
<https://indiankanoon.org/doc/290623/>: every reporting entity shall

> "(a) maintain a record of all transactions … in such manner as to enable it
> to reconstruct individual transactions" … "(e) maintain record of documents
> evidencing identity of its clients and beneficial owners as well as account
> files and business correspondence relating to its clients"

with a retention period of five years (FIU-IND guidelines; AZB summary).

**How an investigator gets it.** PMLA section 50, read at
<https://indiankanoon.org/doc/1395568/>:

> (2) "The Director, Additional Director, Joint Director, Deputy Director or
> Assistant Director shall have power to summon any person whose attendance he
> considers necessary" to give evidence or produce records; (3) "All the
> persons so summoned shall be bound to attend … and shall be bound to state
> the truth".

Outside the PMLA route, state police obtain the same records from a registered
exchange by notice under the criminal procedure code (section 94 of the
Bharatiya Nagarik Suraksha Sanhita, 2023, formerly section 91 CrPC) — this
step is general procedure and is stated here from the investigator's side, not
from a source read in this session.

**What this means for Exchequer's output.** A trace ends at an *address*.
The record that links that address to a person exists only at the exchange,
under section 12, and is obtained under section 50 (ED) or a police notice.
So the sentence the report attaches to every attribution — "an exchange match
identifies where funds arrived, not who controls the account; only the
exchange can link a deposit address to a customer identity, via a lawful
request" — is precisely what the framework provides for. The report's job is
to give the officer the address, the transaction hashes, the amounts and the
times, in a form the exchange's compliance team can match against its own
records. That is why Phase 8 of this work makes the report list every hash.

For an *inferred* deposit address (Phase 2), the same request confirms or
refutes the inference: the exchange either has a customer record for that
address or it does not.

---

## Sources that could not be retrieved

- FATF, *Targeted Update on Implementation of the FATF Standards on Virtual
  Assets and VASPs*, June 2025, and the FATF *Updated Guidance for a Risk-Based
  Approach to Virtual Assets and VASPs*, October 2021 — the FATF website
  returned HTTP 403 to every fetch (HTML page and PDF). A law-firm summary was
  read instead and is labelled secondary above.
- Enforcement Directorate press releases — the ED website's press-release pages
  could not be reached in the session, so ED cases are cited through named
  press coverage.
- Lexology's summary of the FATF update — HTTP 403.
