# YouTube Metadata Extractor - How to Use

See also: `docs/architecture-decisions.md` for design rationale and tradeoffs.

## Prereqs
- Python 3.11+
- `uv` installed
- YouTube Data API v3 key

## Setup
```bash
uv venv
uv pip install -r requirements.txt
```

Create `.env` in repo root:
```dotenv
YOUTUBE_API_KEY=your_api_key_here
```

Optional:
```dotenv
YOUTUBE_API_KEYS_PATH=data/api_keys.json
```

## Run the web UI
```bash
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

## UI workflow (exact routes)
1. Add or validate one or more API keys on `/api-key`.
   - Select which key is primary; the app uses it first and falls back to other configured keys if that key hits quota exhaustion.
2. Open `/` (or `/runs`) and submit a run in one mode:
   - `search` (query + optional filters)
   - `playlist` (playlist ID)
   - `channel` (channel ID)
3. Monitor run cards:
   - list fragment: `/runs/list`
   - per-run status fragment: `/runs/{run_id}/status`
4. Download outputs:
   - `/runs/{run_id}/download/jsonl`
   - `/runs/{run_id}/download/csv`
5. Resume failed/cancelled runs from the run card (POST `/runs/{run_id}/resume`).

## Run from CLI
The CLI uses the same service contracts as the web adapter.

### Start a search run
```bash
uv run python -m app.cli run --mode search --query "cppcon allocator" --max-pages 10
```

### Start a playlist run
```bash
uv run python -m app.cli run --mode playlist --playlist-id PL123 --max-pages 10
```

### Start a channel run
```bash
uv run python -m app.cli run --mode channel --channel-id UC123 --max-pages 20
```

### Search filters example
```bash
uv run python -m app.cli run \
  --mode search \
  --query "allocators" \
  --published-after 2024-01-01T00:00:00+00:00 \
  --published-before 2025-01-01T00:00:00+00:00 \
  --video-duration medium \
  --order-by date \
  --region-code US \
  --relevance-language en \
  --safe-search moderate \
  --max-pages 5 \
  --stop-after-empty-pages 2
```

### Resume a run
```bash
uv run python -m app.cli resume <run_id>
```

## Quota guidance
- Search mode is expensive:
  - each `search.list` page is estimated as `100` quota units
  - each `videos.list` batch call is estimated as `1` unit
- Playlist/channel extraction is cheaper:
  - each `playlistItems.list` page is estimated as `1` unit
  - each `videos.list` batch call is estimated as `1` unit
- Check `summary.json -> progress.quota_estimate` per run.
- The `/api-key` dashboard tracks successful app-estimated usage per stored key and per YouTube quota day.
- The dashboard uses local app accounting, not a live read from the Google quota console.
- Keys from the same Google Cloud project still share the same upstream YouTube quota pool.
- Keep `max_pages` bounded (default `10`, hard cap `50`).

## Output structure
Each run writes to `./runs/<run_id>/`:
- `videos.jsonl` (if requested)
- `videos.csv` (if requested)
- `run_state.json` (full checkpoint + dedupe state)
- `summary.json` (compact progress/status)

`summary.json` includes:
- `status`, `started_at`, `finished_at`, `error_message`
- `progress.pages_processed`, `progress.results_seen`
- `progress.new_video_ids`, `progress.existing_video_ids`
- `progress.videos_fetched`, `progress.quota_estimate`

`run_state.json` includes:
- serialized `config` (mode + filters + limits)
- serialized `result` (status + progress + output paths)
- `seen_ids` used for in-run dedupe and safe resume behavior

## Resume notes
- Resume continues from `run_state.json` checkpoint values.
- Resume is best-effort for search mode; upstream `nextPageToken` values can expire.
- If token resume fails, rerun safely with dedupe enabled (default) to avoid duplicates.

## Testing
Run all tests:
```bash
uv run pytest
```

Focused stateless suites:
```bash
uv run pytest tests/test_extraction_contracts.py tests/test_stateless_core.py tests/test_stateless_routes.py tests/test_cli.py
```
