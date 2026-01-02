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

sync_error_message = None


# Dependency
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    db_state = database.get_db_state()
    api_key_valid = youtube.has_valid_key()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "db_state": db_state,
            "sync_error_message": sync_error_message,
            "api_key_valid": api_key_valid,
        },
    )


@app.get("/sources", response_class=HTMLResponse)
async def read_sources(request: Request, db: Session = Depends(get_db)):
    sources = crud.get_sources(db)
    return templates.TemplateResponse(request, "sources.html", {"request": request, "sources": sources})


@app.post("/sources", response_class=RedirectResponse)
async def create_source_from_form(
    db: Session = Depends(get_db),
    name: str = Form(...),
    type: str = Form(...),
    external_id: str = Form(...)
):
    source = schemas.SourceCreate(name=name, type=type, external_id=external_id)
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
            return HTMLResponse(
                f'<div class="p-3 rounded bg-red-100 text-red-800">Error discovering playlists: {exc}</div>',
                status_code=500,
            )

    db.refresh(source)
    return templates.TemplateResponse(
        request, "playlist-list.html", {"request": request, "playlists": source.playlists}
    )


@app.post("/playlists/{playlist_id}/pin", response_class=HTMLResponse)
async def toggle_pin_playlist(
    playlist_id: int, request: Request, db: Session = Depends(get_db)
):
    playlist = crud.toggle_playlist_pinned(db, playlist_id=playlist_id)
    return templates.TemplateResponse(
        request, "playlist-item.html", {"request": request, "playlist": playlist}
    )


def _sync_playlist_videos(playlist_id: int):
    """Background job to sync a single playlist."""
    db = database.SessionLocal()
    try:
        global sync_error_message
        playlist = crud.get_playlist(db, playlist_id=playlist_id)
        if not playlist:
            return

        videos_data = youtube.get_videos_for_playlist(playlist.external_id)
        new_count = 0
        for item in videos_data:
            video_id = item["id"]
            existing_video = crud.get_video_by_external_id(db, external_id=video_id)
            if existing_video:
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
        playlist.last_synced_at = datetime.datetime.utcnow()
        db.commit()
        logging.info("Synced %s new videos for playlist %s", new_count, playlist.external_id)
    except Exception:
        logging.exception("Sync failed for playlist_id=%s", playlist_id)
        sync_error_message = "Sync failed; check API key/network. See logs for details."
    finally:
        db.close()


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
    state = schemas.VideoStateCreate(status=status, notes=notes, score=score)
    crud.update_video_state(db, video_id=video_id, state=state)
    video = crud.get_video(db, video_id=video_id)
    return templates.TemplateResponse(
        request, "video-item.html", {"request": request, "video": video}
    )


@app.post("/videos/{video_id}/tags", response_class=HTMLResponse)
async def add_video_tag(
    video_id: int,
    request: Request,
    tag: str = Form(...),
    db: Session = Depends(get_db),
):
    video = crud.add_tag_to_video(db, video_id=video_id, tag_name=tag.strip())
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return templates.TemplateResponse(
        request, "video-item.html", {"request": request, "video": video}
    )


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
    return _export_videos_content(db, fmt="markdown", status=status)


@app.get("/export/csv")
async def export_csv(status: Optional[str] = None, db: Session = Depends(get_db)):
    return _export_videos_content(db, fmt="csv", status=status)


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
    video = crud.remove_tag_from_video(db, video_id=video_id, tag_name=tag.strip())
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return templates.TemplateResponse(
        request, "video-item.html", {"request": request, "video": video}
    )


@app.get("/api-key", response_class=HTMLResponse)
async def api_key_form(request: Request):
    return templates.TemplateResponse(
        request,
        "api-key.html",
        {"request": request, "api_key_valid": youtube.has_valid_key()},
    )


@app.post("/api-key", response_class=RedirectResponse)
async def set_api_key(key: str = Form(...)):
    youtube.set_api_key(key.strip())
    return RedirectResponse(url="/", status_code=303)


@app.get("/search", response_class=HTMLResponse)
async def search_videos_page(
    request: Request, q: Optional[str] = None, db: Session = Depends(get_db)
):
    videos = crud.search_videos(db, query=q)
    if "hx-request" in request.headers:
        return templates.TemplateResponse(
            request, "video-list.html", {"request": request, "videos": videos}
        )
    return templates.TemplateResponse(
        request, "search.html", {"request": request, "videos": videos}
    )
