import datetime
import logging

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional

from . import crud, models, schemas, youtube, export, database

app = FastAPI()

templates = Jinja2Templates(directory="templates")

# ensure tables exist once models are loaded
database.create_tables()
db_health_ok, db_health_error = database.health_check()

sync_error_message = None
api_key_status_message = None
api_key_validation_ok = None
AUTO_SYNC_INTERVAL_MINUTES = 30
last_auto_sync_at = None
sync_in_progress = False
active_sync_jobs = 0
total_sync_jobs = 0
last_sync_started_at = None
last_sync_completed_at = None
sync_message = ""
sync_steps_done = 0
sync_steps_total = 0


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


def queue_auto_sync(background_tasks: BackgroundTasks):
    """Schedule a sync if enough time has passed and not already running."""
    from datetime import timedelta

    global last_auto_sync_at, sync_in_progress, active_sync_jobs, total_sync_jobs, sync_error_message, last_sync_started_at, sync_message, sync_steps_done, sync_steps_total
    now = datetime.datetime.utcnow()
    if sync_in_progress:
        return
    if last_auto_sync_at and now - last_auto_sync_at < timedelta(minutes=AUTO_SYNC_INTERVAL_MINUTES):
        return

    db = database.SessionLocal()
    try:
        pinned_playlists = crud.get_pinned_playlists(db)
        if not pinned_playlists:
            last_auto_sync_at = now
            last_sync_started_at = now
            last_sync_completed_at = now
            sync_message = "No pinned playlists to sync."
            sync_steps_done = 0
            sync_steps_total = 0
            return
        sync_error_message = None
        sync_in_progress = True
        active_sync_jobs = len(pinned_playlists)
        total_sync_jobs = len(pinned_playlists)
        last_sync_started_at = now
        sync_message = "Sync started."
        sync_steps_done = 0
        sync_steps_total = len(pinned_playlists)
        last_auto_sync_at = now
        for playlist in pinned_playlists:
            background_tasks.add_task(_sync_playlist_videos, playlist.id)
    finally:
        db.close()


def sync_pinned_now():
    """Force a sync of all pinned playlists (used before exports)."""
    global sync_error_message, sync_in_progress, active_sync_jobs, total_sync_jobs, last_auto_sync_at, last_sync_started_at, last_sync_completed_at, sync_message, sync_steps_done, sync_steps_total
    db = database.SessionLocal()
    try:
        pinned_playlists = crud.get_pinned_playlists(db)
        if not pinned_playlists:
            now = datetime.datetime.utcnow()
            last_sync_started_at = now
            last_sync_completed_at = now
            sync_in_progress = False
            active_sync_jobs = 0
            total_sync_jobs = 0
            sync_message = "No pinned playlists to sync."
            sync_steps_done = 0
            sync_steps_total = 0
            return
        sync_error_message = None
        sync_in_progress = True
        active_sync_jobs = len(pinned_playlists)
        total_sync_jobs = len(pinned_playlists)
        last_sync_started_at = datetime.datetime.utcnow()
        sync_message = "Sync started."
        sync_steps_done = 0
        sync_steps_total = len(pinned_playlists)
        for playlist in pinned_playlists:
            _sync_playlist_videos(playlist.id)
        last_auto_sync_at = datetime.datetime.utcnow()
    finally:
        sync_in_progress = False
        active_sync_jobs = 0
        last_sync_completed_at = datetime.datetime.utcnow()
        sync_message = "Sync completed."
        db.close()


def _home_context(db: Session):
    db_state = database.get_db_state()
    api_key_valid = youtube.has_valid_key()
    sources = crud.get_sources(db)
    return {
        "db_state": db_state,
        "sync_error_message": sync_error_message,
        "api_key_valid": api_key_valid,
        "db_health_ok": db_health_ok,
        "db_health_error": db_health_error,
        "api_key_status_message": api_key_status_message,
        "api_key_validation_ok": api_key_validation_ok,
        "AUTO_SYNC_INTERVAL_MINUTES": AUTO_SYNC_INTERVAL_MINUTES,
        "sources": sources,
        "sync_in_progress": sync_in_progress,
        "active_sync_jobs": active_sync_jobs,
        "total_sync_jobs": total_sync_jobs,
        "last_sync_started_at": last_sync_started_at,
        "last_sync_completed_at": last_sync_completed_at,
        "sync_message": sync_message,
        "sync_steps_done": sync_steps_done,
        "sync_steps_total": sync_steps_total,
    }


@app.on_event("startup")
async def validate_initial_api_key():
    """Validate any configured API key once at startup."""
    global api_key_status_message, api_key_validation_ok
    key = youtube.get_api_key()
    if not key or "your_api_key_here" in key:
        return
    ok, message = youtube.validate_api_key()
    api_key_status_message = message
    api_key_validation_ok = ok
    if not ok:
        logging.warning("API key validation failed on startup: %s", message)


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    queue_auto_sync(background_tasks)
    ctx = _home_context(db)
    ctx["request"] = request
    return templates.TemplateResponse(request, "index.html", ctx)


