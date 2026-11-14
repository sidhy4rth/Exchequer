# Custody procedure: holding seized crypto in a multisig wallet

A plain checklist for the officer who moves seized crypto into the unit's
custody wallet and, later, out of it. Exchequer keeps the record of every step
(suite feature 9: the custody wallet panel on a case's Letters tab, under the
asset register). It never holds a key: no field takes one, and none should be
typed anywhere.

This is a working procedure, not legal advice. Where it says "the court order",
follow the order the court actually made in the case, and your unit's standing
instructions.

## Rules that apply at every step

- [ ] **Two-person rule.** No step that touches seized funds is done by one
      officer alone. Two named officers are present for every setup, deposit
      and release. Exchequer records who set the wallet up, who proposed each
      movement and each signer's approval; write down anyone else present in
      your unit's own record.
- [ ] **Never photograph, type or copy a seed phrase.** Not into Exchequer, a
      phone, an email, a chat, a document or a cloud note. A seed phrase is
      written only on the recovery sheet that comes with the hardware wallet,
      by hand, and sealed.
- [ ] **No private key ever leaves its hardware wallet.** Approvals are signed
      on the device itself. If any software asks you to paste a key or seed,
      stop.
- [ ] **Record every step in Exchequer as it happens,** not afterwards from
      memory: who did it, when, the amount and the transaction hash.
- [ ] **Nothing moves out of custody without the court order.** Its reference
      goes into the release record before anyone signs.

## 1. Set up the custody wallet (once per unit, or per case if the court directs)

- [ ] Decide the threshold with your supervisor: **m of n**, with m at least 2
      (Exchequer refuses 1) and n large enough that one lost device or one
      absent officer does not lock the funds (for example 2 of 3, or 3 of 5).
- [ ] Get **n new hardware wallets**, still sealed, bought through the unit.
      Note each device's serial number on paper.
- [ ] Assign each device to **one named officer**. Each officer initialises
      their own device in front of a second officer, writes its recovery
      phrase by hand on the device's recovery sheet, and seals the sheet in a
      tamper-evident envelope signed across the seal by both officers.
- [ ] Store each sealed envelope separately from its device, in the place your
      unit's instructions name. Record where on paper, not in Exchequer.
- [ ] Create the multisig with those n devices as its owners and the agreed
      threshold, using the chain's multisig scheme (for example a Safe on an
      Ethereum-family chain, or a multi-sign permission on Tron). Whether the
      officer who proposes a transaction may also count as a signer depends on
      the scheme and on your unit's choice; note which.
- [ ] Check the wallet's address on each device's own screen, not only on a
      computer screen.
- [ ] In Exchequer, open the case, Letters tab, **Custody wallets**, and choose
      **Record a custody wallet**: the chain, the address, the scheme as you set
      it up, the threshold, each signer by name, role and unit, who set it up
      and the day. Names only.

## 2. Test with a small amount first

- [ ] Before moving any seized funds, send a **small test amount** into the
      wallet and record it as a deposit.
- [ ] Propose a release of the test amount back out, collect the threshold of
      approvals on the signers' devices, broadcast it, and check it confirms.
      Record each step. This proves the signers can actually sign before real
      money depends on it.
- [ ] If anything fails, stop and fix the setup before any seized funds move.

## 3. Move seized funds in (deposit)

- [ ] Two officers present. The officer holding access to the seized funds
      sends them to the custody wallet's address, checked on the receiving
      devices' screens.
- [ ] In Exchequer: **Propose a deposit or release**, choose **Deposit into the
      wallet**, choose who proposed it (one of the signers, or someone else
      where the scheme keeps proposing apart from signing), the asset and the
      exact amount.
- [ ] Once sent, record the **transaction hash**; once final on chain, mark it
      **Confirmed on chain**.
- [ ] In the asset register, record the seized amount as held in the custody
      wallet with the same transaction, and link that row to the wallet.

## 4. Release on the court order

- [ ] Read the court order. Check the amount, the asset and the destination it
      names.
- [ ] In Exchequer: propose a **Release on the court's order** with the
      destination address, the exact amount and the **court order reference**
      (Exchequer refuses a release without one).
- [ ] Each signer checks the destination and amount **on their own device's
      screen** against the court order before signing. Record each approval as
      it is given: Exchequer counts each signer once and refuses a signer the
      scheme does not allow.
- [ ] When the threshold is reached, broadcast the transaction and record its
      hash; once final on chain, mark it **Confirmed on chain**.
- [ ] In the asset register, record the outcome with the same transaction.

## 5. If something goes wrong

- [ ] A proposal that should not go ahead: **Cancel** it with the reason. A
      cancelled movement cannot be approved or broadcast again; propose a new
      one.
- [ ] A lost, damaged or compromised device, or a signer who leaves the unit:
      tell your supervisor at once. Move the funds to a new custody wallet
      with a fresh set of devices, using the steps above, and record the new
      wallet in Exchequer.
- [ ] A suspected exposure of a recovery phrase: treat the wallet as
      compromised and move the funds the same way, as soon as the threshold of
      signers can be gathered.
