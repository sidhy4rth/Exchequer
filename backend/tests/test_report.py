"""Tests for the investigator's report.

The report is the one artefact that leaves the tool, so the tests pin what
it must always contain -- header, plain summary, hop-by-hop path with times,
thresholds, inference evidence, appendix of hashes -- and that a case stored
by an earlier version, without the newer fields, still renders rather than
crashing the export.
"""
from __future__ import annotations

import json

from app.models import Case
from app.report import build_report, render_text_report

from conftest import addr

SEED, MID, HOT = addr("5eed"), addr("a1"), addr("b1a")


def stored(result: dict) -> Case:
    return Case(id="case-1", address=SEED, created_at="2026-09-15T12:00:00+00:00",
                result_json=json.dumps(result))


def full_result() -> dict:
    return {
        "address": SEED, "chain": "ethereum", "chain_name": "Ethereum Mainnet", "chain_id": 1,
        "asset": "ETH", "native_symbol": "ETH", "direction": "outgoing",
        "explorer_url": "https://etherscan.io",
        "exchange": "Binance", "exchange_address": MID, "exchange_label": "probable Binance deposit address (inferred)",
        "attribution_inferred": True, "hop_count": 1, "value_received_native": 9.5, "confidence": 0.875,
        "flags": ["amount_split"], "risk_flags": [], "risk_matches": [], "risk_notes": [],
        "confidence_detail": {"band": "high", "summary": "High confidence (0.88) that funds reached Binance.",
                              "components": [{"name": "hop_proximity", "raw_value": 1.0, "weight": 0.4,
                                              "contribution": 0.4, "explanation": "Direct."}],
                              "caveats": ["An exchange match identifies where funds arrived, not who controls the account."]},
        "trace_path": [
            {"address": SEED, "depth": 0, "label": None},
            {"address": MID, "depth": 1, "label": "probable Binance deposit address (inferred)",
             "value_native": 9.5, "tx_count": 2, "first_seen": 1_700_000_000, "last_seen": 1_700_100_000,
             "tx_hashes": ["0xaaa", "0xbbb"]},
        ],
        "matches": [], "inferred_deposits": [{
            "address": MID, "exchange": "Binance", "depth": 1, "inferred": True,
            "evidence": {"sweep_count": 3, "sweep_destination": HOT, "sweep_destination_label": "Binance 14",
                         "total_swept_native": 30.0, "first_sweep": 1_700_000_000, "last_sweep": 1_700_200_000,
                         "current_balance_native": 0.01, "thresholds_applied": {"min_sweeps": 2},
                         "confirmation": "A lawful request to Binance would confirm or refute this inference."}}],
        "inference_notes": [f"{MID} is inferred to be a Binance deposit address. A lawful request to Binance would confirm or refute this inference."],
        "findings": [{"pattern": "amount_split", "strength": 0.7, "description": "Amount split: fanned out.",
                      "evidence": {"thresholds_applied": {"min_split_branches": 4, "min_forwarded_ratio": 0.9}}}],
        "swaps": [], "swap_notes": [],
        "graph": {"nodes": [{"id": SEED}, {"id": MID}, {"id": HOT}], "edges": [{}, {}]},
        "transfers": [{"hash": "0xaaa", "from": SEED, "to": MID, "value_native": 4.5, "timestamp": 1_700_000_000, "internal": False},
                      {"hash": "0xccc", "from": MID, "to": HOT, "value_native": 9.0, "timestamp": 1_700_300_000, "internal": True}],
        "depth_reached": 2, "transfers_excluded_by_time": 3, "truncated": True,
        "truncation_reasons": ["depth limit of 3 hops reached"], "warnings": [],
        "direct_senders": [],
    }


def test_the_text_report_carries_every_section_an_officer_needs():
    text = render_text_report(build_report(stored(full_result())))
    # Prose is wrapped at 78 columns, so sentences are checked with the line
    # breaks folded away; fixed-width fields are checked as printed.
    flat = " ".join(text.split())

    assert "Case ID          : case-1" in text
    assert "Asset followed   : ETH" in text
    assert "Rendered with    : Exchequer" in text and "Traced with      : " in text
    assert "SUMMARY" in text and "was followed across 3 addresses" in flat
    assert "infers to be a Binance deposit address" in flat
    assert "INFERRED from the wallet's behaviour" in text
    assert "PATH THE MONEY TOOK" in text
    assert ("sent 9.5 ETH in 2 transfers between 2023-11-15 03:43 IST (2023-11-14 22:13 UTC) "
            "and 2023-11-16 07:30 IST (02:00 UTC) to") in flat
    assert "tx 0xaaa" in text
    assert "INFERRED DEPOSIT ADDRESSES" in text
    assert f"outgoing transfers : 3, all to {HOT}" in flat
    assert "lawful request to Binance" in flat
    assert "Thresholds applied:" in text and "min_split_branches" in text
    assert "reason to look closer, not as a verdict" in flat
    assert "Excluded by the time rule  : 3" in text
    assert "APPENDIX A - EVERY ADDRESS IN THE TRACE" in text and HOT in text
    assert "APPENDIX B - EVERY TRANSACTION IN THE TRACE" in text
    assert "0xccc" in text and " i " in text  # the contract-moved one is marked


