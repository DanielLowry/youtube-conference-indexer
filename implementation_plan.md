# YouTube Conference Indexer - Implementation Plan with Status

Legend: `[x]` = complete, `[~]` = partially complete, `[ ]` = not started.

--

## Testing Approach - [~]
Goal: lightweight, locally reproducible unit and regression checks.

- [x] Add a minimal `pytest` smoke suite (no network; stubbed settings).
- [x] Cover Phase 1/2 basics: root/sources pages render; playlist sources create playlists; channel discovery hydrates playlists.
- [x] GitHub Actions CI (Linux) runs pytest on push/PR.
- [ ] Expand coverage: CRUD (sources/playlists/pin), sync pipeline (mocked YouTube responses), search/FTS queries, export formatters once added.
- [ ] One-step local run: `pytest`.

--

## Documentation - [ ]
Goal: concise how-to-use guide for future you.

- [ ] Add `docs/how-to-use.md` covering setup, adding sources/playlists, discovery, pinning, sync, search, exports, and running tests.

--

## Phase 1: Foundation (Milestone 0) — MVP - [x]
Goal: Core project structure, dependencies, and minimal web app.

- [x] Project bootstrap: repo structure, `requirements.txt`, `.env`, FastAPI skeleton (`/`).
- [x] Dependencies: FastAPI, Uvicorn, SQLAlchemy, Alembic, dotenv, isodate, Jinja2, pydantic-settings, pytest.
- [x] DB + Alembic: SQLite connection, `alembic` config/env, `data/` ignored.
- [x] Initial schema and migration: sources/playlists created and applied.
- [x] Basic frontend: templates, static dir, base + index page wired.
- [x] Verification: smoke test for app startup and root route (`pytest tests/test_app_smoke.py`).

--

## Phase 2: Source Discovery and Pinning — MVP - [x]
Goal: Add/list/delete sources; discover playlists; pin playlists.

- [x] Models/schemas: Source, Playlist (with `pinned`), Pydantic schemas.
- [x] Sources CRUD API and UI: `/sources` list/add/delete with HTMX form.
- [x] Playlist discovery: channel discovery via YouTube API with HTMX update; playlist sources create immediate playlist entries.
- [x] Pinning: toggle endpoint `/playlists/{id}/pin` with UI star control.
- [~] Verification: add a real channel, fetch playlists, pin/unpin, confirm DB persistence.

--

## Phase 3: The Async Sync Engine — MVP - [~]
Goal: Ingest video metadata from pinned playlists.

- [x] Video model/schema and migrations; initial state creation on insert.
- [x] YouTube ingestion helpers: playlistItems plus videos batch with duration parsing.
- [~] Sync endpoint `/sync/run` and UI button exist, but run inline (no BackgroundTasks, no error handling).
- [ ] Background task integration: trigger per pinned playlist with FastAPI `BackgroundTasks`; keep request quick.
- [ ] Robustness: handle API failures/quota, log counts, return user-friendly status.
- [~] Verification: basic sync works; needs non-blocking run and validation against DB contents.

--

## Phase 4: Search and Curation — MVP - [~]
Goal: Full-text search plus curation state and tags.

- [x] FTS5 virtual table and triggers migration.
- [x] Search API/UI: `/search` with FTS-backed lookup and HTMX results.
- [~] Curation state: `video_states` auto-created, but no update endpoints/UI; tags tables exist but unused.
- [ ] Curation endpoints/UI: update status/notes/score, add/remove tags, show badges on results.
- [ ] Filtering: search filters (playlist, duration, etc.) and UI controls.
- [ ] Verification: search returns synced videos; status/tag changes persist and display.

--

## Phase 5: Export — MVP - [ ]
Goal: Export curated lists in Markdown/CSV.

- [ ] Export logic: `export.py` with Markdown/CSV generators.
- [ ] Export endpoints: `/export/markdown`, `/export/csv` returning files for selected states (e.g., queued).
- [ ] UI: buttons to trigger exports.
- [ ] Verification: download files contain expected metadata.

--

## Phase 6: Optimization — Post-MVP - [ ]
Goal: Efficiency and usability improvements.

- [ ] Incremental refresh: skip already-synced video IDs per playlist.
- [ ] Bulk actions: Alpine.js select-all with endpoint for batch status updates.
- [ ] Observability: `sync_runs` table for timings/status/new counts; status page display.
