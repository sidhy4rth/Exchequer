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
    assert "Tool version     : TraceChain" in text
    assert "SUMMARY" in text and "was followed across 3 addresses" in flat
    assert "infers to be a Binance deposit address" in flat
    assert "INFERRED from the wallet's behaviour" in text
    assert "PATH THE MONEY TOOK" in text
    assert "sent 9.5 ETH in 2 transfers between 2023-11-14 22:13 UTC and 2023-11-16 02:00 UTC to" in flat
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
