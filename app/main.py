"""Stateless FastAPI UI adapters for extraction services.

Purpose:
- Preserve a lightweight browser UI while removing runtime DB dependencies.
- Expose extraction service APIs (`run_extraction` / `resume_extraction`) via
  HTTP routes and background tasks.
- Provide run listing, progress polling, and output download endpoints.

Implementation details:
- This module intentionally contains adapter logic only (form parsing, templates,
  HTTP responses). Business logic lives in `app.services.extractors`.
- Run artifacts are stored under `./runs/<run_id>/` by default.
- Progress/status data is read from `summary.json` and `run_state.json` files.
"""

import datetime
import json
import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import youtube, state
from .services.contracts import ExtractionMode, OutputFormat, RunConfig
from .services.extractors import resume_extraction
from .services.run_state import RunStateStore, build_run_id


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates")
OUTPUT_ROOT = "./runs"
DOWNLOAD_MIME_TYPES = {
    "jsonl": "application/x-ndjson",
    "csv": "text/csv",
    "md": "text/markdown",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Validate configured API key on startup for immediate UI feedback."""
    key = youtube.get_api_key()
    if key and "your_api_key_here" not in key:
        ok, message = youtube.validate_api_key()
        state.api_key_status_message = message
        state.api_key_validation_ok = ok
        if not ok:
            logger.warning("API key validation failed on startup: %s", message)
    yield


app = FastAPI(lifespan=lifespan)


def _api_key_context() -> dict[str, Any]:
    """Build API-key-specific UI context flags and status text."""
    key = youtube.get_api_key()
    key_present = bool(key) and "your_api_key_here" not in key
    return {
        "api_key_valid": youtube.has_valid_key() if key_present else False,
        "api_key_status_message": state.api_key_status_message,
        "api_key_validation_ok": state.api_key_validation_ok,
    }


def _parse_optional_datetime(value: str | None) -> datetime.datetime | None:
    """Parse optional datetime form values and normalize to UTC."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    parsed = datetime.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def _parse_output_formats(values: list[str] | None) -> list[OutputFormat]:
    """Parse output format form values with safe defaults and dedupe."""
    if not values:
        return [OutputFormat.JSONL, OutputFormat.CSV]
    formats: list[OutputFormat] = []
    seen: set[str] = set()
    for value in values:
        try:
            fmt = OutputFormat(value)
        except ValueError:
            continue
        if fmt.value in seen:
            continue
        seen.add(fmt.value)
        formats.append(fmt)
    return formats or [OutputFormat.JSONL, OutputFormat.CSV]


def _resolve_output_root(output_root: str | None = None) -> str:
    """Resolve output root with runtime default fallback.

    Using a helper avoids default-argument capture so tests can monkeypatch
    `OUTPUT_ROOT` after import and still affect route behavior.
    """
    return output_root or OUTPUT_ROOT


def _load_run_snapshot(run_id: str, output_root: str | None = None) -> dict[str, Any] | None:
    """Load one run summary for UI rendering.

    The function prefers `summary.json` for fast reads and falls back to
    `run_state.json` when needed.
    """
    resolved_root = _resolve_output_root(output_root)
    store = RunStateStore(output_root=resolved_root)
    run_dir = store.run_dir(run_id)
    if not run_dir.exists():
        return None

    summary_path = run_dir / "summary.json"
    state_path = run_dir / "run_state.json"
    payload: dict[str, Any] | None = None

    if summary_path.exists():
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    elif state_path.exists():
        state_payload = json.loads(state_path.read_text(encoding="utf-8"))
        result_payload = state_payload.get("result", {})
        payload = {
            "run_id": result_payload.get("run_id"),
            "mode": result_payload.get("mode"),
            "status": result_payload.get("status"),
            "started_at": result_payload.get("started_at"),
            "finished_at": result_payload.get("finished_at"),
            "output_dir": result_payload.get("output_dir"),
            "output_files": result_payload.get("output_files") or [],
            "progress": result_payload.get("progress") or {},
            "error_message": result_payload.get("error_message"),
        }
    if not payload:
        return None
    return _normalize_run_payload(payload)


def _normalize_run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize run summary payload for template safety."""
    progress = payload.get("progress") or {}
    output_dir = payload.get("output_dir") or ""
    run = {
        "run_id": payload.get("run_id", ""),
        "mode": str(payload.get("mode", "")),
        "status": str(payload.get("status", "queued")),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "output_dir": output_dir,
        "output_files": payload.get("output_files") or [],
        "error_message": payload.get("error_message"),
        "progress": {
            "pages_processed": progress.get("pages_processed", 0),
            "results_seen": progress.get("results_seen", 0),
            "new_video_ids": progress.get("new_video_ids", 0),
            "existing_video_ids": progress.get("existing_video_ids", 0),
            "videos_fetched": progress.get("videos_fetched", 0),
            "quota_estimate": progress.get("quota_estimate", 0),
            "total_playlists": progress.get("total_playlists", 0),
            "processed_playlists": progress.get("processed_playlists", 0),
            "current_playlist_id": progress.get("current_playlist_id"),
        },
    }
    run_dir = Path(output_dir) if output_dir else None
    for ext in ("jsonl", "csv", "md"):
        run[f"has_{ext}"] = bool(run_dir and (run_dir / f"videos.{ext}").exists())
    return run


def _list_runs(output_root: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List run snapshots sorted newest-first by run directory name."""
    resolved_root = _resolve_output_root(output_root)
    root = Path(resolved_root)
    if not root.exists():
        return []
    runs: list[dict[str, Any]] = []
    for run_dir in sorted(root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        snapshot = _load_run_snapshot(run_dir.name, output_root=resolved_root)
        if snapshot:
            runs.append(snapshot)
        if len(runs) >= limit:
            break
    return runs


def _home_context(error_message: str | None = None, selected_run_id: str | None = None) -> dict[str, Any]:
    """Build template context for the main dashboard page."""
    context = _api_key_context()
    context.update(
        {
            "runs": _list_runs(),
            "error_message": error_message,
            "selected_run_id": selected_run_id,
        }
    )
    return context


async def _resume_job_background(run_id: str, output_root: str):
    """Background task wrapper for run resume execution.

    The extraction service is synchronous, so the wrapper runs it in a worker
    thread to keep the FastAPI event loop responsive.
    """
    await asyncio.to_thread(resume_extraction, run_id=run_id, output_root=output_root)


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Render stateless extraction dashboard."""
    context = _home_context(selected_run_id=request.query_params.get("run_id"))
    context["request"] = request
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/runs", response_class=HTMLResponse)
async def list_runs_page(request: Request):
    """Render the same dashboard under `/runs` for route discoverability."""
    context = _home_context()
    context["request"] = request
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/runs/list", response_class=HTMLResponse)
async def list_runs_fragment(request: Request):
    """Return runs list fragment for periodic HTMX polling."""
    return templates.TemplateResponse(
        request,
        "run-list.html",
        {
            "request": request,
            "runs": _list_runs(),
        },
    )


@app.get("/runs/{run_id}/status", response_class=HTMLResponse)
async def run_status_fragment(run_id: str, request: Request):
    """Return one run status card fragment for HTMX row polling."""
    run = _load_run_snapshot(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return templates.TemplateResponse(
        request,
        "run-status.html",
        {
            "request": request,
            "run": run,
        },
    )


@app.post("/runs", response_class=HTMLResponse)
async def submit_run(
    request: Request,
    background_tasks: BackgroundTasks,
    mode: str = Form(...),
    query: str | None = Form(None),
    playlist_id: str | None = Form(None),
    channel_id: str | None = Form(None),
    published_after: str | None = Form(None),
    published_before: str | None = Form(None),
    video_duration: str = Form("any"),
    order_by: str = Form("relevance"),
    region_code: str | None = Form(None),
    relevance_language: str | None = Form(None),
    safe_search: str | None = Form(None),
    max_pages: int = Form(10),
    stop_after_empty_pages: int = Form(2),
    output_formats: list[str] | None = Form(None),
):
    """Create a run config, initialize checkpoint files, and queue background run."""
    try:
        extraction_mode = ExtractionMode(mode)
        config = RunConfig(
            mode=extraction_mode,
            query=(query or "").strip() or None,
            playlist_id=(playlist_id or "").strip() or None,
            channel_id=(channel_id or "").strip() or None,
            published_after=_parse_optional_datetime(published_after),
            published_before=_parse_optional_datetime(published_before),
            video_duration=video_duration,  # validated by contract
            order_by=order_by,  # validated by contract
            region_code=(region_code or "").strip() or None,
            relevance_language=(relevance_language or "").strip() or None,
            safe_search=(safe_search or "").strip() or None,
            max_pages=max_pages,
            stop_after_empty_pages=stop_after_empty_pages,
            output_formats=_parse_output_formats(output_formats),
            output_root=OUTPUT_ROOT,
        )
    except Exception as exc:  # noqa: BLE001
        context = _home_context(error_message=f"Invalid run configuration: {exc}")
        context["request"] = request
        return templates.TemplateResponse(request, "index.html", context, status_code=400)

    run_id = build_run_id(config)
    config = config.model_copy(update={"run_id": run_id})

    store = RunStateStore(output_root=config.output_root)
    store.initialize_run(config)
    background_tasks.add_task(
        _resume_job_background,
        run_id,
        config.output_root,
    )
    return RedirectResponse(url=f"/?run_id={run_id}", status_code=303)


@app.post("/runs/{run_id}/resume", response_class=RedirectResponse)
async def resume_run(run_id: str, background_tasks: BackgroundTasks):
    """Queue a resume operation for an existing run checkpoint."""
    snapshot = _load_run_snapshot(run_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Run not found")
    background_tasks.add_task(_resume_job_background, run_id, OUTPUT_ROOT)
    return RedirectResponse(url=f"/?run_id={run_id}", status_code=303)


@app.get("/runs/{run_id}/download/{output_format}")
async def download_run_artifact(run_id: str, output_format: str):
    """Download one run output file (`videos.<format>`) if present."""
    if output_format not in DOWNLOAD_MIME_TYPES:
        raise HTTPException(status_code=404, detail="Unsupported output format")
    store = RunStateStore(output_root=OUTPUT_ROOT)
    run_dir = store.run_dir(run_id).resolve()
    root_dir = Path(OUTPUT_ROOT).resolve()
    if root_dir not in run_dir.parents and run_dir != root_dir:
        raise HTTPException(status_code=404, detail="Invalid run path")
    path = run_dir / f"videos.{output_format}"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")
    return FileResponse(
        path=path,
        media_type=DOWNLOAD_MIME_TYPES[output_format],
        filename=f"{run_id}.{output_format}",
    )


@app.get("/api-key", response_class=HTMLResponse)
async def api_key_form(request: Request):
    """Render API key settings form."""
    return templates.TemplateResponse(
        request,
        "api-key.html",
        {
            "request": request,
            **_api_key_context(),
        },
    )


@app.post("/api-key", response_class=HTMLResponse)
async def set_api_key(request: Request, key: str = Form(...)):
    """Save API key in-memory and validate with a lightweight probe."""
    youtube.set_api_key(key.strip())
    ok, message = youtube.validate_api_key()
    state.api_key_status_message = message
    state.api_key_validation_ok = ok
    if not ok:
        return templates.TemplateResponse(
            request,
            "api-key.html",
            {
                "request": request,
                "api_key_valid": False,
                "api_key_status_message": message,
                "api_key_validation_ok": ok,
            },
            status_code=400,
        )
    return RedirectResponse(url="/", status_code=303)


@app.get("/search", response_class=RedirectResponse)
async def redirect_search():
    """Keep legacy `/search` links functional by redirecting to dashboard."""
    return RedirectResponse(url="/", status_code=307)


@app.get("/sources", response_class=RedirectResponse)
async def redirect_sources():
    """Keep legacy `/sources` links functional by redirecting to dashboard."""
    return RedirectResponse(url="/", status_code=307)
