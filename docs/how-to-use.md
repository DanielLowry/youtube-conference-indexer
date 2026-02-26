# YouTube Conference Indexer — How to Use

See also: `docs/architecture-decisions.md` for design rationale and tradeoffs.

## Prereqs
- Python 3.11+
- `uv` installed (used for env + deps)
- YouTube Data API v3 key

## Setup
```bash
uv venv
uv pip install -r requirements.txt
```
You can start the app without an API key—the UI will show a warning and let you paste one on the **API Key** page. To set it upfront, create `.env` in the repo root (defaults to SQLite at `data/indexer.db`):
```
YOUTUBE_API_KEY=your_api_key_here
DATABASE_URL=sqlite:///./data/indexer.db
```
The SQLite file and tables are created automatically on first run. If you don’t want persistence, you can skip setting `DATABASE_URL` and run in in-memory mode (see “DB-free mode” below).

## Run the app
```bash
uv run uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000

## Workflow
1) **Add sources**: Go to `/sources`, add a Channel ID/handle/URL or Playlist ID. Channels auto-discover their playlists immediately—no extra click.
2) **Pin**: Pin playlists you care about. Pinning does two things:
   - Priority: pinned playlists are synced first, but all playlists are synced automatically in the background.
   - Export scope: only pinned playlists are included in Markdown/CSV exports.
3) **Auto-sync**: The app auto-queues all playlists on page load and every ~30 minutes (throttled). Progress bars appear per playlist; queued/fetching playlists poll automatically.
4) **Search**: Visit `/search` and type to search titles/descriptions (FTS).
5) **Curation**: In search results, update status/notes/score; add/remove tags inline.
6) **Export**: From the home page, download Markdown or CSV (optionally filtered by status via query string, e.g., `?status=queued`). Exports use pinned playlists.

## Testing
```bash
uv run pytest
```
CI mirrors this on GitHub Actions (Linux). Tests stub YouTube calls; no network needed.

## Notes
- If using a custom DB location, set `DATABASE_URL` accordingly. For SQLite, the file is created automatically.
- Alembic is configured; current schema is up to date with the code. If you change models, add a migration before deployment.
- DB options:
  - SQLite (default): persistent file at `data/indexer.db` (or your `DATABASE_URL`). No extra setup; it’s created automatically.
  - DB-free mode: If the configured DB is unavailable, the app falls back to in-memory (you’ll see a red warning on the home page). You can also switch to in-memory or retry the configured DB via the buttons on the home page. In-memory mode is ephemeral—nothing persists across restarts.
