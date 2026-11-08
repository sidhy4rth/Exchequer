"""Exchequer FastAPI application.

Endpoints:
    POST /trace                     trace a reported address (waits for the result)
    POST /trace/jobs                trace in the background; watch /trace/jobs/{id}/events
    GET  /trace/{case_id}           retrieve a stored case
    GET  /trace/{case_id}/report    exportable report (json or text)
    GET  /cases                     history of past traces
    GET  /exchanges                 what the label database covers
    GET  /ledger                    the addresses the tool knows, for the sign-in backdrop
    GET  /health                    liveness + configuration check
    GET  /signing-key               public key that signs exported reports
    POST /verify                    check a text report's hash and signature
    /watches, /alerts               watch an address; alerts when funds leave it
    /requests                       freeze requests sent about a case, and their status
    /batches                        trace a list of complaints, then correlate them

This module is the application shell: startup checks, CORS, the routers and
the built frontend. The endpoints live in app/routes/ (coverage.py, cases.py,
evidence.py, casebook.py and others) and the trace itself in app/pipeline.py.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import DataError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from . import batches as batch_runner
from . import api_budget, backups, config, log_safety, models, rate_limit, warmup, watchlist, webhook_vault
from . import access
from .access import DemoCodeMiddleware
from .input_rules import ControlCharMiddleware
from .security_headers import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from .chain_data import provider_status
from .exchange_matcher import get_matcher
from .risk_matcher import FROZEN, MIXER, SANCTIONED, STOLEN, get_risk_matcher
from .routes import admin, batches, casebook, cases, coverage, demos, evidence, jobs, requests, verify, watches

# Re-exported: scripts (scout.py) and the warm-up call the pipeline by these
# names. The pipeline itself lives in app/pipeline.py.
from .pipeline import TraceRequest, run_trace  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# Before any provider is called: httpx would otherwise log request URLs, keys
# included, and uvicorn's own handlers and access log are filtered too. See
# app/log_safety.py.
log_safety.install()
logger = logging.getLogger(__name__)


# The case store at startup: tried this many times (seconds to wait before
# each try), well inside the host's boot window. If it still cannot be
# reached the site starts without it -- the UI, /health, the recorded demos
# and /verify need no store -- and a background thread retries every
# DB_RETRY_SECONDS. A database outage used to stop the whole site at its next wake.
DB_STARTUP_DELAYS = (0.0, 2.0, 5.0)
DB_RETRY_SECONDS = 60.0


def _short(exc: Exception) -> str:
    """The error's type and first line: enough to diagnose, never a connection string."""
    first = str(exc).splitlines()[0] if str(exc) else ""
    return f"{type(exc).__name__}: {first[:200]}"


def _open_store() -> bool:
    """Bring the store to the current schema, then mark batches a restart cut
    short. False if the store cannot be reached."""
    try:
        models.init_db()
    except Exception as exc:  # noqa: BLE001 -- the site must start without its store
        logger.error("Case store unavailable: %s", _short(exc))
        return False
    try:
        # A restart stops running batches; say so on their rows.
        batch_runner.mark_interrupted()
    except Exception as exc:  # noqa: BLE001 -- a read-only store still serves cases
        logger.error("Could not mark interrupted batches: %s", _short(exc))
    try:
        sealed = watchlist.seal_legacy_hooks()
        if sealed:
            logger.info("Sealed %d stored webhook URLs", sealed)
    except Exception as exc:  # noqa: BLE001 -- the hooks still work unsealed
        logger.error("Could not seal stored webhook URLs: %s", _short(exc))
    return True


def _retry_store_in_background() -> None:
    def loop() -> None:
        while not _open_store():
            time.sleep(DB_RETRY_SECONDS)
        logger.info("Case store reachable again")
    threading.Thread(target=loop, name="store-retry", daemon=True).start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Again, for any handler set up after this module was imported.
    log_safety.install()
    for delay in DB_STARTUP_DELAYS:
        if delay:
            await asyncio.sleep(delay)
        if _open_store():
            break
    else:
        logger.error("Starting without the case store; its routes answer 503 until it is back")
        _retry_store_in_background()
    for key, chain in config.CHAINS.items():
        matcher = get_matcher(key)
        if not len(matcher):
            logger.warning(
                "No exchange labels for %s -- traces on that chain will graph "
                "but never attribute",
                chain.name,
            )
    for key, chain in config.CHAINS.items():
        risk = get_risk_matcher(key)
        if len(risk):
            counts = risk.counts_by_category()
            logger.info(
                "%s: screening against %d sanctioned, %d mixer, %d Tether-frozen and %d stolen-funds addresses",
                chain.name, counts[SANCTIONED], counts[MIXER], counts[FROZEN], counts[STOLEN],
            )
        else:
            logger.warning(
                "No risk labels for %s -- traces on that chain will not be "
                "screened against sanctions or mixer lists",
                chain.name,
            )
    access.report_at_startup()
    logger.info("Per-client limits key on %s", rate_limit.rule())
    for status in provider_status().values():
        if status["ready"]:
            logger.info("%s: ready via %s", status["name"], status["provider"])
        else:
            logger.warning("%s unavailable: %s", status["name"], status["detail"])
    # After the providers are known to be configured: the demo addresses are
    # traced in the background so the first real request finds them cached.
    warmup.start_in_background()
    # Watched addresses are re-read on a schedule (off unless EXCHEQUER_WATCHER).
    webhook_vault.warn_if_unsealed()
    watchlist.start_in_background()
    # A daily snapshot of the store beside it (off unless EXCHEQUER_BACKUPS).
    backups.start_in_background()
    yield
    backups.stop()
    watchlist.stop()
    api_budget.flush_meters()  # the day's provider spend survives the restart


