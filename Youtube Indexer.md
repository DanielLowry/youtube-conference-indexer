---
type: project
status: planned
topics:
  - coding
  - webapp
  - python
  - fastapi
  - sqlite
  - youtube-api
  - data-ingestion
  - curation
  - "[[Web Development]]"
next:
  - Initialize repository with Alembic and FastAPI skeleton
  - Create Google Cloud project and enable YouTube Data API v3
hub: "[[Coding Hub]]"
linked projects: "[[HFT Learning Acceleration Tooling]]"
---

# YouTube Conference Indexer — Comprehensive Project Plan

## 0) Project Vision
**One-sentence summary:** A local web app for discovering conference playlists, pinning relevant ones, ingesting video metadata, and providing a searchable, curated export workflow.

This tool serves as a critical component of the **[[HFT Plan Overview]]**, specifically for generating and managing a high-quality inventory of C++ conference content to accelerate learning.

---

## 1) Problem Statement
YouTube’s native UI is excellent for casual browsing but fails for professional curation because:
* It is difficult to build a **complete inventory** across multiple distinct conference channels.
* It lacks tools for exporting **structured metadata** (descriptions, durations, publish dates) in bulk.
* It does not support a strict **curation workflow** (pin → ingest → score/tag → queue).
* It is hard to manage long-term watch plans (1–2 years) within the platform.

---

## 2) Tech Stack (Simple + Durable)

### Backend
* **Python 3.12+**.
* **FastAPI:** Core framework for API and server-rendered templates.
* **FastAPI BackgroundTasks:** Used to handle long-running YouTube API syncs without timing out the browser.
* **SQLite + FTS5:** Local storage with built-in full-text search.
* **Alembic:** Database migration tool to evolve the schema without losing curated data.
* **isodate:** Library for parsing YouTube’s ISO 8601 duration strings into searchable integers (seconds).

### Frontend
* **Tailwind CSS:** For rapid, responsive styling.
* **HTMX:** For server-side HTML updates and interactivity.
* **Alpine.js:** For client-side state (e.g., "Select All" checkboxes and UI toggles).

---

## 3) Implementation Roadmap

### Phase 1: Foundation (Milestone 0) — **MVP**
* Initialize repository using `uv` or `poetry`.
* Set up FastAPI skeleton and Alembic migration environment.
* Establish SQLite connection and create initial base templates.
* **Done when:** The app boots, `/sources` page loads, and the DB file is created.

### Phase 2: Source Discovery & Pinning — **MVP**
* **Sources CRUD:** Add/List/Delete YouTube Channel or Playlist IDs.
* **Discovery Logic:** Fetch a channel's playlists via `playlists.list`.
* **Pinning System:** Toggle playlists as "In-Scope" for the indexer.
* **Done when:** You can add "CppCon" and pin a specific "2024" playlist.

### Phase 3: The Async Sync Engine — **MVP**
* **Background Tasks:** Trigger ingestion via `BackgroundTasks` to avoid HTTP timeouts.
* **Ingestion Logic:**
  1. `playlistItems.list` to page through video IDs.
  2. `videos.list` to fetch metadata in batches of 50 IDs.
* **Data Normalization:** Convert ISO durations to seconds and store video metadata.
* **Done when:** Searching for a video title returns a result after a sync run.

### Phase 4: Search & Curation — **MVP**
* **Local Search:** Implement FTS5 keyword search over titles and descriptions.
* **Filtering:** Add UI filters for source, playlist, year, and duration.
* **Status Management:** Implement curation states (queued, watching, done, skipped).
* **Tagging:** Implement a many-to-many relationship for custom tags.
* **Done when:** Searching "allocator" returns matches instantly with status badges.

### Phase 5: Export — **MVP**
* **Markdown Export:** Generate Obsidian-friendly watchlists with metadata and status.
* **CSV Export:** Generate flat files for external data analysis.
* **Done when:** You can copy a watchlist into Obsidian and start tracking progress.

### Phase 6: Optimization — **Post-MVP**
* **Incremental Refresh:** Sync only new videos for pinned playlists by detecting existing IDs.
* **Bulk Actions:** Use Alpine.js to update the status of multiple videos at once.
* **Observability:** Store a `sync_runs` table to track errors and new video counts.

---

## 4) YouTube API Quota Strategy
* **Default Allocation:** 10,000 units/day (free).
* **Deterministic Listing:** Use `playlistItems.list` (1 unit) + `videos.list` (1 unit/50 videos).
* **Avoid `search.list`:** This endpoint costs 100 units per request and should be avoided.
* **Caching:** Never re-fetch metadata for a video ID that already exists in SQLite.

---

## 5) Database Schema (SQLite)



### Core Tables
* **`sources`**: `id`, `type` (channel/playlist), `external_id`, `name`.
* **`playlists`**: `id`, `source_id`, `title`, `description`, `pinned` (bool), `last_synced_at`.
* **`videos`**: `id`, `title`, `description`, `published_at`, `duration_seconds` (int), `channel_title`.
* **`tags` & `video_tags`**: Many-to-many relationship for taxonomies.
* **`video_state`**: `video_id`, `status` (queued/done/skipped), `notes`, `score`.

---

## 6) Acceptance Criteria (MVP)
The project is complete when you can:
1. Add a channel source (e.g., CppCon).
2. Discover and pin specific playlists.
3. Sync pinned content into the local DB in the background.
4. Search by keyword locally with high performance.
5. Export a Markdown watchlist for your knowledge base.