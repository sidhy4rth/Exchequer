"""/health, /chains and /health/detail (app/routes/coverage.py): the public
site says whether it is up and what it can trace; how it is configured and
how its provider quota is going is for the operator's token only."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config, report
from app.main import app

TOKEN = "t" * 40


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_public_health_says_only_whether_it_is_up_open_and_which_build(client, monkeypatch):
    """Up, whether anyone may start live traces -- the same fact GET /access
    gives the console, shown where monitors look -- and which commit is
    serving, which every report's footer already prints (the repository is
    public). The site canary waits for the pushed commit by it (r1-ci-github-9)."""
    build = report.tool_version()
    monkeypatch.setattr(config, "DEMO_CODE", "")
    assert client.get("/health").json() == {"status": "ok", "access": "open", "console": "open", "build": build}
    monkeypatch.setattr(config, "DEMO_CODE", "a" * 22)
    assert client.get("/health").json() == {"status": "ok", "access": "code", "console": "open", "build": build}


def test_the_build_is_the_commit_the_host_deployed(monkeypatch):
    """In the image there is no git; Render names the deployed commit."""
    monkeypatch.delenv("EXCHEQUER_VERSION", raising=False)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "0123456789abcdef0123456789abcdef01234567")
    assert report._read_tool_version() == "0123456789ab"


def test_health_detail_reports_the_access_state(client, monkeypatch):
    monkeypatch.setattr(config, "HEALTH_TOKEN", TOKEN)
    monkeypatch.setattr(config, "DEMO_CODE", "short")
    body = client.get("/health/detail", headers={"authorization": f"Bearer {TOKEN}"}).json()
    assert body["access"]["state"] == "code"
    assert body["access"]["demo_code_long_enough"] is False
    assert "short" not in repr(body)


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


# -- R33c: flags and storage in the operator's view ------------------------------
def detail(client, monkeypatch):
    monkeypatch.setattr(config, "HEALTH_TOKEN", TOKEN)
    return client.get("/health/detail", headers={"authorization": f"Bearer {TOKEN}"}).json()


def test_health_detail_lists_every_flag(client, monkeypatch):
    monkeypatch.setitem(config.FLAGS, "EXCHEQUER_TEST_ONLY_FLAG", {"on": True, "about": "a test"})
    assert detail(client, monkeypatch)["flags"]["EXCHEQUER_TEST_ONLY_FLAG"] == {"on": True, "about": "a test"}


# The two below call _storage() itself: the engine they swap in is never
# connected, and /health/detail also reads the store (the watcher's status).
def test_a_sqlite_store_on_a_temporary_disk_says_so(monkeypatch):
    from sqlalchemy import create_engine

    from app import models
    from app.routes import coverage
    monkeypatch.setattr(models, "_engine", create_engine("sqlite://", future=True))
    monkeypatch.setattr(config, "TEMPORARY_DISK", True)
    monkeypatch.setattr(config, "API_CACHE_PATH", config.BACKEND_DIR / "provider_cache.db")
    storage = coverage._storage()
    assert storage["case_store"] == {"engine": "sqlite", "temporary": True}
    assert storage["provider_cache"] == {"enabled": True, "temporary": True}


def test_a_postgres_store_outlives_the_disk(monkeypatch):
    from sqlalchemy import create_engine

    from app import models
    from app.routes import coverage
    # Never connected: only the dialect is read.
    monkeypatch.setattr(models, "_engine", create_engine("postgresql+psycopg://u:p@localhost/x", future=True))
    monkeypatch.setattr(config, "TEMPORARY_DISK", True)
    monkeypatch.setattr(config, "API_CACHE_PATH", None)
    storage = coverage._storage()
    assert storage["case_store"] == {"engine": "postgresql", "temporary": False}
    assert storage["provider_cache"] == {"enabled": False, "temporary": False}


def test_on_a_lasting_disk_nothing_is_called_temporary(client, monkeypatch):
    monkeypatch.setattr(config, "TEMPORARY_DISK", False)
    storage = detail(client, monkeypatch)["storage"]
    assert storage["case_store"]["temporary"] is False and storage["provider_cache"]["temporary"] is False


@pytest.mark.parametrize("environ, temporary", [
    ({}, False),                                                   # a laptop, a VM with a disk
    ({"RENDER": "true"}, True),                                    # Render: no lasting disk
    ({"RENDER": "true", "EXCHEQUER_TEMPORARY_DISK": "0"}, False),  # Render with a disk attached
    ({"EXCHEQUER_TEMPORARY_DISK": "1"}, True),                     # another host that forgets
])
def test_a_temporary_disk_is_read_from_the_host(environ, temporary):
    assert config.temporary_disk(environ) is temporary


# -- r1-scripts-12: whether the 10.9M-row label store is actually in use ---------
def test_health_detail_reports_the_label_store(client, monkeypatch, tmp_path):
    from app.label_store import get_label_store
    from scripts.build_label_store import build

    src = tmp_path / "flagged.csv"
    src.write_text("address,chain,category,entity_or_incident,sources,source_refs,date\n"
                   f"0x{'5c' * 20},ethereum|arbitrum,phishing/scam,Drainer,Threat-intel report: Check Point,,\n")
    build(src, tmp_path / "store.db")
    monkeypatch.setattr(config, "LABEL_STORE_REQUIRED", True)
    monkeypatch.setattr(config, "LABEL_STORE_TAG", "labels-test")
    try:
        monkeypatch.setattr(config, "LABEL_STORE_PATH", tmp_path / "store.db")
        get_label_store.cache_clear()
        assert detail(client, monkeypatch)["label_store"] == {
            "required": True, "loaded": True, "rows": 2, "tag": "labels-test"}
        monkeypatch.setattr(config, "LABEL_STORE_PATH", tmp_path / "missing.db")
        get_label_store.cache_clear()
        assert detail(client, monkeypatch)["label_store"] == {
            "required": True, "loaded": False, "rows": 0, "tag": "labels-test"}
    finally:
        get_label_store.cache_clear()


@pytest.mark.parametrize("keys", [True, False])
def test_chain_readiness_builds_no_provider_client(client, monkeypatch, keys):
    """/chains is public and uncached; it used to build (and close) an httpx
    client, TLS context and all, for every chain on every request just to
    learn whether a key was set (r1-providers-8)."""
    import httpx

    from app.chain_data import provider_status

    for name in ("ETHERSCAN_API_KEY", "NODEREAL_API_KEY"):
        monkeypatch.setattr(config, name, "k" if keys else None)

    def refuse(*args, **kwargs):
        raise AssertionError("a provider client was built")

    monkeypatch.setattr(httpx.Client, "__init__", refuse)
    status = provider_status()
    assert status["tron"]["ready"] is True  # TronGrid answers without a key
    for key in ("ethereum", "polygon", "arbitrum", "bsc"):
        assert status[key]["ready"] is keys
        assert (status[key]["detail"] is None) is keys
    body = client.get("/chains").json()
    assert {k: c["ready"] for k, c in body["chains"].items()} == {k: s["ready"] for k, s in status.items()}


def test_chains_counts_its_labels_once_not_per_request(client, monkeypatch):
    """/chains walked every exchange label and recounted every risk label on
    each public request; the counts change only when a matcher is rebuilt
    (r1-providers-8)."""
    from app.exchange_matcher import ExchangeMatcher
    from app.risk_matcher import RiskMatcher
    from app.routes import coverage

    coverage._COUNTS.clear()
    walks = []
    entries, counts = ExchangeMatcher.entries, RiskMatcher.counts_by_category
    monkeypatch.setattr(ExchangeMatcher, "entries", lambda self: walks.append("x") or entries(self))
    monkeypatch.setattr(RiskMatcher, "counts_by_category", lambda self: walks.append("r") or counts(self))
    first = client.get("/chains").json()["chains"]
    assert len(walks) == 2 * len(first)
    for _ in range(3):
        assert client.get("/chains").json()["chains"] == first
    assert len(walks) == 2 * len(first)

    # A rebuilt matcher (another label file, the store attached) is counted again.
    from app.exchange_matcher import get_matcher

    rebuilt = ExchangeMatcher({"0x" + "ab" * 20: {"exchange": "Test", "type": "hot_wallet"}}, chain="ethereum")
    monkeypatch.setattr(coverage, "get_matcher", lambda key=None: rebuilt if key == "ethereum" else get_matcher(key))
    again = client.get("/chains").json()["chains"]
    assert again["ethereum"]["exchange_labels"] == 1 and again["polygon"] == first["polygon"]
