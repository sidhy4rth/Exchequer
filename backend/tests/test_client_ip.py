"""Which address a request is counted against (rate_limit.client_ip).

Every per-client limit -- traces per hour, running traces, watches, freeze
requests, wrong demo codes -- is keyed on this one value. Behind Render the
leftmost X-Forwarded-For entry used to be the key, and a client can write
that entry itself: rotating it dodged every limit, and typing someone else's
address locked them out. The rule is now explicit (config.CLIENT_IP_HEADER,
config.PROXY_HOPS), never chosen by the client when the edge says who it is,
and /health/detail shows the operator what arrived without showing an address.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, rate_limit
from app.main import app

TOKEN = "t" * 40
REAL = "49.36.1.1"
EDGE = "104.22.17.40"


@pytest.fixture
def render(monkeypatch):
    """Render mode with the defaults the deployed site starts with."""
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(config, "PROXY_CLIENT_FIRST", True)
    monkeypatch.setattr(config, "CLIENT_IP_HEADER", "cf-connecting-ip")
    monkeypatch.setattr(config, "PROXY_HOPS", 0)


def test_a_client_sent_forwarded_entry_does_not_change_the_key_when_the_edge_names_the_client(render):
    for typed in ("1.2.3.4", "5.6.7.8", "203.0.113.9"):
        headers = {"x-forwarded-for": f"{typed}, {REAL}, {EDGE}", "cf-connecting-ip": REAL}
        assert rate_limit.client_ip(headers, "10.0.0.1") == REAL


def test_the_measured_hop_count_reads_from_the_right(render, monkeypatch):
    monkeypatch.setattr(config, "CLIENT_IP_HEADER", "")
    monkeypatch.setattr(config, "PROXY_HOPS", 2)
    for typed in ("1.2.3.4", "5.6.7.8, 9.9.9.9"):
        assert rate_limit.client_ip({"x-forwarded-for": f"{typed}, {REAL}, {EDGE}"}, "10.0.0.1") == REAL
    assert rate_limit.client_ip({"x-forwarded-for": f"{REAL}, {EDGE}"}, "10.0.0.1") == REAL
    # Fewer entries than hops: the request did not come the measured way.
    assert rate_limit.client_ip({"x-forwarded-for": REAL}, "10.0.0.1") == "10.0.0.1"


def test_an_unmeasured_host_never_puts_every_visitor_under_one_key(render, monkeypatch):
    """Without the edge header or a measured hop count, the leftmost entry is
    still used: it can be chosen, but guessing a hop count instead could key
    every visitor on the edge's address and share one allowance between them."""
    monkeypatch.setattr(config, "CLIENT_IP_HEADER", "")
    a = rate_limit.client_ip({"x-forwarded-for": f"{REAL}, {EDGE}"}, "10.0.0.1")
    b = rate_limit.client_ip({"x-forwarded-for": f"49.36.9.9, {EDGE}"}, "10.0.0.1")
    assert a == REAL and b == "49.36.9.9"


def test_a_forged_edge_header_cannot_beat_a_configured_hop_count(render, monkeypatch):
    """With the header switched off, a client-sent CF-Connecting-IP is ignored."""
    monkeypatch.setattr(config, "CLIENT_IP_HEADER", "")
    monkeypatch.setattr(config, "PROXY_HOPS", 2)
    headers = {"x-forwarded-for": f"1.2.3.4, {REAL}, {EDGE}", "cf-connecting-ip": "6.6.6.6"}
    assert rate_limit.client_ip(headers, "10.0.0.1") == REAL


def test_ipv6_clients_share_one_key_per_64(render):
    one = rate_limit.client_ip({"cf-connecting-ip": "2401:4900:1c2a:7a1b::1"}, None)
    two = rate_limit.client_ip({"cf-connecting-ip": "2401:4900:1c2a:7a1b:dead:beef:0:9"}, None)
    other = rate_limit.client_ip({"cf-connecting-ip": "2401:4900:1c2a:7a1c::1"}, None)
    assert one == two == "2401:4900:1c2a:7a1b::/64"
    assert other != one


def test_an_ipv4_mapped_address_is_the_ipv4_address(render):
    assert rate_limit.client_ip({"cf-connecting-ip": "::ffff:49.36.1.1"}, None) == REAL