def test_a_case_stored_by_an_earlier_version_still_renders():
    """Older cases lack transfers, inference and swap fields; the export must
    degrade to a note, never a 500."""
    old = {"address": SEED, "chain": "ethereum", "direction": "outgoing", "graph": {"nodes": [], "edges": []},
           "confidence_detail": {}, "exchange": None}
    text = render_text_report(build_report(stored(old)))
    assert "No known exchange wallet was reached" in text
    assert "were not stored with this case" in text


def test_the_summary_says_when_the_trail_changed_asset():
    result = full_result()
    result.update(exchange=None, attribution_inferred=False,
                  swaps=[{"output_read": True, "asset_out": "USDT", "router_label": "Uniswap V3: Router 2"}])
    assert "exchanged for USDT at Uniswap V3: Router 2" in build_report(stored(result))["summary"]


def test_the_json_report_carries_the_appendix_and_version():
    report = build_report(stored(full_result()))
    assert report["appendix"]["addresses"] == [SEED, MID, HOT]
    assert [t["hash"] for t in report["appendix"]["transactions"]] == ["0xaaa", "0xccc"]
    assert report["tool_version"]


def test_the_report_prints_the_evidence_manifest_and_seals_itself():
    from app.evidence import verify_sealed_text

    result = full_result()
    result["evidence"] = {
        "algorithm": "sha256", "count": 2, "retrieved": 1, "from_cache": 1,
        "providers": ["etherscan"],
        "first_retrieved_at": "2026-09-15T15:40:36Z", "last_retrieved_at": "2026-09-15T15:40:36Z",
        "manifest_sha256": "ab" * 32,
        "records": [
            {"provider": "etherscan", "request": "GET https://api.etherscan.io/v2/api?action=txlist&address=" + SEED,
             "retrieved_at": "2026-09-15T15:40:36Z", "sha256": "cd" * 32, "bytes": 812, "from_cache": False},
            {"provider": "etherscan", "request": "GET https://api.etherscan.io/v2/api?action=txlist&address=" + MID,
             "retrieved_at": "2026-09-15T15:40:36Z", "sha256": "ef" * 32, "bytes": 90, "from_cache": True},
        ],
    }
    text = render_text_report(build_report(stored(result)))

    assert "APPENDIX C - EVIDENCE MANIFEST" in text
    assert "Manifest SHA-256: " + "ab" * 32 in text
    assert "sha256 " + "cd" * 32 in text
    assert "90 bytes  cached" in text
    assert "CONTENT HASH" in text
    assert verify_sealed_text(text)
    assert not verify_sealed_text(text.replace("9.5", "9.6", 1))


def test_a_case_stored_before_hashing_says_so_and_still_seals():
    from app.evidence import verify_sealed_text

    text = render_text_report(build_report(stored(full_result())))
    assert "No evidence manifest was stored with this case" in text
    assert verify_sealed_text(text)


def test_the_summary_names_the_issuer_for_a_circle_freeze():
    # Audit r1-labels-data-0: a Circle freeze is not Tether's.
    circle = {"address": MID, "category": "frozen", "entity": "USDC frozen by Circle", "label": "USDC frozen by Circle",
              "origin": "label_store", "token": "USDC", "issuer": "Circle", "source": "USDC freeze events"}
    xsgd = {**circle, "entity": "XSGD frozen by its issuer", "label": "XSGD frozen by its issuer",
            "token": "XSGD", "issuer": None}
    summary = build_report(stored({**full_result(), "risk_flags": ["frozen"], "risk_matches": [circle, xsgd]}))["summary"]
    assert "USDT frozen by Tether" not in summary
    assert "frozen by its token's issuer (USDC by Circle; XSGD by its issuer)" in summary


def test_a_tether_freeze_still_says_tether():
    tether = {"address": MID, "category": "frozen", "entity": "Tether (USDT freeze)",
              "label": "USDT frozen by Tether on 2021-08-05", "source": "Tether USDT contract on Ethereum"}
    summary = build_report(stored({**full_result(), "risk_flags": ["frozen"], "risk_matches": [tether]}))["summary"]
    assert "had its USDT frozen by Tether" in summary


def test_a_seizure_only_case_does_not_say_sanctions_list():
    """A government seizure order is not a designation (audit r1-labels-data-12)."""
    result = full_result()
    result["risk_flags"] = ["seized"]
    summary = build_report(stored(result))["summary"]
    assert "seizure or forfeiture order, which is not a sanctions designation" in summary
    assert "on a published sanctions list" not in summary


