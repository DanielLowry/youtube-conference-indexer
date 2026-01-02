from sqlalchemy.orm import Session
from sqlalchemy import text, or_

from . import models, schemas


def search_videos(db: Session, query: str):
    if not query:
        return db.query(models.Video).all()

    # Wrap query in quotes to avoid FTS operator parsing (e.g., "+" or "-" characters)
    safe_query = query.strip().replace('"', '""')
    if not safe_query:
        return db.query(models.Video).all()
    fts_param = f'"{safe_query}"'

    # We need to find the rowids from the FTS table first
    fts_query = text("SELECT rowid FROM videos_fts WHERE videos_fts MATCH :query")
    try:
        result = db.execute(fts_query, {"query": fts_param})
        video_ids = [row[0] for row in result]
    except Exception:
        # Fallback to a simple LIKE search if FTS parsing fails
        like = f"%{query}%"
        return (
            db.query(models.Video)
            .filter(
                or_(
                    models.Video.title.ilike(like),
                    models.Video.description.ilike(like),
                )
            )
            .all()
        )

    if not video_ids:
        return []

    return db.query(models.Video).filter(models.Video.id.in_(video_ids)).all()


def get_source(db: Session, source_id: int):
    return db.query(models.Source).filter(models.Source.id == source_id).first()


def get_source_by_external_id(db: Session, external_id: str):
    return db.query(models.Source).filter(models.Source.external_id == external_id).first()


def get_sources(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Source).offset(skip).limit(limit).all()


def create_source(db: Session, source: schemas.SourceCreate):
    db_source = models.Source(
        type=source.type,
        external_id=source.external_id,
        name=source.name
    )
    db.add(db_source)
    db.commit()
    db.refresh(db_source)
    return db_source

def delete_source(db: Session, source_id: int):
    db_source = db.query(models.Source).filter(models.Source.id == source_id).first()
    if db_source:
        db.delete(db_source)
        db.commit()
    return db_source

def get_video(db: Session, video_id: int):
    return db.query(models.Video).filter(models.Video.id == video_id).first()

def update_video_state(db: Session, video_id: int, state: schemas.VideoStateCreate):
    db_state = db.query(models.VideoState).filter(models.VideoState.video_id == video_id).first()
    if db_state:
        db_state.status = state.status
        db_state.notes = state.notes
        db_state.score = state.score
        db.commit()
        db.refresh(db_state)
    return db_state

def get_pinned_playlists(db: Session):
    return db.query(models.Playlist).filter(models.Playlist.pinned == True).all()

def get_video_by_external_id(db: Session, external_id: str):
    return db.query(models.Video).filter(models.Video.external_id == external_id).first()

def create_video(db: Session, video: schemas.VideoCreate, playlist_id: int):
    db_video = models.Video(
        **video.model_dump(),
        playlist_id=playlist_id
    )
    db.add(db_video)
    db.commit()
    db.refresh(db_video)
    # Also create an initial state for the video
    state = models.VideoState(video_id=db_video.id)
    db.add(state)
    db.commit()
    db.refresh(db_video)
    return db_video

def get_playlist_by_external_id(db: Session, external_id: str):
    return db.query(models.Playlist).filter(models.Playlist.external_id == external_id).first()

def get_playlist(db: Session, playlist_id: int):
    return db.query(models.Playlist).filter(models.Playlist.id == playlist_id).first()

def create_playlist(db: Session, playlist: schemas.PlaylistCreate, source_id: int):
    db_playlist = models.Playlist(**playlist.model_dump(), source_id=source_id)
    db.add(db_playlist)
    db.commit()
    db.refresh(db_playlist)
    return db_playlist

def toggle_playlist_pinned(db: Session, playlist_id: int):
    db_playlist = get_playlist(db, playlist_id)
    if db_playlist:
        db_playlist.pinned = not db_playlist.pinned
        db.commit()
        db.refresh(db_playlist)
    return db_playlist


def set_all_playlists_pinned(db: Session, source_id: int, pinned: bool):
    db.query(models.Playlist).filter(models.Playlist.source_id == source_id).update(
        {"pinned": pinned}, synchronize_session=False
    )
    db.commit()


def get_videos(db: Session, status: str | None = None):
    query = db.query(models.Video)
    if status:
        query = query.join(models.VideoState).filter(models.VideoState.status == status)
    return query.all()


def get_or_create_tag(db: Session, name: str):
    tag = db.query(models.Tag).filter(models.Tag.name == name).first()
    if tag:
        return tag
    tag = models.Tag(name=name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def add_tag_to_video(db: Session, video_id: int, tag_name: str):
    video = get_video(db, video_id)
    if not video:
        return None
    tag = get_or_create_tag(db, tag_name)
    if tag not in video.tags:
        video.tags.append(tag)
        db.commit()
        db.refresh(video)
    return video


def remove_tag_from_video(db: Session, video_id: int, tag_name: str):
    video = get_video(db, video_id)
    if not video:
        return None
    tag = db.query(models.Tag).filter(models.Tag.name == tag_name).first()
    if tag and tag in video.tags:
        video.tags.remove(tag)
        db.commit()
        db.refresh(video)
    return video
