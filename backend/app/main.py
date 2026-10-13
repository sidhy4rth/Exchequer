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

This module is the application shell: startup checks, CORS, the routers and
the built frontend. The endpoints live in app/routes/ (coverage.py, cases.py)
and the trace itself in app/pipeline.py.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, log_safety, models, warmup
from .security_headers import SecurityHeadersMiddleware
from .chain_data import provider_status
from .exchange_matcher import get_matcher
from .risk_matcher import FROZEN, MIXER, SANCTIONED, STOLEN, get_risk_matcher
from .routes import cases, coverage, jobs, verify

# Re-exported: scripts (scout.py) and the warm-up call the pipeline by these
# names. The pipeline itself lives in app/pipeline.py.
from .pipeline import TraceRequest, run_trace  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# Before any provider is called: httpx would otherwise log request URLs, keys
# included. See app/log_safety.py.
log_safety.install()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    models.init_db()
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
    for key, status in provider_status().items():
        if status["ready"]:
            logger.info("%s: ready via %s", status["name"], status["provider"])
        else:
            logger.warning("%s unavailable: %s", status["name"], status["detail"])
    # After the providers are known to be configured: the demo addresses are
    # traced in the background so the first real request finds them cached.
    warmup.start_in_background()
    yield


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
# Jobs first: /trace/jobs/... must not be read as /trace/{case_id}/...
app.include_router(jobs.router)
app.include_router(cases.router)
app.include_router(verify.router)


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

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Serve the single-page app for any path the API did not claim.

        The UI routes on the client (/trace/0x…, /case/<id>), so a deep link
        opened directly or reloaded must still return index.html rather than a
        404 -- the router then reads the URL and renders the right screen.
        """
        # A real file (favicon, manifest) is served as itself.
        candidate = (FRONTEND_DIR / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        # The shell must never be cached: a stale index.html keeps pointing at
        # asset hashes from a previous build, and the old bundle then calls the
        # wrong API base and reports the backend as unreachable.
        return FileResponse(
            FRONTEND_DIR / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    logger.info("Serving frontend from %s", FRONTEND_DIR)
else:
    logger.info("No built frontend at %s -- API only", FRONTEND_DIR)
