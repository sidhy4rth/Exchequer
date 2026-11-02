"""/health, /chains and /health/detail (app/routes/coverage.py): the public
site says whether it is up and what it can trace; how it is configured and
how its provider quota is going is for the operator's token only."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

TOKEN = "t" * 40


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_public_health_says_only_whether_it_is_up(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_chains_lists_what_the_console_needs(client):
    body = client.get("/chains").json()
    assert body["default_chain"] == config.DEFAULT_CHAIN.key
    assert body["max_depth"] == config.TRACE_MAX_DEPTH
    for chain in body["chains"].values():
        assert {"key", "name", "ready", "assets", "address_family", "exchange_labels", "risk_labels"} <= set(chain)


def test_chains_never_says_how_the_server_is_configured(client, monkeypatch):
    # An unconfigured provider explains itself by naming its key variable.
    for name in ("ETHERSCAN_API_KEY", "NODEREAL_API_KEY"):
        monkeypatch.setattr(config, name, None)
    monkeypatch.setattr(config, "HEALTH_TOKEN", TOKEN)
    detail = client.get("/health/detail", headers={"authorization": f"Bearer {TOKEN}"}).text
    assert "_API_KEY" in detail  # the control: the operator's view does name it
    response = client.get("/chains")
    assert response.headers["content-type"] == "application/json"  # not the app's HTML
    for leak in ("detail", "_API_KEY", "etherscan_key_configured", "api_budget", "warm_cache"):
        assert leak not in response.text


def test_health_detail_does_not_exist_without_a_token(client, monkeypatch):
    monkeypatch.setattr(config, "HEALTH_TOKEN", "")
    assert client.get("/health/detail").status_code == 404
    assert client.get("/health/detail", headers={"authorization": "Bearer "}).status_code == 404


def test_health_detail_refuses_anything_but_the_token(client, monkeypatch):
    monkeypatch.setattr(config, "HEALTH_TOKEN", TOKEN)
    for header in (None, "Bearer wrong", f"Basic {TOKEN}", TOKEN):
        headers = {"authorization": header} if header else {}
        assert client.get("/health/detail", headers=headers).status_code == 401


def test_health_detail_gives_the_operator_everything(client, monkeypatch):
    monkeypatch.setattr(config, "HEALTH_TOKEN", TOKEN)
    body = client.get("/health/detail", headers={"authorization": f"Bearer {TOKEN}"}).json()
    assert body["status"] == "ok"
    assert {"etherscan_key_configured", "api_budget", "warm_cache", "chains"} <= set(body)
    assert all("detail" in chain for chain in body["chains"].values())


# -- R14: wallets and deposit addresses counted apart -----------------------------
def test_chains_counts_exchange_wallets_apart_from_customer_deposit_addresses(client):
    import json

    for key, chain in client.get("/chains").json()["chains"].items():
        # Read the label file directly, not through the code under test.
        labels = json.loads(config.CHAINS[key].labels_path.read_text())["labels"]
        deposits = sum(1 for v in labels.values() if isinstance(v, dict) and v.get("type") == "deposit_wallet")
        assert chain["deposit_addresses"] == deposits, key
        assert chain["exchange_wallets"] + chain["deposit_addresses"] == chain["exchange_labels"], key
    # The case that made the single number misleading: most of Ethereum's are deposits.
    ethereum = client.get("/chains").json()["chains"]["ethereum"]
    assert ethereum["deposit_addresses"] > ethereum["exchange_wallets"] > 0
