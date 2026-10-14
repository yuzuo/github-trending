# GitHub Trending Implementation Plan

> Execute inline with superpowers:executing-plans; user authorized implementation. No existing Git repository or code to isolate.

**Goal:** Deliver a local daily Trending collector with persisted repository metadata and Chinese README display.

**Architecture:** One FastAPI process runs HTTP API and a daily scheduler. SQLAlchemy persists repositories, daily snapshots and collection runs in PostgreSQL 16. Vue 3 served by Nginx proxies API requests.

**Tech Stack:** Python, FastAPI, SQLAlchemy, psycopg, httpx, BeautifulSoup, Vue 3, Vite, markdown-it, DOMPurify, Docker Compose.

## 1. Backend behavior
- [x] Create backend/tests/test_sources.py and fixtures/trending.html: numbers with separators, missing growth, empty page, missing README, rate-limit handling.
- [x] Create backend/tests/test_translation.py: preserve code and links, split long content, reject incomplete completions, retain old translation on failure.
- [x] Run `python -m unittest discover -s backend/tests -v` and observe missing implementation failures.
- [x] Implement backend/app/sources.py and translation.py against these cases.

## 2. Storage and API
- [x] Create backend/app/config.py, database.py, models.py, collector.py and main.py.
- [x] Test repeated same-day collection creates one snapshot, historical snapshots survive, failed translation preserves data, sorting/search and request origin validation.
- [x] Use a dedicated PostgreSQL test database when available; never clear application data to run tests.
- [x] Run `python -m unittest discover -s backend/tests -v`; report unavailable PostgreSQL integration separately.

## 3. Frontend
- [x] Create frontend/package.json, Vite config, src/App.vue, src/main.js, src/style.css and src/markdown.js.
- [x] Implement date/search/language controls, status, collection action, detail view and original/Chinese README.
- [x] Test malicious Markdown, safe relative links and images with `npm test`; build with `npm run build`.

## 4. Deployment and end-to-end checks
- [x] Create backend/Dockerfile, frontend/Dockerfile, frontend/nginx.conf, compose.yaml, .env.example and README.md.
- [x] Verify `docker compose --env-file .env.example config --quiet`.
- [x] Attempt Docker engine access and start the stack if available. Otherwise verify backend and frontend locally and record the exact limitation.
- [x] Run a live GitHub source smoke check without invoking a paid translation service. Live translation requires user-configured local credentials.
- [x] Read code for failure handling, exposed secrets, XSS, data retention and scheduler overlap; fix findings and re-run affected checks.

## Completion evidence
Record actual check outputs in README or final handoff. Do not equate fixture tests with live translation or PostgreSQL verification. No user accounts, notifications or whole-GitHub coverage added.
