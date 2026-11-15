# Handoff: label-quality

- **Feature**: the exchange label files name only cash-out wallets, attribute firms' accounts to the exchange that holds them, and mark closed exchanges so no letter is addressed to one as if it could answer
- **Issue**: #208
- **Branch**: `fix/label-quality` (part 1), `fix/label-defunct` (part 2, stacked on part 1)
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: merged: part 1 in #212, with part 2 (#213), on 2026-11-15

## Done

- Part 1 (`fix/label-quality`): `scripts/clean_exchange_labels.py` removed 2 token contracts (BUSD on BSC, Kanga Exchange Token on Ethereum) and 5 infrastructure addresses (7 rows), attributed 9 firm-account rows to the exchange that holds them, and dropped the ChangeNOW instant-exchanger seed row that is now HTX's. `firm_account()` (exchange_matcher.py) lets the letter name the firm as the account holder. Fixed the doc drift: CoinDCX left `_unverified_pending`, and the tron_tags docstring now says 68 labels. The guard tests are in `tests/test_label_quality.py`.
- Part 2 (`fix/label-defunct`): `data/exchange_status.json` lists 16 exchanges that have closed or are closing, each with a source. `scripts/mark_exchange_status.py` adds "(defunct)" or "(winding down)" to their labels. `request_letters.py` addresses a defunct exchange's letters to its administrator, liquidator or successor, and a winding-down exchange's letters carry a send-before-it-closes note.

## Decisions

- Token contracts are found with the repo's own check (`never_flag.tokens`), on every chain, every time the cleaner runs. A keyless `eth_getCode` probe of every non-deposit EVM label (15 Nov) found no other ERC-20 contract.
- The rows removed are named in each file's `_meta.review_2026_11_15`, each with its reason.
- Kept on purpose: Deposit Funder, Eth2 Depositor, Kraken MANA Token Wallet and Batch Transfer wallets. Each is the exchange's own wallet, so a trace that ends there names the right company. The importers already refuse such tags, so none come back from a new import.
- Defunct status is looked up by exchange name, so a case stored before the label said "(defunct)" is caught too.

## Next

1. Owner: confirm the defunct list (see Open questions) and whether to keep the tracker-sourced entries.
2. When BitMart (31 Jan 2027) and CoinEx (22 Dec 2026) close, change `status` to `defunct` in `data/exchange_status.json` and run `scripts.mark_exchange_status`.

## Open questions

- Bilaxy, ABCC and Catex are not marked: no source says they closed (Sidhyarth).
- 5 entries rest only on exchange-listing sites (Allbit, Bgogo, Coinbene, Kryptono, TopBTC). Keep them or drop them? (Sidhyarth)

## Files mid-change (do not touch)

- none
