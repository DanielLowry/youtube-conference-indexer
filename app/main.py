import datetime
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import crud, models, schemas, youtube, export, database, state
from .services import sync as sync_service

# Ensure our own log lines appear alongside uvicorn's
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Validate any configured API key once at startup (modern lifespan API)."""
    key = youtube.get_api_key()
    if key and "your_api_key_here" not in key:
        ok, message = youtube.validate_api_key()
        state.api_key_status_message = message
        state.api_key_validation_ok = ok
        if not ok:
            logging.warning("API key validation failed on startup: %s", message)
    yield


app = FastAPI(lifespan=lifespan)

templates = Jinja2Templates(directory="templates")

# ensure tables exist once models are loaded
database.create_tables()
state.db_health_ok, state.db_health_error = database.health_check()

# Dependency
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _inline_error(message: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f'<div class="p-3 rounded bg-red-100 text-red-800 border border-red-300">{message}</div>',
        status_code=status_code,
    )


def _page_error(request: Request, message: str, status_code: int = 500) -> HTMLResponse:
    content = _inline_error(message, status_code=status_code).body.decode()
    return templates.TemplateResponse(
        request,
        "base.html",
        {"request": request, "content": content},
        status_code=status_code,
    )


def _home_context(db: Session):
    db_state = database.get_db_state()
    key = youtube.get_api_key()
    key_present = bool(key) and "your_api_key_here" not in key
    api_key_valid = youtube.has_valid_key() if key_present else False
    sources = crud.get_sources(db)
    playlist_status = {}
    for source in sources:
        for pl in source.playlists:
            playlist_status[pl.id] = state.get_playlist_status(pl.id)
    return {
        "db_state": db_state,
        "sync_error_message": state.sync_error_message,
        "api_key_valid": api_key_valid,
        "db_health_ok": state.db_health_ok,
        "db_health_error": state.db_health_error,
        "api_key_status_message": state.api_key_status_message,
        "api_key_validation_ok": state.api_key_validation_ok,
        "AUTO_SYNC_INTERVAL_MINUTES": state.AUTO_SYNC_INTERVAL_MINUTES,
        "sources": sources,
        "sync_in_progress": state.sync_in_progress,
        "active_sync_jobs": state.active_sync_jobs,
        "total_sync_jobs": state.total_sync_jobs,
        "last_sync_started_at": state.last_sync_started_at,
        "last_sync_completed_at": state.last_sync_completed_at,
        "sync_message": state.sync_message,
        "sync_steps_done": state.sync_steps_done,
        "sync_steps_total": state.sync_steps_total,
        "playlist_status": playlist_status,
    }


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    sync_service.queue_auto_sync(background_tasks)
    ctx = _home_context(db)
    ctx["request"] = request
    return templates.TemplateResponse(request, "index.html", ctx)


@app.get("/sync/status", response_class=HTMLResponse)
async def sync_status(request: Request):
    percent = 0
    completed = 0
    total_steps = state.sync_steps_total or state.total_sync_jobs or 0
    done_steps = state.sync_steps_done or 0
    if total_steps:
        completed = min(done_steps, total_steps)
        percent = int((completed / total_steps) * 100)
    status_text = ""
    if state.sync_in_progress:
        if total_steps:
            status_text = f"Sync in progress: {percent}% ({completed}/{total_steps} steps)"
        else:
            status_text = "Sync in progress..."
    elif state.last_sync_completed_at:
        status_text = f"Last sync completed at {state.last_sync_completed_at} UTC"
    elif state.last_sync_started_at:
        status_text = state.sync_message or "Sync attempted but nothing to do (no pinned playlists)."
    else:
        status_text = "No sync has run yet."
    bar = f"""
    <div class="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
        <div class="bg-green-500 h-3" style="width: {percent}%"></div>
    </div>
    <div class="text-xs text-gray-700 mt-1">{status_text}</div>
    """
    return HTMLResponse(bar)


@app.get("/sources", response_class=HTMLResponse)
async def read_sources(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    sync_service.queue_auto_sync(background_tasks)
    ctx = _home_context(db)
    ctx["request"] = request
    return templates.TemplateResponse(request, "index.html", ctx)


@app.post("/sources", response_class=RedirectResponse)
async def create_source_from_form(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    type: str = Form(...),
    external_id: str = Form(...)
):
    try:
        external_id_input = external_id.strip()
        channel_suggestions = []
        channel_id = external_id_input
        if type == "channel":
            channel_id, search_term = youtube.extract_channel_identifier(external_id_input)
            if not channel_id:
                if not youtube.has_valid_key():
                    sources = crud.get_sources(db)
                    return templates.TemplateResponse(
                        request,
                        "sources.html",
                        {
                            "request": request,
                            "sources": sources,
                            "error_message": "You need a valid YouTube API key to look up channel names. Add one on the API Key page, then retry.",
                        },
                        status_code=400,
                    )
                try:
                    channel_suggestions = youtube.search_channels(search_term or external_id_input)
                except Exception as exc:  # noqa: BLE001
                    logging.exception("Channel lookup failed")
                    channel_suggestions = []
                if not channel_suggestions:
                    sources = crud.get_sources(db)
                    return templates.TemplateResponse(
                        request,
                        "sources.html",
                        {
                            "request": request,
                            "sources": sources,
                            "error_message": f"Could not find a channel for '{external_id_input}'. Try a full channel URL or a different name.",
                        },
                        status_code=400,
                    )
                # Auto-pick if a clear match exists
                normalized_term = (search_term or external_id_input).strip().lstrip("@").lower()
                auto_pick = None
                if len(channel_suggestions) == 1:
                    auto_pick = channel_suggestions[0]
                else:
                    for cand in channel_suggestions:
                        title_norm = (cand.get("title") or "").lower()
                        if normalized_term == title_norm:
                            auto_pick = cand
                            break
                    if not auto_pick:
                        for cand in channel_suggestions:
                            title_norm = (cand.get("title") or "").lower()
                            if normalized_term in title_norm:
                                auto_pick = cand
                                break
                if auto_pick:
                    channel_id = auto_pick["id"]
                    # keep user-provided name; ID becomes the canonical external_id
                else:
                    sources = crud.get_sources(db)
                    return templates.TemplateResponse(
                        request,
                        "sources.html",
                        {
                            "request": request,
                            "sources": sources,
                            "channel_suggestions": channel_suggestions,
                            "suggestions_term": external_id_input,
                            "error_message": f"Select the channel for '{external_id_input}' before adding.",
                        },
                        status_code=200,
                    )

        source = schemas.SourceCreate(name=name, type=type, external_id=channel_id)
        created_source = crud.create_source(db=db, source=source)

        # For playlist-type sources, create a playlist record immediately so it appears in the UI
        if type == "playlist":
            existing = crud.get_playlist_by_external_id(db, external_id=external_id)
            if not existing:
                playlist = schemas.PlaylistCreate(
                    external_id=external_id,
                    title=name,
                    description=None,
                )
                crud.create_playlist(db, playlist=playlist, source_id=created_source.id)
        elif type == "channel":
            # Auto-discover once so playlists render immediately (best-effort; non-blocking)
            if youtube.has_valid_key():
                try:
                    playlists_data = youtube.get_channel_playlists(channel_id)
                    for item in playlists_data:
                        playlist_id = item["id"]
                        existing_playlist = crud.get_playlist_by_external_id(db, external_id=playlist_id)
                        if not existing_playlist:
                            playlist = schemas.PlaylistCreate(
                                external_id=playlist_id,
                                title=item["snippet"]["title"],
                                description=item["snippet"]["description"],
                            )
                            crud.create_playlist(db, playlist=playlist, source_id=created_source.id)
                    state.mark_discover_cache(created_source.id)
                except Exception as exc:  # noqa: BLE001
                    logging.exception("Auto-discover on create failed")
        return RedirectResponse(url="/sources", status_code=303)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Create source failed")
        ctx = _home_context(db)
        ctx.update(
            {
                "request": request,
                "error_message": f"Could not create source: {exc}",
            }
        )
        return templates.TemplateResponse(request, "index.html", ctx, status_code=400)


@app.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: int, db: Session = Depends(get_db)):
    crud.delete_source(db=db, source_id=source_id)


@app.get("/sources/{source_id}/playlists", response_class=HTMLResponse)
async def load_source_playlists(
    source_id: int,
    request: Request,
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    source = crud.get_source(db, source_id=source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    logging.info("Load playlists for source_id=%s refresh=%s", source_id, refresh)
    before_count = len(source.playlists)
    if source.type == "channel":
        needs_discover = refresh or not source.playlists or state.discover_cache_expired(source_id)
        if needs_discover:
            if not youtube.has_valid_key():
                return _inline_error("No valid YouTube API key configured. Set one on the API Key page.")
            try:
                playlists_data = youtube.get_channel_playlists(source.external_id)
                logging.info("Discovered %s playlists for source_id=%s", len(playlists_data), source_id)
                for item in playlists_data:
                    playlist_id = item["id"]
                    existing_playlist = crud.get_playlist_by_external_id(db, external_id=playlist_id)
                    if not existing_playlist:
                        playlist = schemas.PlaylistCreate(
                            external_id=playlist_id,
                            title=item["snippet"]["title"],
                            description=item["snippet"]["description"],
                        )
                        crud.create_playlist(db, playlist=playlist, source_id=source_id)
                state.mark_discover_cache(source_id)
            except Exception as exc:  # noqa: BLE001
                logging.exception("Auto-discover playlists failed")
                return _inline_error(f"Error loading playlists: {exc}")

    db.refresh(source)
    logging.info(
        "Load playlists complete source_id=%s count_before=%s count_after=%s",
        source_id,
        before_count,
        len(source.playlists),
    )
    # Prioritize pinned playlists first
    playlists = sorted(source.playlists, key=lambda pl: (not pl.pinned, (pl.title or "").lower()))
    playlist_status = {pl.id: state.get_playlist_status(pl.id) for pl in playlists}
    return templates.TemplateResponse(
        request,
        "playlist-list.html",
        {"request": request, "playlists": playlists, "playlist_status": playlist_status},
    )


@app.post("/sources/{source_id}/discover", response_class=HTMLResponse)
async def discover_playlists(
    source_id: int, request: Request, db: Session = Depends(get_db)
):
    source = crud.get_source(db, source_id=source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if source.type == "channel":
        if not youtube.has_valid_key():
            return HTMLResponse(
                '<li class="p-3 rounded bg-red-100 text-red-800 border border-red-300">No valid YouTube API key configured. Set one on the API Key page.</li>',
                status_code=200,
            )
        try:
            playlists_data = youtube.get_channel_playlists(source.external_id)
            for item in playlists_data:
                playlist_id = item["id"]
                existing_playlist = crud.get_playlist_by_external_id(db, external_id=playlist_id)
                if not existing_playlist:
                    playlist = schemas.PlaylistCreate(
                        external_id=playlist_id,
                        title=item["snippet"]["title"],
                        description=item["snippet"]["description"],
                    )
                    crud.create_playlist(db, playlist=playlist, source_id=source_id)
        except Exception as exc:  # noqa: BLE001
            logging.exception("Discover playlists failed")
            suggestions = []
            try:
                suggestions = youtube.search_channels(source.external_id)
            except Exception:
                suggestions = []
            suggestion_html = ""
            if suggestions:
                suggestion_items = "".join(
                    f'<li class="ml-4 list-disc"><strong>{item["title"]}</strong> (ID: {item["id"]})</li>'
                    for item in suggestions
                )
                suggestion_html = f"<div class='mt-2 text-sm'>Did you mean one of these channels?<ul class='list-disc list-inside'>{suggestion_items}</ul></div>"
            return HTMLResponse(
                f'<li class="p-3 rounded bg-red-100 text-red-800 border border-red-300">Error discovering playlists: {exc}{suggestion_html}</li>',
                status_code=200,
            )

    db.refresh(source)
    state.mark_discover_cache(source_id)
    playlist_status = {pl.id: state.get_playlist_status(pl.id) for pl in source.playlists}
    return templates.TemplateResponse(
        request,
        "playlist-list.html",
        {"request": request, "playlists": source.playlists, "playlist_status": playlist_status},
    )


@app.post("/playlists/{playlist_id}/pin", response_class=HTMLResponse)
async def toggle_pin_playlist(
    playlist_id: int, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    try:
        playlist = crud.toggle_playlist_pinned(db, playlist_id=playlist_id)
        if playlist.pinned:
            state.set_playlist_status(playlist.id, state="queued", total=0, done=0, message="Queued after pin")
            background_tasks.add_task(sync_service.sync_playlist_videos, playlist.id)
        else:
            state.set_playlist_status(playlist.id, state="cancelled", total=0, done=0, message="Cancelled after unpin")
        playlist_status = {playlist.id: state.get_playlist_status(playlist.id)}
        return templates.TemplateResponse(
            request,
            "playlist-item.html",
            {"request": request, "playlist": playlist, "playlist_status": playlist_status},
        )
    except Exception as exc:  # noqa: BLE001
        logging.exception("Pin/unpin failed")
        return _inline_error(f"Could not update pin: {exc}")


@app.post("/sources/{source_id}/playlists/pin_all", response_class=HTMLResponse)
async def bulk_pin_playlists(
    source_id: int, request: Request, action: str = Form(...), db: Session = Depends(get_db)
):
    try:
        if action not in ("pin", "unpin"):
            raise HTTPException(status_code=400, detail="Invalid action")
        crud.set_all_playlists_pinned(db, source_id=source_id, pinned=(action == "pin"))
        source = crud.get_source(db, source_id=source_id)
        playlist_status = {}
        for pl in source.playlists:
            if action == "pin":
                state.set_playlist_status(pl.id, state="queued", total=0, done=0, message="Queued after pin-all")
                background_tasks.add_task(sync_service.sync_playlist_videos, pl.id)
            else:
                state.set_playlist_status(pl.id, state="cancelled", total=0, done=0, message="Cancelled after unpin-all")
            playlist_status[pl.id] = state.get_playlist_status(pl.id)
        return templates.TemplateResponse(
            request,
            "playlist-list.html",
            {"request": request, "playlists": source.playlists, "playlist_status": playlist_status},
        )
    except Exception as exc:  # noqa: BLE001
        logging.exception("Bulk pin/unpin failed")
        return _inline_error(f"Could not update pins: {exc}")


@app.post("/sync/run", response_class=HTMLResponse)
async def run_sync(background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    state.sync_error_message = None
    pinned_playlists = crud.get_pinned_playlists(db)
    if not pinned_playlists:
        return HTMLResponse(
            """
            <div id="sync-status" class="text-yellow-700 bg-yellow-100 p-2 rounded">
                No pinned playlists to sync.
            </div>
            """,
            status_code=200,
        )
    for playlist in pinned_playlists:
        state.set_playlist_status(playlist.id, state="queued", total=0, done=0, message="Queued via manual sync")
        background_tasks.add_task(sync_service.sync_playlist_videos, playlist.id)

    return HTMLResponse(f"""
    <div id="sync-status" class="text-green-500">
    
        Sync started for {len(pinned_playlists)} pinned playlist(s). This may take a moment.
    </div>
    """)


@app.get("/playlists/{playlist_id}/status", response_class=HTMLResponse)
async def playlist_status_fragment(playlist_id: int, db: Session = Depends(get_db)):
    playlist = crud.get_playlist(db, playlist_id=playlist_id)
    pinned = bool(playlist and playlist.pinned)
    status = state.get_playlist_status(playlist_id)
    state_value = status.get("state", "idle")
    done = status.get("done", 0) or 0
    total = status.get("total", 0) or 0
    percent = 0
    if total:
        percent = int(min(done, total) / total * 100)
    # Only keep polling when queued/fetching; otherwise one-shot
    trigger_attr = ' hx-trigger="every 2s"' if state_value in ("queued", "fetching") else ""
    message = status.get("message") or ""
    started_at = status.get("started_at")
    logging.info(
        "playlist_status_fragment id=%s state=%s done=%s total=%s message=%s started_at=%s",
        playlist_id,
        state_value,
        done,
        total,
        message,
        started_at,
    )
    if not pinned:
        state_value = "not_pinned"
        message = "Pin this playlist to sync."
        trigger_attr = ""
    if state_value == "idle" and state.sync_in_progress:
        state_value = "fetching"
        trigger_attr = ' hx-trigger="every 2s"'
        if not message:
            message = "Sync running..."
    elapsed_text = ""
    if started_at:
        elapsed_seconds = int((datetime.datetime.now(datetime.UTC) - started_at).total_seconds())
        if elapsed_seconds >= 3600:
            elapsed_text = f"{elapsed_seconds // 3600}h {(elapsed_seconds % 3600) // 60}m elapsed"
        elif elapsed_seconds >= 60:
            elapsed_text = f"{elapsed_seconds // 60}m {elapsed_seconds % 60}s elapsed"
        else:
            elapsed_text = f"{elapsed_seconds}s elapsed"

    # If a playlist has been stuck in queued/fetching for too long, mark it as error to stop polling.
    updated_at = status.get("updated_at")
    if state_value in ("queued", "fetching") and updated_at:
        age = (datetime.datetime.now(datetime.UTC) - updated_at).total_seconds()
        if age > 180:
            state.set_playlist_status(
                playlist_id,
                state="error",
                total=total,
                done=done,
                message="Sync timed out. Check API key/network.",
            )
            status = state.get_playlist_status(playlist_id)
            state_value = status.get("state", state_value)
            message = status.get("message", message)
            trigger = "load"

    total_display = total if total else "?"
    indeterminate_bar = total == 0 and state_value in ("queued", "fetching")

    progress_bar = (
        "<div class='bg-gradient-to-r from-blue-500 to-green-500 h-2 animate-pulse w-full'></div>"
        if indeterminate_bar
        else f"<div class='bg-gradient-to-r from-blue-500 to-green-500 h-2 transition-all duration-500' style='width: {percent}%'></div>"
    )

    content = f"""
    <div
        id="playlist-status-{playlist_id}"
        data-state="{state_value}"
        hx-get="/playlists/{playlist_id}/status"{trigger_attr}
        hx-swap="outerHTML"
        hx-on::afterSwap="
            const btn = this.closest('li')?.querySelector('button');
            if (!btn) return;
            const st = this.dataset.state;
            if (st === 'queued' || st === 'fetching') {{
                btn.setAttribute('disabled', 'disabled');
                btn.classList.add('cursor-not-allowed', 'text-gray-300');
            }} else {{
                btn.removeAttribute('disabled');
                btn.classList.remove('cursor-not-allowed', 'text-gray-300');
            }}
        "
        class="text-xs text-gray-700 space-y-1"
    >
        <div class="flex items-center space-x-2">
            <span class="px-2 py-0.5 rounded-full text-white text-[10px] {'bg-blue-600' if state_value in ('queued','fetching') else 'bg-green-600' if state_value == 'ready' else 'bg-red-600' if state_value == 'error' else 'bg-gray-500'}">
                {state_value}
            </span>
            <span class="text-sm">{message}</span>
        </div>
        <div class="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
            {progress_bar}
        </div>
        <div class="text-[11px] text-gray-700 flex items-center space-x-2">
            <span class="font-mono">{done}/{total_display} steps</span>
            {f'<span class="text-gray-500">{elapsed_text}</span>' if elapsed_text else ''}
            {f'<span class="animate-pulse text-blue-700">syncing…</span>' if state_value in ('queued', 'fetching') else ''}
        </div>
    </div>
    """
    return HTMLResponse(content)


@app.post("/videos/{video_id}/status", response_class=HTMLResponse)
async def update_video_status(
    video_id: int,
    request: Request,
    status: str = Form(...),
    notes: Optional[str] = Form(None),
    score: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    ):
    try:
        state = schemas.VideoStateCreate(status=status, notes=notes, score=score)
        crud.update_video_state(db, video_id=video_id, state=state)
        video = crud.get_video(db, video_id=video_id)
        return templates.TemplateResponse(
            request, "video-item.html", {"request": request, "video": video}
        )
    except Exception as exc:  # noqa: BLE001
        logging.exception("Update status failed")
        return _inline_error(f"Could not update status: {exc}")


@app.post("/videos/{video_id}/tags", response_class=HTMLResponse)
async def add_video_tag(
    video_id: int,
    request: Request,
    tag: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        video = crud.add_tag_to_video(db, video_id=video_id, tag_name=tag.strip())
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        return templates.TemplateResponse(
            request, "video-item.html", {"request": request, "video": video}
        )
    except Exception as exc:  # noqa: BLE001
        logging.exception("Add tag failed")
        return _inline_error(f"Could not add tag: {exc}")


def _export_videos_content(db: Session, fmt: str, status: Optional[str]):
    videos = crud.get_videos(db, status=status)
    if fmt == "markdown":
        content = export.generate_markdown_export(videos)
        media_type = "text/markdown"
        filename = "videos.md"
    else:
        content = export.generate_csv_export(videos)
        media_type = "text/csv"
        filename = "videos.csv"
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/markdown")
async def export_markdown(status: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        sync_service.sync_pinned_now()
        return _export_videos_content(db, fmt="markdown", status=status)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Export markdown failed")
        return _inline_error(f"Export failed: {exc}", status_code=500)


@app.get("/export/csv")
async def export_csv(status: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        sync_service.sync_pinned_now()
        return _export_videos_content(db, fmt="csv", status=status)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Export CSV failed")
        return _inline_error(f"Export failed: {exc}", status_code=500)


@app.post("/db/use-memory", response_class=RedirectResponse)
async def use_memory():
    database.switch_to_memory()
    return RedirectResponse(url="/", status_code=303)


@app.post("/db/reconnect", response_class=RedirectResponse)
async def reconnect_db():
    database.switch_to_primary()
    return RedirectResponse(url="/", status_code=303)


@app.delete("/videos/{video_id}/tags", response_class=HTMLResponse)
async def remove_video_tag(
    video_id: int,
    request: Request,
    tag: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        video = crud.remove_tag_from_video(db, video_id=video_id, tag_name=tag.strip())
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        return templates.TemplateResponse(
            request, "video-item.html", {"request": request, "video": video}
        )
    except Exception as exc:  # noqa: BLE001
        logging.exception("Remove tag failed")
        return _inline_error(f"Could not remove tag: {exc}")


@app.get("/api-key", response_class=HTMLResponse)
async def api_key_form(request: Request):
    return templates.TemplateResponse(
        request,
        "api-key.html",
        {
            "request": request,
            "api_key_valid": youtube.has_valid_key(),
            "api_key_status_message": state.api_key_status_message,
            "api_key_validation_ok": state.api_key_validation_ok,
        },
    )


@app.post("/api-key", response_class=HTMLResponse)
async def set_api_key(request: Request, key: str = Form(...)):
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


@app.get("/search", response_class=HTMLResponse)
async def search_videos_page(
    request: Request, q: Optional[str] = None, db: Session = Depends(get_db)
):
    try:
        videos = crud.search_videos(db, query=q)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Search failed")
        error_fragment = f'<div class="p-3 rounded bg-red-100 text-red-800 border border-red-300">Search failed: {exc}</div>'
        if "hx-request" in request.headers:
            return HTMLResponse(error_fragment, status_code=200)
        return HTMLResponse(
            templates.get_template("base.html").render(
                request=request, content=error_fragment
            ),
            status_code=500,
        )
    if "hx-request" in request.headers:
        return templates.TemplateResponse(
            request, "video-list.html", {"request": request, "videos": videos}
        )
    return templates.TemplateResponse(
        request, "search.html", {"request": request, "videos": videos}
    )
