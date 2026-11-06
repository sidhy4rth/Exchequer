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


# -- every sink, every shape (r2-g2-log-redaction-http-edges-2-4, -2-5) -----------------
import io  # noqa: E402
import logging.config  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402

import pytest  # noqa: E402
import uvicorn.config  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app import config, models  # noqa: E402
from app.pipeline import TraceRequest  # noqa: E402
from app.routes import cases  # noqa: E402

ADDRESS = "0x71c0" + "ab" * 16 + "9f3e"
TX = "0x" + "cd" * 32
TRON = "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf"
NCRP = "31911250012345"


@pytest.fixture
def sink(monkeypatch):
    """A handler on the root logger, as basicConfig makes on the server."""
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    log_safety.install()
    yield stream
    root.removeHandler(handler)


def test_a_padded_tron_key_never_reaches_the_log(sink, monkeypatch):
    monkeypatch.setattr(config, "TRONGRID_API_KEY", "TRONKEYSPACE123")
    monkeypatch.setenv("TRONGRID_API_KEY", "TRONKEYSPACE123 ")
    logging.getLogger("app.tron_client").warning(
        "TronGrid retry 1/2 in 0.00s (%s)", "Illegal header value b'TRONKEYSPACE123 '")
    logging.getLogger("app.tron_tags").warning("lookup failed: Illegal header value b'OTHERKEY987\\n'")
    text = sink.getvalue()
    assert "TRONKEYSPACE123" not in text and "OTHERKEY987" not in text
    assert "TronGrid retry" in text


def test_provider_keys_are_read_without_stray_whitespace(monkeypatch):
    """A key pasted with a trailing space or newline made httpx refuse the
    header and print the key in the error, on every Tron request."""
    monkeypatch.setenv("TRONGRID_API_KEY", " padded-key-123\n")
    monkeypatch.setenv("ETHERSCAN_API_KEY", "   ")
    assert config.secret_env("TRONGRID_API_KEY") == "padded-key-123"
    assert config.secret_env("ETHERSCAN_API_KEY") is None
    source = (config.BACKEND_DIR / "app" / "config.py").read_text()
    for name in ("ETHERSCAN_API_KEY", "NODEREAL_API_KEY", "TRONGRID_API_KEY", "TRONSCAN_API_KEY"):
        assert f'{name}: str | None = secret_env("{name}")' in source


def test_secret_values_are_redacted_wherever_they_appear(sink, monkeypatch):
    monkeypatch.setattr(config, "HEALTH_TOKEN", "health-token-abcdef123")
    monkeypatch.setattr(config, "BACKUP_TOKEN", "backup-token-abcdef456")
    monkeypatch.setattr(config, "DEMO_CODE", "demo-code-abcdef789")
    monkeypatch.setattr(config, "DATABASE_URL", "postgres://user:db-pass-word-42@host.neon.tech/db")
    monkeypatch.setenv("EXCHEQUER_SIGNING_KEY", "c2lnbmluZy1rZXktc2VlZC0zMi1ieXRlcy1sb25nIQ==")
    logging.getLogger("app.x").warning(
        "a=%s b=%s c=%s d=%s e=%s", "health-token-abcdef123", "backup-token-abcdef456",
        "demo-code-abcdef789", "postgres://user:db-pass-word-42@host", "c2lnbmluZy1rZXktc2VlZC0zMi1ieXRlcy1sb25nIQ==")
    logging.getLogger("app.x").warning("Authorization: Bearer some.other-token_99 sent")
    text = sink.getvalue()
    for secret in ("health-token-abcdef123", "backup-token-abcdef456", "demo-code-abcdef789",
                   "db-pass-word-42", "c2lnbmluZy1rZXk", "some.other-token_99"):
        assert secret not in text


def test_a_traceback_is_redacted(sink):
    try:
        raise ValueError(f"apikey=SECRET123 for {ADDRESS}")
    except ValueError:
        logging.getLogger("app.x").exception("failed")
    text = sink.getvalue()
    assert "ValueError" in text and "SECRET123" not in text and ADDRESS not in text


