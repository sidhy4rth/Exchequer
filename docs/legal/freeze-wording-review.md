# For counsel: the wording of Exchequer's bank-hold notice

Prepared 15 Nov 2026 for an advocate to review. **This is not legal advice and
makes no legal finding.** It sets out what Exchequer's draft says, an
alternative, and the questions we need answered. Check every quotation against
the official text before relying on it.

Exchequer drafts letters for police officers. Every draft says it is not valid
until an officer signs it, leaves the legal provision as a blank for the
officer to fill, and needs a second officer's sign-off before a bank hold is
marked ready. The bank-hold draft is refused unless the officer enters a
Magistrate's order (number, date, court). Code: `backend/app/notice_letters.py`.

## Current wording (live)

> Subject: URGENT — debit freeze on account [no.], pending a formal request
>
> Under [____] (the legal provision this request is made under, officer to state):
> Please place a debit freeze, now, on account [no.] (IFSC [code]) up to the amount below, pending a formal request from this office.
>
> Amount: up to INR [amount] · Order: [officer's text] (copy attached)
>
> Please confirm the hold and the balance held to the contact above.

Our concern: it asks for a "debit freeze" of the account but limits it to an
amount, which mixes two things the courts treat differently (*Kartik Chatur*
para 16: a lien on the disputed amount, not a debit freeze of the account).

## Proposed wording (built, switched off: `EXCHEQUER_FREEZE_WORDING_V2`)

> Subject: URGENT — action on account [no.] under a Magistrate's order, pending a formal request
>
> Under [____] (the legal provision this request is made under, officer to state):
> [e.g. Section 107 of the Bharatiya Nagarik Suraksha Sanhita, 2023, as the order states — officer to confirm]
> Please give effect, now, to the attached order of the Magistrate on account [no.] (IFSC [code]), as that order directs and for no more than the amount below, pending a formal request from this office.
>
> Amount: up to INR [amount] · Order: [officer's text] (copy attached)
>
> Please confirm to the contact above what was done under the order and the balance it covers.

The idea: the order, not the letter, says what the bank must do, so the letter
does not have to choose between "debit freeze", "attachment" and "lien". It
does not offer a police-only route (a hold without a Magistrate's order).

## Questions for counsel

1. Is the proposed wording right for a request that rests on a Magistrate's
   order? Should it instead name the action ("attach", "debit freeze", "lien on
   the amount"), and name the order as one under s.107(1)/(5) BNSS?
2. Is "for no more than the amount below" right when the order covers the whole
   account, or should the amount come only from the order?
3. Is a "hold" or "lien" on a specific disputed amount legally different from a
   "debit freeze" or "attachment"? (*Kartik Chatur* paras 15–16; *Khalsa*
   principle C; *Malabar Gold* para 18.)
4. Does s.168 read with s.94 BNSS support a police direction to hold money, or
   only s.106 (with s.106(3) reporting), or only s.107? Is *Smartpaddle* (Bom
   HC Aurangabad, 30.07.2026) the first decision on this?
5. Does reporting the hold to the Magistrate (s.106(3); *Khalsa* principle D;
   *Archana* guideline II) change the answer?
6. Which High Court's view binds the officers who would use Exchequer? Kerala,
   Bombay and Delhi hold one way; Allahabad and MP allow an amount-limited lien
   by police notice. Is the dismissal of SLP (Crl.) 13433/2025 a merits decision?
7. Is a hold made inside CFCFRMS the same act as a letter Exchequer drafts
   outside the portal? An Exchequer draft is not sent through CFCFRMS.
8. Should Exchequer later add an amount-limited "SOP hold" without a
   Magistrate's order (MHA SOP para 6.1(g), Annexure I), and if so with what
   fields and safeguards?

## Sources (as cited in our research note; levels of checking differ)

- MHA SOP for NCRP-CFCFRMS (bank-hosted copy, read in full): https://www.zoroastrianbank.bank.in/download/SOP-NCRP.pdf; Meghalaya HC notification, 28.04.2026: https://meghalayahighcourt.nic.in/notification-28042026-sop-national-cybercrime-reporting-portal-and-citizen-financial-fraud. Versions differ; use the current one.
- *Kartik Yogeshwar Chatur v. Union of India*, Bom HC Nagpur, Crl. WP 321/2025: https://www.verdictum.in/pdf_upload/kartik-yogeshwar-chatur-v-union-of-india-ors-632526watermark-1756732.pdf
- *Malabar Gold and Diamond Ltd. v. Union of India*, Del HC, W.P.(C) 4198/2025, 16.01.2026 (also the source of the BNSS s.106 and s.107 text used): https://delhihighcourt.nic.in/app/showlogo/1769248155_eb87a6191c1f9386_596_41982025.pdf/2026
- *Khalsa Medical Store v. RBI*, All HC Lucknow, WRIT-C 12211/2025, 19.01.2026: https://www.verdictum.in/pdf_upload/wricl122112025allhc-1767471.pdf
- *Ritesh Yadav v. RBI*, All HC Lucknow, WRIT-C 6602/2026, 6.08.2026: https://www.livelaw.in/pdf_upload/2026/08/14/ritesh-yadav-vs-reserve-bank-of-india-new-delhi-thru-its-governor-and-6-others-2026-livelaw-ab-578-allahabad-high-court-693898.pdf
- *Archana v. State of MP*, MP HC Jabalpur, WP 29117/2026, 27.07.2026: https://www.livelaw.in/pdf_upload/2026/07/28/archana-v-state-of-madhya-pradesh-689886.pdf
- *Pay 10 Services v. Union of India*, Del HC, W.P.(C) 1592/2026, 26.02.2026: https://delhihighcourt.nic.in/app/showFileJudgment/59626022026CW15922026_170735.txt
- *Neelkanth Pharma Logistics v. Union of India*, Del HC, W.P.(C) 17905/2024 (known only as quoted in *Malabar Gold*): https://delhihighcourt.nic.in/app/showFileJudgment/60920022025CW179052024_093911.pdf
- *Headstar Global v. State of Kerala*, Ker HC, Crl.MC 3740/2025 (known only as quoted, and from a report): https://www.livelaw.in/high-court/kerala-high-court/kerala-high-court-rules-police-cannot-freeze-bank-account-section-107-bnss-295027
- *Smartpaddle Technology v. State*, Bom HC Aurangabad, 30.07.2026 (snippets only; holding not found): https://lawtext.in/judgement.php?bid=87834

Not yet obtained: the *Smartpaddle* and *Headstar* judgments, the Supreme Court
record of SLP (Crl.) 13433/2025, the current SOP version, and the BNSS text
from India Code.