@pytest.mark.parametrize("junk", ["not-an-ip", "x" * 4096, "1.2.3.4:5678", ""])
def test_a_garbage_or_huge_header_falls_back_and_keys_stay_short(render, junk):
    key = rate_limit.client_ip({"cf-connecting-ip": junk, "x-forwarded-for": junk}, "10.0.0.1")
    assert key == "10.0.0.1"


def test_a_peer_that_is_not_an_address_is_kept_short():
    assert len(rate_limit.client_ip({}, "p" * 500)) <= 64


def test_x_real_ip_is_trusted_only_in_mode_1(monkeypatch):
    headers = {"x-real-ip": "198.51.100.4", "x-forwarded-for": "6.6.6.6, 203.0.113.9"}
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(config, "PROXY_CLIENT_FIRST", False)
    assert rate_limit.client_ip(headers, "10.0.0.1") == "198.51.100.4"
    monkeypatch.setattr(config, "PROXY_CLIENT_FIRST", True)
    monkeypatch.setattr(config, "CLIENT_IP_HEADER", "")
    monkeypatch.setattr(config, "PROXY_HOPS", 0)
    assert rate_limit.client_ip(headers, "10.0.0.1") == "6.6.6.6"
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", False)
    assert rate_limit.client_ip(headers, "10.0.0.1") == "10.0.0.1"


@pytest.mark.parametrize("environ, mode", [
    ({}, ""),
    ({"RENDER": "true"}, "render"),
    ({"RAILWAY_ENVIRONMENT": "production"}, "1"),
    ({"RENDER": "true", "EXCHEQUER_TRUST_PROXY": "0"}, "0"),
    ({"EXCHEQUER_TRUST_PROXY": " Render "}, "render"),
])
def test_the_proxy_mode_is_read_from_the_host_when_not_set(environ, mode):
    """Render sets RENDER on every service itself, so the right rule cannot
    drift the way a dashboard value can."""
    assert config.proxy_mode(environ) == mode


def test_the_image_does_not_trust_proxy_headers_by_default():
    """A host with no proxy in front would otherwise key on a client-chosen X-Real-IP."""
    dockerfile = (Path(config.BACKEND_DIR).parent / "Dockerfile").read_text()
    assert not any(line.strip().startswith("ENV EXCHEQUER_TRUST_PROXY") for line in dockerfile.splitlines())


# -- the operator's measurement, in /health/detail --------------------------------
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "HEALTH_TOKEN", TOKEN)
    with TestClient(app) as c:
        yield c


def probe(client, **headers):
    sent = {"authorization": f"Bearer {TOKEN}", **{k.replace("_", "-"): v for k, v in headers.items()}}
    return client.get("/health/detail", headers=sent).json()["client_ip"]


def test_the_probe_says_which_header_holds_the_caller_without_showing_an_address(client, render):
    body = probe(client, x_forwarded_for=f"1.2.3.4, {REAL}, {EDGE}", cf_connecting_ip=REAL,
                 x_exchequer_probe_me=REAL)
    text = repr(body)
    for address in ("1.2.3.4", REAL, EDGE, "49.36"):
        assert address not in text
    assert body["rule"].startswith("cf-connecting-ip")
    assert body["chosen"]["is_me"] is True
    assert body["candidates"]["cf-connecting-ip"]["is_me"] is True
    assert [e["is_me"] for e in body["candidates"]["x-forwarded-for"]] == [False, True, False]
    assert body["client_can_choose_key"] is False


def test_the_probe_suggests_the_hop_count_when_the_edge_header_is_missing(client, render):
    body = probe(client, x_forwarded_for=f"1.2.3.4, {REAL}, {EDGE}", x_exchequer_probe_me=REAL)
    assert body["client_can_choose_key"] is True
    assert body["chosen"]["is_me"] is False  # the leftmost entry was the forged one
    assert "EXCHEQUER_PROXY_HOPS=2" in body["advice"]


def test_the_probe_fingerprints_match_within_a_process(client, render):
    one = probe(client, cf_connecting_ip=REAL)
    two = probe(client, cf_connecting_ip=REAL)
    other = probe(client, cf_connecting_ip="49.36.9.9")
    assert one["chosen"]["fp"] == two["chosen"]["fp"] != other["chosen"]["fp"]