def test_on_a_public_host_a_traceback_is_one_line(sink, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_HOST", True)
    monkeypatch.delenv("EXCHEQUER_LOG_TRACEBACKS", raising=False)
    try:
        raise ValueError("apikey=SECRET456 boom")
    except ValueError:
        logging.getLogger("app.x").exception("failed")
    lines = [line for line in sink.getvalue().splitlines() if line]
    assert len(lines) == 1
    assert "ValueError" in lines[0] and "test_log_safety.py:" in lines[0]
    assert "Traceback" not in lines[0] and "SECRET456" not in lines[0]


def test_addresses_and_hashes_are_masked_in_messages(sink):
    logging.getLogger("app.x").warning("Could not fetch %s via %s on %s", ADDRESS, TX, TRON)
    text = sink.getvalue()
    for whole in (ADDRESS, TX, TRON):
        assert whole not in text
    assert ADDRESS[:6] in text and ADDRESS[-4:] in text


@pytest.fixture
def uvicorn_logging(monkeypatch):
    """uvicorn's own logging set up as the server sets it up; put back after."""
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    saved = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).propagate,
                 logging.getLogger(n).level) for n in names}
    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)
    yield
    for n, (handlers, propagate, level) in saved.items():
        logger = logging.getLogger(n)
        logger.handlers[:] = handlers
        logger.propagate, logger.level = propagate, level


def test_uvicorn_handlers_are_filtered(monkeypatch, uvicorn_logging):
    monkeypatch.setattr(config, "PUBLIC_HOST", True)
    if True:
        log_safety.install()
        for name in ("uvicorn", "uvicorn.access"):
            assert all(handler.filters for handler in logging.getLogger(name).handlers)
        stream = io.StringIO()
        error_handler = logging.getLogger("uvicorn").handlers[0]
        error_handler.setStream(stream)
        try:
            raise RuntimeError("apikey=KEYUV5 failed")
        except RuntimeError:
            logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
        text = stream.getvalue()
        assert "KEYUV5" not in text and "RuntimeError" in text
        assert len([line for line in text.splitlines() if line]) == 1


def test_access_lines_keep_their_shape_and_lose_ids_queries_and_addresses(uvicorn_logging):
    if True:
        log_safety.install()
        handler = logging.getLogger("uvicorn.access").handlers[0]
        stream = io.StringIO()
        handler.setStream(stream)
        case_id = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"
        for path in (f"/trace/{case_id}/report?format=pdf", f"/trace/{ADDRESS}?pay={TX}&ncrp={NCRP}",
                     "/health?apikey=QUERYKEY999"):
            logging.getLogger("uvicorn.access").info(
                '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", path, "1.1", 200)
        text = stream.getvalue()
        assert "/trace/<id>/report" in text
        for leak in (case_id, "?", TX, NCRP, "QUERYKEY999", ADDRESS):
            assert leak not in text
        assert text.count("200") == 3


def test_a_thread_crash_is_one_filtered_line(sink, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_HOST", True)

    def crash():
        raise RuntimeError(f"apikey=KEYTHR7 on {ADDRESS}")
    worker = threading.Thread(target=crash, name="batch-test")
    worker.start()
    worker.join()
    text = sink.getvalue()
    assert "batch-test" in text and "RuntimeError" in text
    assert "KEYTHR7" not in text and ADDRESS not in text
    assert len([line for line in text.splitlines() if line]) == 1


# -- the store's errors carry no complaint particulars -----------------------------------
def test_the_engine_hides_parameters(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "e.db")
    monkeypatch.setattr(config, "DATABASE_URL", "")
    assert models._make_engine().hide_parameters is True
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://u:p@localhost/x")
    assert models._make_engine().hide_parameters is True


def test_a_failed_save_logs_no_particulars(sink, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "f.db")
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(models, "_engine", models._make_engine())
    models.init_db()
    payload = {"address": ADDRESS, "intake": {"mode": "payment", "ncrp_ack": NCRP}}
    monkeypatch.setattr(models, "new_case_id", lambda: "dup-case-id")
    request = TraceRequest(address=ADDRESS)
    assert cases.store_result(dict(payload), request, "a" * 64)["case_id"] == "dup-case-id"
    again = cases.store_result(dict(payload), request, "a" * 64)  # same id: IntegrityError
    assert again["case_id"] is None
    text = sink.getvalue()
    assert "Failed to persist" in text
    for leak in (ADDRESS, NCRP, "[parameters", "a" * 64):
        assert leak not in text


def test_a_full_store_does_not_log_the_address(sink, monkeypatch, tmp_path):
    monkeypatch.setattr(models, "_engine", create_engine(f"sqlite:///{tmp_path / 'g.db'}", future=True))
    models.init_db()
    monkeypatch.setattr(config, "MAX_STORED_CASES", 1)
    monkeypatch.setattr(config, "MAX_CASES_PER_OWNER", 0)
    request = TraceRequest(address=ADDRESS)
    cases.store_result({"address": ADDRESS}, request, "b" * 64)
    full = cases.store_result({"address": ADDRESS}, request, "b" * 64)
    assert full["case_id"] is None
    text = sink.getvalue()
    assert "Case store full" in text and ADDRESS[6:-4] not in text
