"""No "Frozen by <issuer>" on shared infrastructure, whichever file or store row says it.

Stablecoin issuers block token contracts, DEX pools and mixer contracts
defensively. On 14 Nov 2026 the curated frozen_labels files held 106 such
contracts and the released store 27 more, so a trace through a Uniswap pair
read "Frozen by Tether". never_flag.freeze_refusal() now refuses a freeze at
lookup time, for a curated file's entry and a store row alike, on:

  * a token contract, DEX router, burn address or exchange's own wallet;
  * a shared contract in data/never_frozen.json (the 14 Nov review).

Each class below is checked both ways: the infrastructure stays silent, and a
real frozen wallet from the same files still reads frozen.
"""
from __future__ import annotations

import csv
import json
import sqlite3

import pytest

from app import config, label_rules, never_flag
from app.label_store import CHAIN_IDS, LabelStore, encode_address
from app.risk_matcher import FROZEN, RiskMatcher
from scripts import import_tether_freezes as freezes
from scripts.build_label_store import build

from conftest import addr

# Real addresses, each from the file named. Freezes on all of them are on chain;
# showing one on a trace is the false positive.
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"             # token contract, never_flag_tokens.txt
CHI = "0x0000000000004946c0e9f43f4dee607b0ef1fa1c"              # token contract (Chi Gastoken), never_frozen.json
UNI_PAIR = "0x50b6071561f068963bcfe2b341126cd6accafafb"         # Uniswap V2 pair, never_frozen.json
UNI_PAIR_STORE = "0x8c1c499b1796d7f3c2521ac37186b52de024e58c"   # Uniswap V2 pair the 14b store holds
METAMASK_ROUTER = "0x881d40237659c251811cec9c364ef91dc08d300c"  # router_labels.json
TORNADO_GOVERNANCE = "0xffbac21a641dcfe4552920138d90f3638b3c9fba"  # Tornado protocol contract, never_frozen.json
TORNADO_ARB_POOL = "0x1e34a77868e19a6647b1f2f47b51ed72dede95dd"    # ETHTornado pool on Arbitrum, never_frozen.json
BINANCE_14 = "0x28c6c06298d514db089934071355e5743bf21d60"       # exchange_labels.json: hot wallet
JUSTSWAP = "TVE2XCeDRqbLQQQhbcp6g6vit52zLgYzzT"                 # JustSwap V1 exchange on Tron, never_frozen.json
# Genuine frozen wallets: an EOA in frozen_labels.json (GAZA NOW, demo 7) and one in frozen_labels_tron.json.
FROZEN_EOA = "0x21b8d56bda776bbe68655a16895afd96f5534fed"
DEPOSIT = "0x000f9f5f6db6d63bb64bb55d58272a1ce660fd90"          # exchange_labels.json: one customer's deposit

INFRASTRUCTURE = [
    ("ethereum", WETH, never_flag.TOKEN),
    ("ethereum", CHI, "token contract"),
    ("ethereum", UNI_PAIR, "DEX pool"),
    ("ethereum", UNI_PAIR_STORE, "DEX pool"),
    ("ethereum", METAMASK_ROUTER, never_flag.ROUTER),
    ("ethereum", TORNADO_GOVERNANCE, "mixer protocol contract"),
    ("arbitrum", TORNADO_ARB_POOL, "mixer pool"),
    ("ethereum", BINANCE_14, never_flag.EXCHANGE),
    ("tron", JUSTSWAP, "DEX pool"),
]


def _freeze(token="USDT", issuer="Tether"):
    return {"category": FROZEN, "entity": f"{issuer} ({token} freeze)", "label": f"{token} frozen by {issuer}",
            "source": f"{token} contract, freeze event"}


@pytest.mark.parametrize("chain, address, why", INFRASTRUCTURE)
def test_infrastructure_refuses_a_freeze(chain, address, why):
    assert never_flag.freeze_refusal(chain, address) == why


@pytest.mark.parametrize("chain, address", [("ethereum", FROZEN_EOA), ("ethereum", DEPOSIT),
                                            ("ethereum", addr("f00d")), ("arbitrum", FROZEN_EOA)])
def test_a_wallet_or_deposit_address_keeps_its_freeze(chain, address):
    assert never_flag.freeze_refusal(chain, address) is None


def test_a_listed_contract_is_refused_only_on_its_own_chain():
    # The Arbitrum pool address means nothing on Polygon: a contract address is per chain.
    assert never_flag.freeze_refusal("polygon", TORNADO_ARB_POOL) is None


