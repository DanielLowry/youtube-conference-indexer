# YouTube Conference Indexer — Detailed Implementation Plan

This document breaks down the project into a concrete, step-by-step guide suitable for implementation. Each step is designed to be a small, verifiable unit of work.

---

## Phase 1: Foundation (Milestone 0) — MVP

**Goal:** Set up the core project structure, dependencies, and a minimal working web application that can serve a page.

1.  **Initialize Project and Environment:**
    *   Use `uv` to create a new virtual environment: `uv venv`
    *   Activate the environment: `source .venv/bin/activate` (or `.venv\Scripts\activate.bat` on Windows).
    *   Create a `requirements.txt` file.

2.  **Install Core Dependencies:**
    *   Add the following to `requirements.txt`:
        ```
        fastapi
        uvicorn[standard]
        sqlalchemy
        alembic
        python-dotenv
        isodate
        ```
    *   Install dependencies: `uv pip install -r requirements.txt`

3.  **Set up FastAPI Skeleton:**
    *   Create a directory `app`.
    *   Create `app/main.py` with a basic FastAPI app instance and a single root endpoint (`/`).
    *   Create a `.env` file for environment variables (e.g., `YOUTUBE_API_KEY`).
    *   Create a `config.py` to load settings from the `.env` file.

4.  **Database and Alembic Setup:**
    *   Create a `database.py` to handle SQLite connection logic. The database file should be in a `data` directory (e.g., `data/indexer.db`). Add `data/` to `.gitignore`.
    *   Initialize Alembic: `alembic init alembic`
    *   Configure `alembic/env.py` to point to the SQLite database.
    *   Modify `alembic.ini` to set `sqlalchemy.url`.

5.  **Initial Schema and Migration:**
    *   Create `models.py` to define the initial SQLAlchemy models for `sources` and `playlists`.
    *   Generate the first migration: `alembic revision --autogenerate -m "Initial schema"`
    *   Apply the migration: `alembic upgrade head`

6.  **Basic Frontend Structure:**
    *   Create `templates` and `static` directories.
    *   Add `jinja2` to `requirements.txt` and install it.
    *   Configure FastAPI to use Jinja2 templates.
    *   Create a base template (`base.html`) and an index page (`index.html`).
    *   The root endpoint should render `index.html`.

7.  **Verification (MCP Checkpoint):**
    *   Run the app: `uvicorn app.main:app --reload`
    *   The app should be accessible at `http://127.0.0.1:8000`.
    *   The `data/indexer.db` file should exist.
    *   The Alembic migration should be applied.

---

## Phase 2: Source Discovery & Pinning — MVP

**Goal:** Allow users to add YouTube channels/playlists as sources and pin playlists for indexing.

1.  **Models and Schemas:**
    *   Finalize the `Source` and `Playlist` models in `models.py`.
    *   Create Pydantic schemas in `schemas.py` for API validation (e.g., `SourceCreate`, `PlaylistUpdate`).

2.  **Sources CRUD API & UI:**
    *   Create a `crud.py` file for database operations.
    *   Implement CRUD functions for `Source` (create, read, delete).
    *   Create FastAPI endpoints in `main.py` for `/sources`.
    *   Create a `sources.html` template to list sources and a form to add new ones using HTMX for submission.

3.  **Playlist Discovery Logic:**
    *   Create a `youtube.py` service to interact with the YouTube Data API v3.
    *   Implement a function `get_channel_playlists(channel_id)` that uses `playlists.list`.
    *   Integrate this with a "discover" button on the sources page. This should be a background task.

4.  **Pinning System:**
    *   Add a `pinned` boolean field to the `playlists` table (and model).
    *   Create an endpoint `POST /playlists/{playlist_id}/pin` that toggles the `pinned` status.
    *   Use HTMX on the playlists view to call this endpoint when a "pin" button is clicked, updating the UI dynamically.

