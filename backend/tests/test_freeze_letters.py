"""The urgent freeze letter: "hold these funds now, pending a formal request".

Money reaches an exchange hours after it leaves the victim, so the letter that
can save it is the short one, sent first. It carries only what an exchange or
Tether needs to act -- the wallets, the hashes and their times, the chain and
token, and the one amount an information letter states -- and blanks for
everything that is the officer's. Every letter, of every kind, says plainly
that it is a draft and not valid until an officer signs it on letterhead: an
unsigned Exchequer letter must not pass as a police request.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import config
from app.request_letters import BLANK, LETTERS, NOT_VALID, LetterNotApplicable, available, draft

from test_request_letters import DEPOSIT, PRORATA, SEED, SWAPPER, TX, case, follow_on_case

DEMOS = {d["demo"]: d["result"] for d in json.loads(
    (Path(config.DATA_DIR) / "recorded_demos.json").read_text(encoding="utf-8"))}
METHODS = {"figures": {"fifo": 2000.0, "prorata": 6000.0}, "range": {"low": 2000.0, "high": 6000.0},
           "conservative": 2000.0, "conservative_method": "fifo"}
HOP = "T" + "h0p".ljust(33, "1")
HOP_TX = "cd" * 32


def usdt_case(**over):
    """Tron USDT: reported address -> one plain hop -> a Binance deposit."""
    return case(**{"chain": "tron", "chain_name": "Tron", "asset": "USDT", "prorata": PRORATA,
                   "tracing_methods": METHODS, "estimates": {"fifo": 2000.0, "prorata": 6000.0, "conservative": 2000.0},
                   "trace_path": [
                       {"address": SEED, "depth": 0},
                       {"address": HOP, "depth": 1, "value_native": 9000.0, "tx_count": 1,
                        "first_seen": 1_734_000_000, "last_seen": 1_734_000_000, "tx_hashes": [HOP_TX]},
                       {"address": DEPOSIT, "depth": 2, "label": "Binance Dep", "exchange": "Binance",
                        "value_native": 7000.0, "tx_count": 1, "first_seen": 1_734_011_100,
                        "last_seen": 1_734_011_100, "tx_hashes": [TX]},
                   ],
                   "transfers": [{"hash": TX, "from": HOP, "to": DEPOSIT, "value_native": 7000.0,
                                  "timestamp": 1_734_011_100}], **over})


def one_line(text):
    return " ".join(text.split())


# -- which letters, in which order ----------------------------------------------------
def test_the_freeze_letters_are_offered_first_and_the_information_letters_keep_their_names():
    assert available(usdt_case()) == [
        {"to": "exchange-freeze", "title": "Urgent freeze request to Binance"},
        {"to": "tether-freeze", "title": "Urgent freeze request to Tether"},
        {"to": "exchange", "title": "Request to Binance"}, {"to": "tether", "title": "Request to Tether"}]
    assert LETTERS == ("exchange-freeze", "instant-freeze", "tether-freeze", "exchange", "instant", "tether")


def test_no_exchange_means_no_exchange_freeze_letter():
    result = case(exchange=None, exchange_address=None, trace_path=[])
    assert all(letter["to"] != "exchange-freeze" for letter in available(result))
    with pytest.raises(LetterNotApplicable):
        draft("case-1", result, "exchange-freeze")


def test_eth_without_usdt_offers_no_tether_freeze_letter():
    assert all(letter["to"] != "tether-freeze" for letter in available(case()))
    with pytest.raises(LetterNotApplicable):
        draft("case-1", case(), "tether-freeze")


def test_a_reverse_trace_asks_no_one_to_freeze_where_the_money_came_from():
    result = usdt_case(direction="incoming")
    assert not any(letter["to"].endswith("-freeze") for letter in available(result))
    with pytest.raises(LetterNotApplicable):
        draft("case-1", result, "tether-freeze")


# -- what the exchange freeze letter carries -------------------------------------------
def test_the_exchange_freeze_letter_carries_what_the_exchange_needs_to_act():
    text = draft("case-1", usdt_case(), "exchange-freeze")
    flat = one_line(text)
    assert "URGENT" in text and "hold" in flat and "pending a formal request" in flat
    assert DEPOSIT in text and TX in text
    assert "Chain : Tron" in flat and "Token : USDT" in flat
    assert "2024-12-12 19:15 IST (13:45 UTC)" in text  # each hash's time, in IST with UTC


def test_the_exchange_freeze_letter_states_only_the_conservative_amount():
    flat = one_line(draft("case-1", usdt_case(), "exchange-freeze"))
    assert "about 2,000.000000 USDT" in flat
    for gross in ("6,000", "7,000", "9,000"):  # pro-rata, the hop flows, the transfer's value
        assert gross not in flat


def test_the_freeze_letter_never_exceeds_what_the_victim_reported():
    result = usdt_case(reported_amount=1000.0, intake={"mode": "payment", "payments": [{"tx_hash": TX, "amount": 1000.0}]})
    flat = one_line(draft("case-1", result, "exchange-freeze"))
    assert "about 1,000.000000 USDT" in flat and "2,000" not in flat


def test_with_no_estimate_the_amount_is_the_officers_to_state():
    flat = one_line(draft("case-1", case(), "exchange-freeze"))
    assert f"Amount : {BLANK}" in flat and "2.500000" not in flat


def test_the_officer_fills_every_blank_the_tool_cannot():
    lines = draft("case-1", usdt_case(), "exchange-freeze").splitlines()
    for field in ("name and rank", "police station", "FIR / NCRP", "legal provision", "e-mail and phone"):
        assert any(BLANK in line and field in line for line in lines), field


def test_the_freeze_letter_carries_no_narrative_and_no_investigation_detail():
    text = draft("case-1", usdt_case(evidence={"manifest_sha256": "f" * 64}), "exchange-freeze")
    for detail in ("investigating a complaint", "Hop 1", HOP, SEED, "f" * 64, "case-1", "KYC", "pro-rata"):
        assert detail not in text, detail


@pytest.mark.parametrize("result, ask", [
    (case(matches=[{"address": DEPOSIT, "wallet_type": "deposit_wallet", "label": f"Binance Dep: {DEPOSIT}"}]),
     f"in the account(s) that deposit address {DEPOSIT} belongs to"),
    (DEMOS[9], "credited by the transactions below"),
    (DEMOS[6], "If 0x8290868cc51e7315d1318f449d48fe66fcf203a5 is a deposit address you issued"),
    (DEMOS[12], "If TA6SbszfFYC7NYt48viCM9LMD5F5E1Gbi8 is controlled by you"),
])
def test_the_exchange_freeze_asks_only_what_the_case_holds_about_the_address(result, ask):
    assert ask in one_line(draft("case-1", result, "exchange-freeze"))


def test_a_hot_wallet_freeze_is_not_about_the_wallet_itself():
    flat = one_line(draft("case-1", DEMOS[9], "exchange-freeze"))
    assert "not about the wallet itself" in flat


def test_demo_11s_hot_wallet_freeze_lists_only_the_transfers_that_can_carry_the_traced_funds():
    # 635 USDT reached hop 1 (340 on 19 Dec 2024, 295 on 24 Dec); it sent 27
    # transfers into Binance-Hot 7 over a year. Holding every account they
    # credited would hold innocent customers' money.
    text = draft("case-1", DEMOS[11], "exchange-freeze")
    assert "38ef314819abff3f5c448da6de769fad80821ae06a26f15a8fd134e1645fbdba" in text  # 19 Dec: carries 340
    assert "821965673662c740fe8b51126bc3dd3e6d53047f2282f7def00ee750c748f974" in text  # 24 Dec: the other 295
    assert "ddcaeacc39f740712c31cee205ed1f8c93b01cec67dcf4207a6983183902ada1" not in text  # 635 already covered
    assert "e92795864f33580eb583e9c54839d8c4ea1ad35642eb4d5533a370df979cc1e5" not in text  # Dec 2025
    assert "25 other transfers into it in this trace are not part of this request" in one_line(text)


def test_the_hot_wallet_note_wraps_at_one_indent_so_it_reads_as_one_paragraph():
    # The Letters tab flows a server-wrapped line back into its paragraph only
    # when it keeps the paragraph's indent: every line of the note keeps the tx lines' five.
    text = draft("case-1", DEMOS[11], "exchange-freeze")
    rows = text.splitlines()
    first = next(i for i, r in enumerate(rows) if r.lstrip().startswith("(the earliest"))
    note = rows[first:rows.index("", first)]
    assert len(note) > 1, "the note no longer wraps: this test needs a longer one"
    assert {len(r) - len(r.lstrip(" ")) for r in note} == {5}


def test_a_hot_wallet_freeze_never_lists_a_transfer_made_before_the_funds_arrived():
    hot = {**usdt_case()["trace_path"][2], "label": "Binance 14", "tx_count": 4}
    sent = [("e0" * 32, 300.0, 1_733_000_000), ("e1" * 32, 600.0, 1_734_000_500), ("e2" * 32, 1500.0, 1_734_000_900),
            ("e3" * 32, 5000.0, 1_734_002_000)]
    result = usdt_case(matches=[{"address": DEPOSIT, "wallet_type": "hot_wallet", "label": "Binance 14"}],
                       transfers=[{"hash": HOP_TX, "from": SEED, "to": HOP, "value_native": 9000.0,
                                   "timestamp": 1_734_000_000}]
                       + [{"hash": h, "from": HOP, "to": DEPOSIT, "value_native": v, "timestamp": ts}
                          for h, v, ts in sent])
    result["trace_path"][2] = hot
    text = draft("case-1", result, "exchange-freeze")
    assert "credited by the transactions below" in one_line(text)
    assert "e1" * 32 in text and "e2" * 32 in text  # 600 + 1,400 of 1,500 cover the 2,000
    assert "e0" * 32 not in text and "e3" * 32 not in text  # before the funds arrived; not needed


def test_demo_11s_freeze_letter_states_the_figure_its_information_letter_states():
    freeze = one_line(draft("case-1", DEMOS[11], "exchange-freeze"))
    assert "about 635.000000 USDT" in freeze and "about 635.000000 USDT" in one_line(draft("case-1", DEMOS[11], "exchange"))
    assert "45,968" not in freeze  # the gross flow into the hot wallet


# -- the Tether freeze letter --------------------------------------------------------
def test_the_tether_freeze_letter_names_the_wallets_hashes_and_times():
    text = draft("case-1", usdt_case(), "tether-freeze")
    flat = one_line(text)
    assert "Tether" in text and "freeze" in flat and "pending a formal request" in flat
    assert SEED in text and HOP in text and HOP_TX in text
    assert "2024-12-12 16:10 IST (10:40 UTC)" in text
    assert "Chain : Tron" in flat and "Token : USDT" in flat
    assert "about 2,000.000000 USDT passed through these wallets and reached Binance" in flat and "9,000" not in flat


def test_the_tether_freeze_letter_never_names_an_exchange_or_an_already_frozen_wallet():
    frozen = {"address": HOP, "category": "frozen", "label": "USDT frozen by Tether on 2026-09-11",
              "source": "Tether USDT contract on Tron, AddedBlackList event"}
    text = draft("case-1", usdt_case(risk_matches=[frozen]), "tether-freeze")
    assert DEPOSIT not in text and HOP not in text and SEED in text


def test_the_tether_freeze_amount_says_the_funds_went_on_to_the_exchange():
    # Demo 9: the reported wallet sent 26,405 USDT into Binance's hot wallet;
    # the figure is not what sits at the wallet the letter lists.
    flat = one_line(draft("case-1", DEMOS[9], "tether-freeze"))
    assert "about 26,405.277104 USDT passed through these wallets and reached Binance" in flat
    assert "Amount : about 26,405.277104 USDT (" not in flat


def test_a_follow_on_tether_freeze_states_the_swap_capped_figure():
    result = follow_on_case()
    follow = result["follow_ons"][0]["result"]
    follow["trace_path"][0]["address"] = SWAPPER
    flat = one_line(draft("case-1", result, "tether-freeze"))
    assert SWAPPER in flat and DEPOSIT not in flat
    assert "about 100.000000 USDT passed through these wallets and reached Binance" in flat
    assert "5,000" not in flat


def test_the_tether_freeze_lists_every_transfer_into_a_route_wallet_not_the_steps_twenty():
    hashes = ["%064x" % (0xa000 + i) for i in range(27)]
    result = usdt_case(transfers=[{"hash": h, "from": SEED, "to": HOP, "value_native": 1.0,
                                   "timestamp": 1_734_000_000 + i} for i, h in enumerate(hashes)])
    result["trace_path"][1].update(tx_count=27, tx_hashes=hashes[:20])
    text = draft("case-1", result, "tether-freeze")
    assert all(h in text for h in hashes) and "officer to add the rest" not in text


def test_when_the_case_holds_only_the_steps_twenty_the_freeze_says_the_list_is_cut():
    hashes = ["%064x" % (0xa000 + i) for i in range(20)]
    result = usdt_case()
    result["trace_path"][1].update(tx_count=27, tx_hashes=hashes)
    flat = one_line(draft("case-1", result, "tether-freeze"))
    assert all(h in flat for h in hashes) and "(20 of 27 transfers listed; officer to add the rest)" in flat


# -- a USDT trace that reached no exchange: where the USDT stopped ------------------------
DEMO3_END, DEMO3_TX = "0xc6aafd1238694e165bf82ce50a5bff879e822177", (
    "0x6e60845518b36c8ccce7b3bac7cbc6a753dcb853ed4ce38e2e109d23b2999e31")


def test_demo_3s_tether_freeze_names_neither_the_empty_swapping_wallet_nor_one_never_read():
    # 0x35cf... sent all 5,215 USDT on to DEMO3_END, at the depth limit: the
    # walk never read what that wallet sent, so the case cannot say the USDT
    # stopped there, and there is no wallet left to ask Tether to freeze.
    assert all(letter["to"] != "tether-freeze" for letter in available(DEMOS[3]))
    with pytest.raises(LetterNotApplicable):
        draft("case-1", DEMOS[3], "tether-freeze")
    assert DEMO3_END in draft("case-1", DEMOS[3], "tether") and DEMO3_TX in draft("case-1", DEMOS[3], "tether")


def node(address, out=0.0, into=0.0, **over):
    return {"id": address, "address": address, "total_out_native": out, "total_in_native": into, **over}


def stopped_case(nodes, edges=(), transfers=()):
    return usdt_case(exchange=None, exchange_address=None, trace_path=[], estimates=None, prorata=None,
                     tracing_methods=None, graph={"nodes": nodes, "edges": list(edges)}, transfers=list(transfers))


def test_the_tether_freeze_never_names_a_labelled_router_listed_or_frozen_end_wallet():
    ends = ["T" + c * 33 for c in "abcdefg"]
    frozen = {"address": ends[6], "category": "frozen", "label": "USDT frozen by Tether on 2026-09-11",
              "source": "Tether USDT contract on Tron, AddedBlackList event"}
    result = stopped_case([node(SEED, out=900.0), node(ends[0], into=100.0), node(ends[1], into=1, label="Pool"),
                           node(ends[2], into=1, is_router=True), node(ends[3], into=1, risk_category="gambling"),
                           node(ends[4], into=1, is_service_contract=True), node(ends[5], into=1, inferred_exchange="X"),
                           node(ends[6], into=1), node(HOP, out=50.0, into=50.0)])
    result["risk_matches"] = [frozen]
    text = draft("case-1", result, "tether-freeze")
    assert ends[0] in text and not any(e in text for e in ends[1:]) and SEED not in text and HOP not in text
    assert f"Amount : {BLANK}" in one_line(text)


def test_a_start_that_sent_nothing_on_is_where_the_usdt_stopped():
    text = draft("case-1", stopped_case([node(SEED)]), "tether-freeze")
    assert SEED in text and "Transactions into them: " + BLANK in text  # never the payments into it


def test_the_tether_freeze_names_at_most_five_end_wallets_the_largest_first():
    ends = ["T" + c * 33 for c in "abcdefg"]
    text = draft("case-1", stopped_case([node(SEED, out=28.0)] + [node(e, into=i + 1.0) for i, e in enumerate(ends)]),
                 "tether-freeze")
    assert all(e in text for e in ends[2:]) and ends[0] not in text and ends[1] not in text
    assert "2 more wallets where the traced USDT stopped are not listed" in one_line(text)


def test_a_usdt_trace_with_nowhere_to_freeze_offers_no_tether_freeze_letter():
    result = stopped_case([node(SEED, out=10.0), node(HOP, into=10.0, label="Pool")])
    assert all(letter["to"] != "tether-freeze" for letter in available(result))


# -- the draft line, on every letter -------------------------------------------------
def test_the_not_valid_line_is_plain():
    assert NOT_VALID == "This is a DRAFT. It is not valid until an officer signs it on official letterhead."


@pytest.mark.parametrize("to", ["exchange-freeze", "tether-freeze", "exchange", "tether"])
def test_every_letter_says_it_is_not_valid_until_an_officer_signs_it(to):
    text = draft("case-1", usdt_case(), to)
    assert text.startswith("DRAFT") and NOT_VALID in text.splitlines()[:3]


@pytest.mark.parametrize("demo", sorted(DEMOS))
def test_every_letter_a_demo_offers_carries_the_not_valid_line(demo):
    for letter in available(DEMOS[demo]):
        assert NOT_VALID in draft("case-1", DEMOS[demo], letter["to"])