app = FastAPI(
    title="Exchequer",
    description=(
        "Traces cryptocurrency fraud from a victim-reported wallet address to "
        "the exchange it was cashed out through."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if config.API_DOCS_ENABLED else None,
    redoc_url="/redoc" if config.API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if config.API_DOCS_ENABLED else None,
)

@app.exception_handler(OperationalError)
@app.exception_handler(InterfaceError)
@app.exception_handler(PoolTimeoutError)
async def store_unavailable(_request: Request, exc: Exception) -> JSONResponse:
    """The database could not be reached, or every pooled connection is busy
    (PoolTimeoutError): say so, rather than a bare 500."""
    logger.error("Case store unavailable: %s", _short(exc))
    return JSONResponse(status_code=503, headers={"Retry-After": "60"},
                        content={"detail": "The case store is unavailable right now. Try again in a minute."})


@app.exception_handler(DataError)
async def cannot_store(_request: Request, exc: DataError) -> JSONResponse:
    """A value the store refused (a NUL, a string past its column): the
    caller's input, so a 400. The edge rules (input_rules.py) catch the known
    cases first; this is the net under them."""
    logger.warning("Store refused a value: %s", _short(exc.orig if exc.orig is not None else exc))
    return JSONResponse(status_code=400, content={"detail": "That input cannot be stored."})


# Added first, so innermost: its refusals still pass through the security
# headers and CORS added after it. See access.py.
app.add_middleware(DemoCodeMiddleware)
# Control characters in a path or query are refused before any route runs.
app.add_middleware(ControlCharMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# The React dev server runs on a different origin during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# What the tool covers and whether it is up (/health, /exchanges,
# /risk-labels, /ledger), then tracing and the case store (/trace, reports,
# letters, /cases). Registered before the static catch-all below.
app.include_router(coverage.router)
app.include_router(access.router)
# Jobs first: /trace/jobs/... must not be read as /trace/{case_id}/...
app.include_router(jobs.router)
app.include_router(cases.router)
app.include_router(evidence.router)
app.include_router(casebook.router)
app.include_router(demos.router)
app.include_router(verify.router)
app.include_router(watches.router)
app.include_router(requests.router)
app.include_router(batches.router)
app.include_router(admin.router)


# ---------------------------------------------------------------------------
# Static frontend
#
# In development the Vite dev server serves the UI and proxies /api here. In
# the deployed image there is no Vite: the built bundle is copied in and served
# by this app, so the UI and the API share one origin. That removes CORS, the
# second deployment, and any need for the frontend to know a backend URL.
#
# This block is registered last on purpose. FastAPI matches routes in
# definition order, so /health, /trace and the rest are already claimed before
# the catch-all below sees a request.
# ---------------------------------------------------------------------------
FRONTEND_DIR = config.BACKEND_DIR.parent / "frontend" / "dist"

if FRONTEND_DIR.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIR / "assets"),
        name="assets",
    )
    logger.info("Serving frontend from %s", FRONTEND_DIR)
else:
    logger.info("No built frontend at %s -- API only", FRONTEND_DIR)


def _is_page_load(request: Request) -> bool:
    """A browser opening the URL, as opposed to fetch(), curl or a script.

    The same test routes/cases.py applies to /trace/{id}: browsers send
    Sec-Fetch-Mode, and an older one still asks for text/html."""
    mode = request.headers.get("sec-fetch-mode")
    if mode:
        return mode == "navigate"
    return "text/html" in request.headers.get("accept", "")


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """What was wrong with a request, without echoing what it sent: the input
    may be a victim's details, and a NaN or Infinity in it cannot be written
    as JSON at all (the default reply then failed with a 500)."""
    errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
              for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def spa(full_path: str, request: Request):
    """The single-page app for a browser opening any path the API did not
    claim; a JSON 404 for anything else.

    The UI routes on the client (/trace/0x…, /case/<id>), so a deep link
    opened directly or reloaded must still return index.html -- the router
    then reads the URL and renders the right screen. But a fetch() or a
    script asking for a path the API does not have used to get that page
    too, with a 200: a mistyped call, or a build with the wrong API base,
    then failed as "backend unreachable" instead of as a 404.
    """
    index = FRONTEND_DIR / "index.html"
    # A real file (favicon, manifest) is served as itself.
    try:
        candidate = (FRONTEND_DIR / full_path).resolve()
        is_file = bool(full_path) and candidate.is_file()
    except (OSError, ValueError):  # a NUL byte, a segment too long for the filesystem
        is_file = False
    if is_file and FRONTEND_DIR.resolve() in candidate.parents:
        return FileResponse(candidate)
    if not index.is_file() or not _is_page_load(request):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    # The shell must never be cached: a stale index.html keeps pointing at
    # asset hashes from a previous build, and the old bundle then calls the
    # wrong API base and reports the backend as unreachable.
    return FileResponse(index, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
