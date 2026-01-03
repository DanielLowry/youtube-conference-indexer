# YouTube Conference Indexer - Implementation Plan with Status

Legend: `[x]` = complete, `[~]` = partially complete, `[ ]` = not started.

--

## Testing Approach - [~]
Goal: lightweight, locally reproducible unit and regression checks.

- [x] Add a minimal `pytest` smoke suite (no network; stubbed settings).
- [x] Cover Phase 1/2 basics: root/sources pages render; playlist sources create playlists; channel discovery hydrates playlists.
- [x] GitHub Actions CI (Linux) runs pytest on push/PR.
- [~] Expand coverage: CRUD (sources/playlists/pin), sync pipeline (mocked YouTube responses), search/FTS queries, export formatters once added.
- [~] One-step local run: `pytest`.
- [ ] One-command dev loop: helper target/script to install deps, run tests, and start the server (`uv pip install -r requirements.txt && uv run pytest && uv run uvicorn app.main:app --reload`).

--

## Documentation - [x]
Goal: concise how-to-use guide for future you.

- [x] Add `docs/how-to-use.md` covering setup, adding sources/playlists, discovery, pinning, sync, search, exports, and running tests.

--

## Phase 1: Foundation (Milestone 0) - MVP - [~]
Goal: Core project structure, dependencies, and minimal web app.

- [x] Project bootstrap: repo structure, `requirements.txt`, `.env`, FastAPI skeleton (`/`).
- [x] Dependencies: FastAPI, Uvicorn, SQLAlchemy, Alembic, dotenv, isodate, Jinja2, pydantic-settings, pytest.
- [x] DB + Alembic: SQLite connection, `alembic` config/env, `data/` ignored.
- [ ] Baseline migration: add an initial Alembic revision under `alembic/versions` and use `alembic upgrade head` instead of runtime table creation.
- [~] Initial schema and migration: sources/playlists created and applied.
- [x] Basic frontend: templates, static dir, base + index page wired.
- [ ] UI cleanup: remove stray characters in templates, replace garbled text with plain ASCII, and add a small alert/log area for background errors.
- [x] Verification: smoke test for app startup and root route (`pytest tests/test_app_smoke.py`).

--

## Phase 2: Source Discovery and Pinning - MVP - [~]
Goal: Add/list/delete sources; discover playlists; pin playlists.

- [x] Models/schemas: Source, Playlist (with `pinned`), Pydantic schemas.
- [x] Sources CRUD API and UI: unified on `/` (home) with HTMX form; nav simplified (no separate Sources tab).
- [x] Playlist discovery: channel discovery via YouTube API with HTMX update; playlist sources create immediate playlist entries.
- [x] Pinning: toggle endpoint `/playlists/{id}/pin` with UI star control.
- [~] Verification: add a real channel, fetch playlists, pin/unpin, confirm DB persistence.

--

## Phase 3: The Async Sync Engine - MVP - [~]
Goal: Ingest video metadata from pinned playlists.

- [x] Video model/schema and migrations; initial state creation on insert.
- [x] YouTube ingestion helpers: playlistItems plus videos batch with duration parsing.
- [x] Sync endpoint `/sync/run` schedules per-playlist background tasks; sync helper handles inserts/idempotence.
- [ ] Sync dry-run: mode to report planned work without calling YouTube (useful for quota/testing).
- [ ] Robustness: handle API failures/quota, log counts, return user-friendly status.
- [~] Verification: background sync covered in tests; needs live API check for real playlists.

--

## Phase 4: Search and Curation - MVP - [~]
Goal: Full-text search plus curation state and tags.

- [x] FTS5 virtual table and triggers migration.
- [x] Search API/UI: `/search` with FTS-backed lookup and HTMX results.
- [x] Curation state + tags: endpoints/UI to update status/notes/score; add/remove tags; badges on results.
- [ ] Filtering: search filters (playlist, duration, etc.) and UI controls.
- [ ] Local sample data: lightweight seed script to populate sources/playlists/videos without YouTube calls (works in in-memory mode).
- [x] Verification: search returns synced videos; status/tag changes persist (tests cover status/tags).

--

## Phase 5: Export - MVP - [~]
Goal: Export curated lists in Markdown/CSV.

- [x] Export logic: `export.py` with Markdown/CSV generators.
- [x] Export endpoints: `/export/markdown`, `/export/csv` returning files for selected states (e.g., queued).
- [x] UI: buttons to trigger exports.
- [ ] Export skip-sync toggle: option to skip the pre-sync step when exporting.
- [~] Verification: tests cover export generation; manual download check recommended.

--

## Phase 6: DB-Optional Mode - Post-MVP - [~]
Goal: Allow running without a persistent DB, with clear warnings and a toggle.

- [x] Detect unreachable/missing DB on startup and fall back to in-memory with a prominent home-page warning.
- [x] Add UI control to switch to “DB-free” mode (in-memory) and to re-attempt connecting to the configured DB; warn that state is ephemeral.
- [~] Gracefully degrade DB-dependent features (sync/search/exports) with clear messaging when in DB-free mode.
- [x] Update docs and tests to cover DB-optional behavior (docs done; tests still to add).
- [ ] Resilience shortcuts: auto-fallback to in-memory on DB errors without prompting and a “replay last successful sync” button using cached IDs to recover after API hiccups.

--

## Phase 7: Live UX & Async Orchestration - Post-MVP - [ ]
Goal: “Modern app” responsiveness: prefetch, optimistic UI, background sync, and visible progress.

- [ ] Channel selection auto-loads playlists (no extra click): htmx `change delay:150ms` with `hx-sync="this:abort"` and indicator; cache playlists per channel for ~1h; “Refresh” override button.
- [ ] Pinning is optimistic + triggers fetch immediately: UI updates star instantly; server enqueues background video fetch; pinned row polls status (`load, every 1s`) until done/error, then stops.
- [ ] Background sync everywhere: trigger on pin/pin-all, on page load (stale-while-revalidate), and on timer; exports should only format cached data (never start heavy work).
- [ ] Progress UX: per-playlist status dashboard (Queued/Fetching N/M/Ready/Error/Cancelled), progressive counts for large playlists, disable controls while in-flight; cancel/abort stale work when unpinning.
- [ ] Async hygiene: use `hx-queue`, `hx-sync`, debounce (`delay:`), clear indicators, and job-based status endpoint to avoid races; stale-while-revalidate fragments update when fresh data arrives.
- [ ] Prefetch/cache warming: trigger lightweight background requests on hover/load where useful; rely on server-side caching to make subsequent interactions instant.
- [ ] Observability/logging: rich console logs for prefetch, background jobs, cache hits/misses, sync progress, retries/backoff.
- [ ] Personal observability: simple rotating file logger and a `/admin/debug` page showing DB mode, pinned counts, and last sync/error state.

--

## Phase 8: Optimization - Post-MVP - [ ]
Goal: Efficiency and usability improvements.

- [ ] Incremental refresh: skip already-synced video IDs per playlist.
- [ ] Bulk actions: Alpine.js select-all with endpoint for batch status updates.
- [ ] Observability: `sync_runs` table for timings/status/new counts; status page display.
- [ ] Optional DB portability: export/import a SQLite file so it can be moved to another device.

--
