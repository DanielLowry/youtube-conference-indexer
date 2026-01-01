from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import datetime
from typing import Optional

from . import crud, models, schemas, youtube
from .database import SessionLocal, engine

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

templates = Jinja2Templates(directory="templates")


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/sources", response_class=HTMLResponse)
async def read_sources(request: Request, db: Session = Depends(get_db)):
    sources = crud.get_sources(db)
    return templates.TemplateResponse("sources.html", {"request": request, "sources": sources})


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

    db.refresh(source)
    return templates.TemplateResponse(
        "playlist-list.html", {"request": request, "playlists": source.playlists}
    )


@app.post("/playlists/{playlist_id}/pin", response_class=HTMLResponse)
async def toggle_pin_playlist(
    playlist_id: int, request: Request, db: Session = Depends(get_db)
):
    playlist = crud.toggle_playlist_pinned(db, playlist_id=playlist_id)
    return templates.TemplateResponse(
        "playlist-item.html", {"request": request, "playlist": playlist}
    )


@app.post("/sync/run", response_class=HTMLResponse)
async def run_sync(request: Request, db: Session = Depends(get_db)):
    pinned_playlists = crud.get_pinned_playlists(db)
    total_videos_synced = 0
    for playlist in pinned_playlists:
        videos_data = youtube.get_videos_for_playlist(playlist.external_id)
        for item in videos_data:
            video_id = item["id"]
            existing_video = crud.get_video_by_external_id(db, external_id=video_id)
            if not existing_video:
                video = schemas.VideoCreate(
                    external_id=video_id,
                    title=item["snippet"]["title"],
                    description=item["snippet"]["description"],
                    published_at=datetime.datetime.fromisoformat(item["snippet"]["publishedAt"].replace("Z", "+00:00")),
                    duration_seconds=item["contentDetails"]["duration_seconds"],
                    channel_title=item["snippet"]["channelTitle"],
                )
                crud.create_video(db, video=video, playlist_id=playlist.id)
                total_videos_synced += 1
        playlist.last_synced_at = datetime.datetime.utcnow()
        db.commit()

    return HTMLResponse(f"""
    <div id="sync-status" class="text-green-500">
        Sync complete. Synced {total_videos_synced} new videos.
    </div>
    """)


@app.get("/search", response_class=HTMLResponse)
async def search_videos_page(
    request: Request, q: Optional[str] = None, db: Session = Depends(get_db)
):
    videos = crud.search_videos(db, query=q)
    if "hx-request" in request.headers:
        return templates.TemplateResponse(
            "video-list.html", {"request": request, "videos": videos}
        )
    return templates.TemplateResponse(
        "search.html", {"request": request, "videos": videos}
    )