# -- a curated file's entry ----------------------------------------------------
@pytest.mark.parametrize("chain, address, why", INFRASTRUCTURE)
def test_a_curated_freeze_on_infrastructure_is_not_shown(chain, address, why):
    matcher = RiskMatcher({address: _freeze(), FROZEN_EOA: _freeze()}, chain=chain)
    assert matcher.lookup(address) is None
    assert matcher.lookup(FROZEN_EOA)["category"] == FROZEN  # the wallet beside it still fires


def test_a_curated_freeze_on_a_deposit_address_is_shown():
    assert RiskMatcher({DEPOSIT: _freeze()}, chain="ethereum").lookup(DEPOSIT)["category"] == FROZEN


def test_the_guard_drops_only_the_freeze_not_another_list_on_the_same_contract():
    # A mixer label on a Tornado contract still ends the trace.
    mixer = {"category": "mixer", "entity": "Tornado Cash", "label": "Tornado.Cash: Governance", "source": "x"}
    assert RiskMatcher({TORNADO_GOVERNANCE: mixer}, chain="ethereum").lookup(TORNADO_GOVERNANCE)["category"] == "mixer"


# -- a store row ---------------------------------------------------------------
FIELDS = ["address", "chain", "category", "entity_or_incident", "sources", "source_refs", "date",
          "exchequer_supported_chain"]


@pytest.fixture
def freeze_store(tmp_path):
    """A store with one freeze row, copied onto each address under test, as an older build might hold them."""
    placeholder = addr("c17c1e")
    src = tmp_path / "freezes.csv"
    with open(src, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerow({**dict.fromkeys(FIELDS, ""), "address": placeholder, "chain": "ethereum",
                    "category": "stablecoin freeze", "entity_or_incident": "USDC frozen by Circle",
                    "sources": "USDC contract freeze events (on-chain replay)"})
    build(src, tmp_path / "freezes.db")
    db = sqlite3.connect(tmp_path / "freezes.db")
    for chain, address, _ in [*INFRASTRUCTURE, ("ethereum", FROZEN_EOA, None)]:
        db.execute("INSERT OR REPLACE INTO labels SELECT ?, ?, category, entity, label, peer, tx, date, source, tier "
                   "FROM labels WHERE address=?", (encode_address(address), CHAIN_IDS[chain], encode_address(placeholder)))
    db.commit()
    db.close()
    return LabelStore(tmp_path / "freezes.db")


@pytest.mark.parametrize("chain, address, why", INFRASTRUCTURE)
def test_a_store_freeze_on_infrastructure_is_not_shown(freeze_store, chain, address, why):
    assert freeze_store.lookup(chain, address) is None
    assert RiskMatcher({}, chain=chain, store=freeze_store).lookup(address) is None


def test_a_store_freeze_on_a_wallet_is_shown(freeze_store):
    meta = RiskMatcher({}, chain="ethereum", store=freeze_store).lookup(FROZEN_EOA)
    assert meta["category"] == FROZEN and meta["origin"] == "label_store"


# -- the shipped data ----------------------------------------------------------
def test_the_never_frozen_list_is_well_formed_and_names_no_one():
    path = config.DATA_DIR / never_flag.NEVER_FROZEN_FILE
    text = path.read_text()
    assert not label_rules.INTERNAL_NAMES.search(text)
    document = json.loads(text)
    chains = [k for k in document if k != "_meta"]
    assert chains and all(c in config.CHAINS for c in chains)
    for chain in chains:
        assert len(never_flag.never_frozen(chain)) == len(document[chain]) == document["_meta"]["counts"][chain]
        for address, entry in document[chain].items():
            assert entry["kind"] and entry["freeze"] and entry["found_in"], address


@pytest.mark.parametrize("chain", ["ethereum", "tron"])
def test_no_shipped_freeze_is_one_the_guard_refuses(chain):
    # The importer and the run-time guard read the same rules, so the file never holds a refused entry.
    labels = json.loads(config.CHAINS[chain].frozen_labels_path.read_text())["labels"]
    assert {a: why for a in labels if (why := never_flag.freeze_refusal(chain, a))} == {}
    assert FROZEN_EOA in labels or chain == "tron"


def test_the_importer_moves_a_listed_shared_contract_to_excluded():
    wallet = addr("f00d")
    kept, excluded, review = freezes.leave_out("ethereum", {UNI_PAIR: _freeze(), CHI: _freeze(), wallet: _freeze()})
    assert set(kept) == {wallet} and review == []
    assert excluded[UNI_PAIR]["why"] == "DEX pool" and excluded[CHI]["why"] == "token contract"
