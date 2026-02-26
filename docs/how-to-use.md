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

## Run the web UI
```bash
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

### UI workflow
1. Set or validate your API key on `/api-key`.
2. On `/`, submit a run in one mode:
   - `search` (query + optional filters)
   - `playlist` (playlist ID)
   - `channel` (channel ID)
3. Monitor run status cards (auto-refresh every few seconds).
4. Download `videos.jsonl` and/or `videos.csv` from the run card.

## Run from CLI
The CLI uses the same service contracts as the web adapter.

### Start a run
```bash
uv run python -m app.cli run --mode search --query "cppcon allocator" --max-pages 10
```

Examples:
```bash
uv run python -m app.cli run --mode playlist --playlist-id PL123 --output-format jsonl --output-format csv
uv run python -m app.cli run --mode channel --channel-id UC123 --max-pages 20
```

### Resume a run
```bash
uv run python -m app.cli resume <run_id>
```

## Output structure
Each run writes to `./runs/<run_id>/`:
- `videos.jsonl` (if requested)
- `videos.csv` (if requested)
- `run_state.json` (full checkpoint + dedupe state)
- `summary.json` (compact progress/status)

## Testing
Run all tests:
```bash
uv run pytest
```

Focused stateless suites:
```bash
uv run pytest tests/test_extraction_contracts.py tests/test_stateless_core.py tests/test_stateless_routes.py tests/test_cli.py
```
