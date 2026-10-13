"""API keys must never reach the logs (app/log_safety.py)."""
import logging

import httpx

from app import log_safety


def test_redacts_etherscan_and_nodereal_keys():
    assert log_safety.redact("GET https://api.etherscan.io/v2/api?module=account&apikey=ABC123XYZ&page=1") == \
        "GET https://api.etherscan.io/v2/api?module=account&apikey=<redacted>&page=1"
    assert log_safety.redact("POST https://bsc-mainnet.nodereal.io/v1/0123abcdef") == \
        "POST https://bsc-mainnet.nodereal.io/v1/<redacted>"
    assert log_safety.redact("nothing secret here") == "nothing secret here"


def test_httpx_request_log_carries_no_key(caplog):
    log_safety.install()
    caplog.handler.addFilter(log_safety.RedactingFilter())
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    with caplog.at_level(logging.DEBUG):
        with httpx.Client(transport=transport) as client:
            client.get("https://api.etherscan.io/v2/api", params={"apikey": "SECRETKEY123"})
            client.post("https://bsc-mainnet.nodereal.io/v1/NODEREALSECRET", json={})
        logging.getLogger("app.test").warning("retry %s", "https://x.io/v2/api?apikey=SECRETKEY123")
    text = caplog.text
    assert "SECRETKEY123" not in text
    assert "NODEREALSECRET" not in text
