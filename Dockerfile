# syntax=docker/dockerfile:1
# Exchequer — one image, one service.
#
# Stage 1 builds the React bundle; stage 2 runs FastAPI and serves that bundle
# itself. Shipping them together means the UI and API share an origin, so there
# is no CORS to configure, no second deployment to keep in step, and no backend
# URL baked into the frontend.
#
# A plain Dockerfile rather than a platform-specific config so the same image
# runs on Railway, Fly, Render or any VM with Docker.

# ---------- stage 1: build the frontend ----------
FROM node:24-slim AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Empty base = same-origin requests (/health, /trace). In development this is
# "/api" and Vite proxies it; here FastAPI answers directly.
ENV VITE_API_BASE=""
RUN npm run build

# ---------- stage 2: the application ----------
FROM python:3.12-slim AS app

# Unbuffered so logs appear in the platform's log viewer immediately rather
# than sitting in a pipe buffer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The lock pins and hashes every package (backend/requirements.in says how it
# is made): pip refuses anything else, and installs wheels only, so no
# package's setup.py runs here.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r backend/requirements.txt

COPY backend/ ./backend/

# The risk-label store: millions of hunt addresses, kept in a PRIVATE release
# rather than in git (too large, and not for publishing). Fetched here with a
# read-only token from a build secret -- on Render, a Secret File named
# label_store_token -- so the token never enters a layer. No token fails the
# build, so the live version stays up rather than a deploy shipping without
# its labels; a build that has no secret on purpose (CI's image job, a fork, a
# local build) passes --build-arg LABEL_STORE_REQUIRED=0 and screens against
# the label files only. The mount stays optional so the script, not BuildKit,
# prints the reason.
# A new store = a new release tag + sha256 here. See backend/scripts/fetch_label_store.py.
ARG LABEL_STORE_REPO="sidhy4rth/exchequer-labels"
ARG LABEL_STORE_TAG="labels-2026-11-05b"
ARG LABEL_STORE_SHA256="f3e1d3b597768234e5b3d2eec14e1365c0c14bdbd9cc771ecd0209dd954e9846"
ARG LABEL_STORE_REQUIRED="1"
RUN --mount=type=secret,id=label_store_token,required=false \
    cd backend && LABEL_STORE_REQUIRED="$LABEL_STORE_REQUIRED" LABEL_STORE_REPO="$LABEL_STORE_REPO" \
    LABEL_STORE_TAG="$LABEL_STORE_TAG" LABEL_STORE_SHA256="$LABEL_STORE_SHA256" python -m scripts.fetch_label_store
# What /health/detail reports: whether this image was built to carry the store, and which.
ENV EXCHEQUER_LABEL_STORE_REQUIRED=${LABEL_STORE_REQUIRED} EXCHEQUER_LABEL_STORE_TAG=${LABEL_STORE_TAG}
COPY --from=frontend /build/dist ./frontend/dist

# The image has no .git, so the report's "tool version" line is baked in at
# build time: `docker build --build-arg EXCHEQUER_VERSION=$(git describe --always)`.
# Railway sets RAILWAY_GIT_COMMIT_SHA automatically; either is read at startup.
ARG EXCHEQUER_VERSION=""
ENV EXCHEQUER_VERSION=${EXCHEQUER_VERSION}

# Case history lives at /data so a volume mounted there survives a redeploy.
# Mount one from the platform (Railway rejects a Dockerfile VOLUME line and
# expects its own volumes; `docker run -v` works the same). Without a volume
# this still runs -- the store simply resets, which is fine for a demo but
# would lose archived cases.
ENV EXCHEQUER_DB_PATH=/data/exchequer.db
RUN mkdir -p /data

# The app runs as this unprivileged user; docker-entrypoint.sh hands it the
# volume and drops to it, falling back to root if the volume will not allow
# that rather than failing to start.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

# The provider response cache also lives on the volume (beside the case
# store, by default), so a redeploy does not forget every response.

# No interactive API docs on the public site: they map every endpoint and
# Swagger UI needs a looser content policy than the app (security_headers.py).
ENV EXCHEQUER_API_DOCS=0

# Nothing that runs in the background or trusts a proxy is turned on here:
# each host opts in, in its own settings (render.yaml for Render). An image
# that turned them on relied on every host turning them off again, and a host
# whose settings drifted ran them anyway. On a host with a lasting disk:
#   EXCHEQUER_WARM_CACHE=1  trace the demos at startup so they answer from cache
#   EXCHEQUER_WATCHER=1     re-read watched addresses every 10 minutes
#   EXCHEQUER_BACKUPS=1     a daily snapshot of a SQLite store on the volume
# (on a temporary disk they stay off unless set to "force"; config.host_flag).
# No EXCHEQUER_TRUST_PROXY either: a host with no proxy in front would then key
# every limit on a header the client wrote. Render and Railway are detected
# from their own variables (config.proxy_mode); anything else sets it itself.

WORKDIR /app/backend
EXPOSE 8000

# Binds 0.0.0.0 and honours the platform's $PORT; most hosts assign one.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
CMD ["/usr/local/bin/docker-entrypoint.sh"]