5.  **Verification (MCP Checkpoint):**
    *   Add a YouTube channel ID (e.g., CppCon's).
    *   The app should fetch and display the channel's playlists.
    *   You should be able to pin and unpin a playlist, and the state should persist in the database.

---

## Phase 3: The Async Sync Engine — MVP

**Goal:** Ingest video metadata from pinned playlists into the local database.

1.  **Video Model and Schema:**
    *   Define the `Video` model in `models.py` (id, title, description, etc.).
    *   Create `Video` Pydantic schemas.
    *   Update Alembic with the new table: `alembic revision --autogenerate -m "Add videos table"` and `alembic upgrade head`.

2.  **Async Sync Logic:**
    *   In `youtube.py`, create `get_videos_for_playlist(playlist_id)`. This will:
        1.  Use `playlistItems.list` to get all video IDs in the playlist.
        2.  Batch requests to `videos.list` (50 IDs at a time) to get video metadata.
    *   Use `isodate` to parse the duration and store it as `duration_seconds`.

3.  **Background Task Integration:**
    *   Create an endpoint `POST /sync/run`.
    *   This endpoint will get all `pinned` playlists and trigger a `BackgroundTasks` instance for each one.
    *   The background task will call the sync logic from `youtube.py` and store the results in the `videos` table.

4.  **UI for Syncing:**
    *   Add a "Sync Pinned Playlists" button to the main interface.
    *   Provide feedback to the user that the sync has started.

5.  **Verification (MCP Checkpoint):**
    *   Pin a playlist with a few videos.
    *   Trigger the sync.
    *   Verify that the `videos` table in `indexer.db` is populated with the correct metadata.

---

## Phase 4: Search & Curation — MVP

**Goal:** Implement full-text search and allow users to manage the curation status of videos.

1.  **Enable FTS5:**
    *   FTS5 is a compile-time option for SQLite. Ensure your Python's SQLite has it.
    *   Create an FTS5 virtual table for `videos`. This can be done with custom Alembic migration scripts.

2.  **Search API and UI:**
    *   Implement a search function in `crud.py` that queries the FTS5 table.
    *   Create a search endpoint `/search?q=...` in `main.py`.
    *   Add a search bar to the UI that uses HTMX to send requests to the search endpoint and display results dynamically.

3.  **Curation State Management:**
    *   Add `video_state` and `tags`/`video_tags` tables to `models.py`. Generate and apply the migration.
    *   Create endpoints to update a video's status (e.g., `POST /videos/{video_id}/status`) and add tags.
    *   In the search results, display the current status and tags for each video.
    *   Add UI elements (buttons, dropdowns) to change the status of a video.

4.  **Filtering:**
    *   Enhance the search endpoint to accept filter parameters (playlist, duration, etc.).
    *   Add filter controls to the search UI.

5.  **Verification (MCP Checkpoint):**
    *   Search for a keyword present in a synced video's title or description.
    *   The video should appear in the results.
    *   Change the status of a video to "watched" and verify it persists.
    *   Add a tag to a video and verify it is saved and displayed.

---

## Phase 5: Export — MVP

**Goal:** Allow users to export curated lists in Markdown and CSV formats.

1.  **Export Logic:**
    *   Create an `export.py` service.
    *   Implement `generate_markdown_export(videos)` which formats a list of videos into a clean Markdown file.
    *   Implement `generate_csv_export(videos)` which does the same for CSV.

2.  **Export Endpoints:**
    *   Create `/export/markdown` and `/export/csv` endpoints.
    *   These endpoints will fetch the relevant videos (e.g., all videos with status "queued") and return a file response.

3.  **UI for Exporting:**
    *   Add "Export as Markdown" and "Export as CSV" buttons to the UI.

4.  **Verification (MCP Checkpoint):**
    *   Queue a few videos for watching.
    *   Click the export button.
    *   A Markdown or CSV file should be downloaded with the correct content.

---

## Phase 6: Optimization — Post-MVP

**Goal:** Improve the efficiency and usability of the application.

1.  **Incremental Refresh:**
    *   Modify the sync logic to first check for existing video IDs in the database for a given playlist.
    *   Only fetch metadata for new video IDs.

2.  **Bulk Actions:**
    *   Use Alpine.js to add "select all" functionality to the video list.
    *   Create an endpoint that accepts a list of video IDs to update their status in bulk.

3.  **Observability:**
    *   Add a `sync_runs` table to log the start time, end time, status, and number of new videos for each sync.
    *   Display this information on a status page.
