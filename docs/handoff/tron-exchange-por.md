# Handoff: Tron exchange labels from proof-of-reserves lists

- **Feature**: a Tron trace that reaches a wallet an exchange publishes as its own (proof of reserves) names that exchange
- **Issue**: #217
- **Branch**: `feat/tron-exchange-por`
- **Current**: nobody
- **Last worked on**: Sidhyarth, 2026-11-15
- **Status**: first set of sources imported; merged in #221 on 2026-11-15

## Done

- `backend/scripts/import_por_tron_labels.py`: reads a downloaded PoR file per source (`SOURCES`), keeps the Tron rows,
  and adds each address that is a valid Base58Check address, an activated non-contract account on chain (TronGrid
  `wallet/getaccount`, keyless, 1 request a second, backs off on the rate-limit answer), not labelled as another
  exchange, and not on a frozen, sanctions, risk, gambling or demo list or in a test. Rows carry `source: "por:..."`;
  `_meta.proof_of_reserves.sources` holds URL, archive copy, published and retrieved dates, SHA-256 of the file read,
  what the source calls the addresses, and the corroborated and left-out lists.
- OKX's file signs every address ("I am an OKX address"); for that source, rows with a signature and a positive
  balance stand on that evidence, and a reproducible random sample (`--sample`, default 150) is checked on chain.
  One failed sample stops the source.
- `seed_tron_labels.py` now keeps `por:` rows and the `proof_of_reserves` section when it rewrites the file.
- 15 Nov: merged main (India labels, #135) by re-running the importer on main's file from the same four downloaded
  files (SHA-256s unchanged), never by hand. `tests/test_tron_tags.py` and `tests/test_tron_tag_proof.py` now use
  `TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf` (unlabelled, from `test_tron_cache.py`) as their unlabelled wallet, so the
  importer added `TMuA6YqfCeX8EhbfYEg5y7S4DqzSJireY9` (Binance, Nov 2022 blog): 52 PoR rows, 134 Tron labels.

## Decisions

- PoR lists never say hot or cold per address in these sources, so rows are `exchange_wallet`, never `deposit_wallet`.
- Label text `"<Exchange>: Reserves Wallet (<yyyy-mm>)"`, so every row still reads as its exchange to
  `tron_tags.exchange_for_tag` (a test requires it of every row in the file).
- An address TronScan already tags as the same exchange keeps its TronScan row (listed as corroborated).

## Next

1. OKX: its 1 Nov 2026 file (`por_csv_2026110100_V1.zip`, 111 MB, SHA-256 93095583…367a6) lists 474,530 Tron
   addresses, every one signed. In this JSON file that is 91 MB and 2.85M lines, and the loader took 11 s and kept
   220 MB (353 MB peak) of a 512 MB host, so the rows are NOT in this PR. The parser, spot check and source entry
   are. Needs an owner decision on storage: e.g. a sorted list of 21-byte raw addresses (about 10 MB, binary search),
   or the label store with an exchange-wallet category. Then run the importer with `--file por:okx:2026-11=<zip>`
   writing to that store instead. Dry run on 15 Nov: on-chain spot check 149 of 149 active (1 no answer); 5 left
   out because they appear in `recorded_demos.json` (re-record that demo when OKX is imported).
2. Bitget, Gate and MEXC: no machine-readable address list found. Bitget's page no longer lists addresses (its
   `queryReserveWalletDetailList` API is unused by the page and refuses guessed parameters); Gate and MEXC answer
   automated clients with a bot check (not bypassed). A person can download each list in a browser and add a
   `SOURCES` entry plus a parser.
3. EVM addresses in the same Bybit and HTX files: issue #215.

## Open questions

- Owner: keep 2022 lists (Binance, KuCoin blog posts) as sources, or only lists from the last 12 months?

## Files mid-change (do not touch)

- none
