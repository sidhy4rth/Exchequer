# ADR-0001: One Docker image serves both the API and the UI

**Date**: 2026-09-05
**Status**: accepted
**Deciders**: Sidhyarth

## Context

Exchequer is a FastAPI backend and a React frontend. It has to run on free
hosting, be brought up in a minute before a demo, and never fail because the
two halves drifted apart or disagreed about where the other one lives.

## Decision

A two-stage `Dockerfile`: stage one builds the React bundle, stage two runs
FastAPI and serves that bundle itself (`app/main.py`, the catch-all at the
bottom). The UI calls the API on the same origin, with `VITE_API_BASE=""`.

## Alternatives Considered

### Separate frontend host (Vercel/Netlify) and API host
- **Pros**: free static hosting, CDN for the bundle.
- **Cons**: two deployments to keep in step, CORS to configure, the API URL baked into the bundle.
- **Why not**: every extra moving part is a way for a live demo to fail.

### Platform-specific config (Nixpacks, a Procfile)
- **Pros**: less to write.
- **Cons**: ties the app to one host.
- **Why not**: a plain Dockerfile runs on Railway, Fly, Render or any VM unchanged.

## Consequences

### Positive
- One deploy, one URL, no CORS in production.
- A deep link (`/case/<id>`) reloads correctly: any path the API does not claim returns `index.html`.

### Negative
- A frontend-only change still rebuilds and redeploys the backend image.

### Risks
- A cached `index.html` pointing at an old bundle would call the wrong API base. Mitigated: the shell is served with `Cache-Control: no-cache, no-store`.