def test_the_summary_no_longer_credits_every_stolen_tag_to_the_explorer():
    """ScamSniffer is not the block explorer, and a list's report is not a theft (r1-labels-data-6)."""
    result = full_result()
    result["risk_flags"] = ["stolen", "scam"]
    summary = build_report(stored(result))["summary"]
    assert "block explorer" not in summary
    assert "tied by a published source to a known hack or exploit" in summary
    assert "named by a published scam or phishing list" in summary


def test_a_payment_case_prints_its_payments_and_window_but_no_particulars():
    # 5-3: the time rule's basis is in the signed report so a reviewer can
    # check it; the sender, the victim's wallet and the NCRP number are not.
    victim, ncrp = addr("71c"), "31911250012345"
    leg = {"tx_hash": "0x" + "aa" * 32, "chain": "ethereum", "asset": "ETH", "amount": 3999.0, "from": victim,
           "to": SEED, "block": 18_000_000, "timestamp": 1_700_000_000, "found_by": "victim",
           "payer_label": "Binance 14", "payer_is_victim": False, "leg": 0}
    intake = {"mode": "payment", "ncrp_ack": ncrp, "victim_address": victim,
              "payments": [leg, {**leg, "amount": 1.0, "leg": 1}]}
    report = build_report(stored({**full_result(), "intake": intake, "reported_amount": 4000.0}))
    assert report["intake"]["window_start"] == 1_700_000_000
    text = render_text_report(report)
    assert "VICTIM'S PAYMENTS" in text and "0x" + "aa" * 32 in text
    assert "Window start" in text and "4000.0 ETH" in text and "transfer 2 of 2" in text
    assert "Binance 14" in text and "not the victim's wallet" in text
    for secret in (victim, ncrp):
        assert secret not in json.dumps(report["intake"]) and secret not in text


def test_an_address_case_has_no_payments_section():
    report = build_report(stored(full_result()))
    # The report says how it started (r2-g2-frontend-intake-rendering-3-4), but lists no payments.
    assert report["intake"] == {"mode": "address", "reported_amount": None, "payments": []}
    assert "VICTIM'S PAYMENTS" not in render_text_report(report)


# -- r1-labels-data-2, round 2: the summary carries the tier --------------------
UNVETTED = "; evidence: unvetted list (community reports or a machine-learning dataset), not checked"


def risk(category, tier, source="HF ethereum_fraud_dataset (fesevu, CC BY 4.0)"):
    match = {"address": MID, "category": category, "entity": "phishing", "label": "phishing",
             "source": source, "origin": "label_store", "depth": 1}
    if tier is not None:
        match["tier"] = tier
    return match


def summary_for(*matches):
    flags = sorted({m["category"] for m in matches})
    return build_report(stored({**full_result(), "risk_flags": flags, "risk_matches": list(matches)}))["summary"]


def test_a_tier_5_scam_is_a_lead_in_the_summary_not_a_listing():
    summary = summary_for(risk("scam", 5))
    assert "named by a published scam or phishing list" not in summary
    assert "listed (reported scam) only by an unverified source" in summary
    assert "treat it as a lead, not a finding" in summary


def test_an_older_case_without_a_tier_is_read_from_its_source_text():
    summary = summary_for(risk("scam", None, source="HF ethereum_fraud_dataset" + UNVETTED))
    assert "named by a published scam or phishing list" not in summary and "unverified source" in summary


def test_a_published_lookalike_is_not_on_chain_detection_in_the_summary():
    summary = summary_for(risk("poisoning", 3, source="Poison-Hunter CCS24 ground truth"))
    assert "found by on-chain detection" not in summary
    assert "named as an address-poisoning lookalike by a published source" in summary
    assert "found by on-chain detection" in summary_for(risk("poisoning", 4, source="Ethereum poisoning via BigQuery"))
    mixed = summary_for(risk("poisoning", 3, source="Poison-Hunter CCS24 ground truth"), risk("poisoning", 5))
    assert "found by on-chain detection" not in mixed and "by a published source" in mixed


def test_tier_1_to_3_sentences_are_unchanged_beside_a_weak_one():
    summary = summary_for(risk("scam", 3, source="Threat-intel report: Check Point"), risk("stolen", 5))
    assert "named by a published scam or phishing list; a list's report is an accusation, not a finding." in summary
    assert "tied by a published source to a known hack" not in summary
    assert "listed (theft) only by an unverified source" in summary


# -- r2-g2-documented-claims-vs-code-7-5: only a pinned pool stops the trace --
def test_a_mixer_tag_that_did_not_stop_the_trace_is_not_called_a_stop():
    tag = {"address": MID, "category": "mixer", "entity": "Tornado.Cash: Router", "label": "Tornado.Cash: Router",
           "source": "Explorer tag", "origin": "label_store", "depth": 1, "is_terminal": False, "tier": 3}
    summary = summary_for(tag)
    assert "The trace stopped at a mixer" not in summary
    assert "not on the pinned list of mixer pools, so the trace went on past it" in summary
    assert "The trace stopped at a mixer" in summary_for({**tag, "is_terminal": True})