@app.get("/sync/status", response_class=HTMLResponse)
async def sync_status(request: Request):
    percent = 0
    completed = 0
    total_steps = sync_steps_total or total_sync_jobs or 0
    done_steps = sync_steps_done or 0
    if total_steps:
        completed = min(done_steps, total_steps)
        percent = int((completed / total_steps) * 100)
    status_text = ""
    if sync_in_progress:
        if total_steps:
            status_text = f"Sync in progress: {percent}% ({completed}/{total_steps} steps)"
        else:
            status_text = "Sync in progress..."
    elif last_sync_completed_at:
        status_text = f"Last sync completed at {last_sync_completed_at} UTC"
    elif last_sync_started_at:
        status_text = sync_message or "Sync attempted but nothing to do (no pinned playlists)."
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
    queue_auto_sync(background_tasks)
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
        return templates.TemplateResponse("index.html", ctx, status_code=400)


@app.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: int, db: Session = Depends(get_db)):
    crud.delete_source(db=db, source_id=source_id)


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
    return templates.TemplateResponse(
        request, "playlist-list.html", {"request": request, "playlists": source.playlists}
    )


@app.post("/playlists/{playlist_id}/pin", response_class=HTMLResponse)
async def toggle_pin_playlist(
    playlist_id: int, request: Request, db: Session = Depends(get_db)
):
    try:
        playlist = crud.toggle_playlist_pinned(db, playlist_id=playlist_id)
        return templates.TemplateResponse(
            request, "playlist-item.html", {"request": request, "playlist": playlist}
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
        return templates.TemplateResponse(
            request, "playlist-list.html", {"request": request, "playlists": source.playlists}
        )
    except Exception as exc:  # noqa: BLE001
        logging.exception("Bulk pin/unpin failed")
        return _inline_error(f"Could not update pins: {exc}")


def _sync_playlist_videos(playlist_id: int):
    """Background job to sync a single playlist."""
    db = database.SessionLocal()
    try:
        global sync_error_message, active_sync_jobs, sync_in_progress, last_sync_completed_at, sync_message, sync_steps_done, sync_steps_total
        playlist = crud.get_playlist(db, playlist_id=playlist_id)
        if not playlist:
            return

        videos_data = youtube.get_videos_for_playlist(playlist.external_id)
        # include per-video steps for progress
        sync_steps_total += len(videos_data)
        new_count = 0
        for item in videos_data:
            video_id = item["id"]
            existing_video = crud.get_video_by_external_id(db, external_id=video_id)
            if existing_video:
                sync_steps_done += 1
                continue
            video = schemas.VideoCreate(
                external_id=video_id,
                title=item["snippet"]["title"],
                description=item["snippet"].get("description"),
                published_at=datetime.datetime.fromisoformat(
                    item["snippet"]["publishedAt"].replace("Z", "+00:00")
                ),
                duration_seconds=item["contentDetails"]["duration_seconds"],
                channel_title=item["snippet"]["channelTitle"],
            )
            crud.create_video(db, video=video, playlist_id=playlist.id)
            new_count += 1
            sync_steps_done += 1
        playlist.last_synced_at = datetime.datetime.utcnow()
        db.commit()
        logging.info("Synced %s new videos for playlist %s", new_count, playlist.external_id)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Sync failed for playlist_id=%s", playlist_id)
        suggestion_text = ""
        try:
            suggestions = youtube.search_playlists(playlist.external_id)
            if suggestions:
                human = "; ".join(f'{s["title"]} (ID: {s["id"]})' for s in suggestions)
                suggestion_text = f" Possible playlists: {human}"
        except Exception:
            suggestion_text = ""
        sync_error_message = f"Sync failed; check API key/network. Details: {exc}.{suggestion_text}"
        sync_message = sync_error_message
    finally:
        db.close()
        # mark playlist-level step complete
        sync_steps_done += 1
        if active_sync_jobs > 0:
            active_sync_jobs -= 1
            if active_sync_jobs == 0:
                sync_in_progress = False
                last_sync_completed_at = datetime.datetime.utcnow()
                sync_message = "Sync completed."


@app.post("/sync/run", response_class=HTMLResponse)
async def run_sync(background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    global sync_error_message
    sync_error_message = None
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
        background_tasks.add_task(_sync_playlist_videos, playlist.id)

    return HTMLResponse(f"""
    <div id="sync-status" class="text-green-500">
        Sync started for {len(pinned_playlists)} pinned playlist(s). This may take a moment.
    </div>
    """)


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
        sync_pinned_now()
        return _export_videos_content(db, fmt="markdown", status=status)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Export markdown failed")
        return _inline_error(f"Export failed: {exc}", status_code=500)


@app.get("/export/csv")
async def export_csv(status: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        sync_pinned_now()
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
            "api_key_status_message": api_key_status_message,
            "api_key_validation_ok": api_key_validation_ok,
        },
    )


@app.post("/api-key", response_class=HTMLResponse)
async def set_api_key(request: Request, key: str = Form(...)):
    global api_key_status_message, api_key_validation_ok
    youtube.set_api_key(key.strip())
    ok, message = youtube.validate_api_key()
    api_key_status_message = message
    api_key_validation_ok = ok
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
