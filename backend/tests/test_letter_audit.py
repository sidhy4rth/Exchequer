"""What the pre-ship audit of the letters found, each pinned so it stays fixed.

The urgent freeze letter and the information letter that follows it go to
the same compliance team, so they must name the same transactions. A letter
must never ask to hold "about 0" of anything, never call an address frozen
that the freeze list now excludes, never leave a numbered paragraph empty,
and never ask Tether to freeze USDT at a wallet the walk never read.
"""
from __future__ import annotations

import copy
import re

import pytest

from app.request_letters import BLANK, LetterNotApplicable, available, draft

from test_freeze_letters import DEMOS, SEED, node, one_line, stopped_case

HASH = re.compile(r"\btx (?:0x)?([0-9a-f]{64})\b")
CARRY = ("38ef314819abff3f5c448da6de769fad80821ae06a26f15a8fd134e1645fbdba",  # 19 Dec 2024
         "821965673662c740fe8b51126bc3dd3e6d53047f2282f7def00ee750c748f974")  # 24 Dec 2024
ROUTER = "0x881d40237659c251811cec9c364ef91dc08d300c"  # MetaMask Swap Router: frozen_labels.json _meta.excluded
DEMO3_END = "0xc6aafd1238694e165bf82ce50a5bff879e822177"
DEMO3_TX = "0x6e60845518b36c8ccce7b3bac7cbc6a753dcb853ed4ce38e2e109d23b2999e31"


# -- the information letter to an exchange-run wallet ------------------------------------
def test_demo_11s_information_letter_names_only_the_transfers_its_freeze_letter_names():
    info = draft("case-1", DEMOS[11], "exchange")
    freeze = draft("case-1", DEMOS[11], "exchange-freeze")
    into = info[info.index("3. The transfers"):info.index("4. In exercise")]
    hot = into[into.index("Hop 2"):]
    assert set(HASH.findall(hot)) == set(HASH.findall(freeze)) == set(CARRY)
    assert "ddcaeacc39f740712c31cee205ed1f8c93b01cec67dcf4207a6983183902ada1" not in info  # 635 already covered
    assert "e92795864f33580eb583e9c54839d8c4ea1ad35642eb4d5533a370df979cc1e5" not in info  # Dec 2025
    assert "25 other transfers into it in this trace are not part of this request" in one_line(info)
    assert "behind each transaction listed in paragraph 3" in one_line(info)


def test_a_hot_wallet_letter_still_lists_every_transfer_when_each_can_carry_the_funds():
    text = draft("case-1", DEMOS[9], "exchange")
    assert "not part of this request" not in text
    assert "Every transfer into" in text


# -- a smallest estimate of zero ---------------------------------------------------------
def zero_11(**figures):
    result = copy.deepcopy(DEMOS[11])
    result["estimates"] = {"fifo": 0.0, "prorata": 635.0, "libr": 10.0, "conservative": 0.0, **figures}
    result["tracing_methods"] = {"conservative": 0.0, "conservative_method": "fifo",
                                 "range": {"low": 0.0, "high": 635.0}}
    return result


@pytest.mark.parametrize("to", ["exchange-freeze", "tether-freeze", "exchange"])
def test_a_zero_smallest_estimate_is_never_stated_the_smallest_non_zero_one_is_named(to):
    flat = one_line(draft("case-1", zero_11(), to))
    assert "about 0.000000" not in flat and "about 10.000000 USDT" in flat
    assert "LIBR" in flat and "FIFO" in flat  # which rule gave it, and which gave none


def test_with_a_zero_smallest_estimate_the_hot_wallet_freeze_still_lists_the_carrying_transfer():
    text = draft("case-1", zero_11(), "exchange-freeze")
    assert CARRY[0] in text and CARRY[1] not in text  # 10 USDT: the first transfer covers it
    assert "(officer to add)" not in text


def test_when_every_estimate_is_zero_the_amount_is_the_officers_to_state():
    flat = one_line(draft("case-1", zero_11(prorata=0.0, libr=0.0), "exchange-freeze"))
    assert f"Amount : {BLANK} (officer to state)" in flat and "0.000000 USDT" not in flat


def estimates_only_11(**figures):
    """A case stored before tracing_methods was kept: its estimates alone."""
    result = zero_11(**figures)
    del result["tracing_methods"]
    return result


@pytest.mark.parametrize("to", ["exchange-freeze", "exchange"])
def test_a_case_with_estimates_alone_names_the_rule_that_found_none(to):
    flat = one_line(draft("case-1", estimates_only_11(), to))
    assert "about 10.000000 USDT" in flat and "LIBR, the smallest estimate that finds any" in flat
    assert "FIFO finds none" in flat and "another tracing rule" not in flat


def test_when_two_rules_find_none_the_letter_names_both():
    flat = one_line(draft("case-1", estimates_only_11(libr=0.0), "exchange-freeze"))
    assert "about 635.000000 USDT" in flat and "FIFO and LIBR find none" in flat


# -- a freeze the list now excludes -------------------------------------------------------
def test_demo_3s_tether_letter_no_longer_calls_the_swap_router_frozen():
    text = draft("case-1", DEMOS[3], "tether")
    assert ROUTER not in text and "AddedBlackList" not in text


def test_an_excluded_freeze_alone_supports_no_tether_letter():
    excluded = {"address": ROUTER, "category": "frozen", "label": "USDT frozen by Tether on 2021-08-05",
                "source": "Tether USDT contract on Ethereum, AddedBlackList event"}
    result = copy.deepcopy(DEMOS[3])
    result["follow_ons"] = []
    result["risk_matches"] = [excluded]
    assert all(letter["to"] != "tether" for letter in available(result))
    with pytest.raises(LetterNotApplicable):
        draft("case-1", result, "tether")


# -- a USDT trace with no route ----------------------------------------------------------
def test_demo_3s_tether_letter_says_where_the_follow_on_usdt_went():
    text = draft("case-1", DEMOS[3], "tether")
    assert DEMO3_END in text and DEMO3_TX in text and "5,215.000000 USDT" in text
    assert not re.search(r"as follows:\n\n", text)


def test_a_usdt_trace_that_went_nowhere_says_so_rather_than_leaving_a_blank_paragraph():
    text = draft("case-1", stopped_case([node(SEED)]), "tether")
    assert "the trace did not follow it further" in one_line(text)
    assert "as follows:" not in text


# -- only wallets the walk read are where the USDT stopped ----------------------------------
def test_a_wallet_at_the_depth_limit_is_not_where_the_usdt_stopped():
    edge, read = "T" + "e" * 33, "T" + "r" * 33
    result = stopped_case([node(SEED, out=30.0, depth=0), node(read, into=10.0, depth=1, expanded=True),
                           node(edge, into=20.0, depth=2)])
    result["max_depth"] = 2
    text = draft("case-1", result, "tether-freeze")
    assert read in text and edge not in text


# -- every blank says what goes in it ------------------------------------------------------
@pytest.mark.parametrize("demo", sorted(DEMOS))
def test_every_blank_in_an_information_letter_says_what_goes_in_it(demo):
    for letter in available(DEMOS[demo]):
        if letter["to"] == "exchange":
            text = draft("case-1", DEMOS[demo], "exchange")
            assert "pending this investigation [" not in text
            if "consider restricting withdrawals" in text:
                assert "(officer to state the period, or the order it is sought under)" in text
