# Crawler Watch Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the independent frontend task; implement backend locally and review integration before delivery.

**Goal:** Discover, monitor and review crawler/data collection repositories in a separate page.

**Architecture:** Independent watch tables and API share the existing GitHub client, PostgreSQL lock, scheduler lifecycle and rate-limit protection. A dedicated Vue page consumes the watch API without changing existing snapshot sources.

**Tech Stack:** Existing FastAPI / SQLAlchemy / PostgreSQL / Vue / node:test / unittest. No additional runtime dependencies.

## Tasks

- [x] Write failing unit tests for repository input, growth baselines, stale ranking and discovery; run `.venv/Scripts/python.exe -m unittest discover -s backend/tests` with backend import path.
- [x] Add `backend/app/watch.py` (metrics, models usage, collection), `watch_api.py` (validated CRUD and queries), watch models in `models.py`; cover add/update/history/capacity with isolated PostgreSQL tests in `backend/tests/test_watch.py`.
- [x] Connect monitor to `main.py`, sharing `collector.busy`, advisory lock and cooldown; add recovery and scheduler tests. Keep existing sources unchanged.
- [x] Implement `frontend/src/Watch.vue` and frontend helpers/tests; update `main.js` and `App.vue` navigation. Run `npm test` and `npm run build`.
- [x] Run backend suite in Docker with existing dedicated `trending_test` database and random schemas; run frontend suite/build. Review spec coverage and correctness independently.
- [x] Update README, product documentation and config example. Back up database, rebuild local API/Web, verify health and new page. Report real network checks separately.

## API contract for frontend

- `GET /api/watch/projects?q=&language=&view=all|following|pending|hidden&sort=growth_7d|growth_24h|stars` returns `{items, languages, active_count, limit:200}`.
- Item fields: `id, full_name, description, language, license, html_url, stars, pushed_at, fetched_at, followed, hidden, manual, review_status, rating, notes, discovered_by, last_error, stale, growth_24h, growth_7d`. Growth is null or `{delta, start, end}`. Status enum: `pending|reviewing|reviewed|dismissed`.
- `GET /api/watch/projects/{id}` returns item plus `readme_original, readme_path, default_branch, history:[{stars,fetched_at}]` (last 100 samples).
- `POST /api/watch/projects` JSON `{repository:"owner/repo or GitHub URL"}` returns item; `PATCH /api/watch/projects/{id}` accepts subset of `followed, hidden, review_status, rating, notes`, returns item. Errors use string `detail`.
- `POST /api/watch/refresh` JSON `{}` returns 202 accepted or 409 busy/cooling.
- `GET /api/watch/run` returns latest task or null: `id,status,started_at,finished_at,success_count,failure_count,error,retry_at,discovery_done`; statuses match existing collector. Poll every 4 seconds; refresh list on completion.
- All mutation endpoints require JSON and same-origin validation. No automatic translation.

## Review focus

Growth must never invent baseline data, missing data sorts last, stale samples marked after 12 hours. Concurrent mutations must serialize capacity decisions. Hidden records stay hidden on discovery. Partial failures preserve old data. Run state must be created before responding to refresh. No write to old snapshots.

No Git repository exists here: commits/worktrees are inapplicable. User approved implementation; continue without another approval gate.
