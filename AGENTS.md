# DISMEPE ONE 2.0 — Base44 Dev Environment

## Overview
Single-origin FastAPI app (Python 3.12) that serves both the HTML frontend and the API
from one process. Entry point: `api.prod597_app:app`. No separate frontend dev server —
the backend serves static HTML/JS files via explicit route handlers.

## Running
- `docker compose -f docker-compose.base44.yml up -d` — starts the app on host port 3000.
- Base image: `python:3.12-slim` with `poppler-utils` (needed for PDF processing).
- Dependencies install at container startup via `pip install -r requirements.txt`.
- Uvicorn runs with `--reload` (WatchFiles) — edits to bind-mounted source hot-reload.
- Health check: `GET /health` returns JSON with `ok`, `version`, and `missingConfig`.

## Environment
- `.env.base44-defaults` — repo-level placeholders (first in env_file chain).
- `/run/base44/app.env` — platform-managed real secrets (always wins).
- `DISMEPE_CORS_ORIGINS` is set to the preview origin in compose `environment:`.
- `DISMEPE_COOKIE_SECURE=false` for dev (preview is HTTPS but this avoids cookie issues).

## Required Secrets (external — user must provide)
- `DISMEPE_SUPABASE_PUBLISHABLE_KEY` — Supabase anon/publishable key.
- `DISMEPE_EDGE_TOKEN` — Supabase Edge Function auth token.
- `DISMEPE_AUTH_PEPPER` — Secret pepper for password hashing.
- `DISMEPE_JWT_SECRET` — JWT signing secret (min 32 chars; generated dev placeholder exists).

Without these, the app boots and serves the portal page, but login/data endpoints fail.
The `/health` endpoint lists which are missing under `missingConfig`.

## Supabase
The app uses a hosted Supabase PostgreSQL instance (`DISMEPE_SUPABASE_URL` is hardcoded
in the defaults). No local database service is needed.

## Key Files
- `api/prod597_app.py` — final app composition (imports from `industries_app`).
- `api/industries_app.py` — creates the FastAPI app, serves portal HTML, route guards.
- `api/main.py` — base app with CORS, auth login, data endpoints.
- `api/config.py` — pydantic-settings config with `validate_required_secrets()`.
- `frontend/` — static HTML/JS files served by route handlers.
