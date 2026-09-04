# TraceChain — one image, one service.
#
# Stage 1 builds the React bundle; stage 2 runs FastAPI and serves that bundle
# itself. Shipping them together means the UI and API share an origin, so there
# is no CORS to configure, no second deployment to keep in step, and no backend
# URL baked into the frontend.
#
# A plain Dockerfile rather than a platform-specific config so the same image
# runs on Railway, Fly, Render or any VM with Docker.

# ---------- stage 1: build the frontend ----------
FROM node:20-slim AS frontend

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

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist

# Case history lives on a mounted volume so it survives a redeploy. Without a
# volume this still runs -- the store simply resets, which is fine for a demo
# but would lose archived cases.
ENV TRACECHAIN_DB_PATH=/data/tracechain.db
VOLUME ["/data"]

WORKDIR /app/backend
EXPOSE 8000

# Bind 0.0.0.0 and honour the platform's $PORT; most hosts assign one.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
