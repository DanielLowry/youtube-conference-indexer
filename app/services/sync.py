import datetime
import logging
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app import crud, schemas, youtube, database
from app import state


def queue_auto_sync(background_tasks: BackgroundTasks):
    """Schedule a sync if enough time has passed and not already running."""
    from datetime import timedelta

    now = datetime.datetime.utcnow()
    if state.sync_in_progress:
        return
    if state.last_auto_sync_at and now - state.last_auto_sync_at < timedelta(minutes=state.AUTO_SYNC_INTERVAL_MINUTES):
        return

    db = database.SessionLocal()
    try:
        pinned_playlists = crud.get_pinned_playlists(db)
        if not pinned_playlists:
            state.last_auto_sync_at = now
            state.last_sync_started_at = now
            state.last_sync_completed_at = now
            state.sync_message = "No pinned playlists to sync."
            state.sync_steps_done = 0
            state.sync_steps_total = 0
            return
        state.sync_error_message = None
        state.sync_in_progress = True
        state.active_sync_jobs = len(pinned_playlists)
        state.total_sync_jobs = len(pinned_playlists)
        state.last_sync_started_at = now
        state.sync_message = "Sync started."
        state.sync_steps_done = 0
        state.sync_steps_total = len(pinned_playlists)
        state.last_auto_sync_at = now
        for playlist in pinned_playlists:
            state.set_playlist_status(playlist.id, state="queued", total=0, done=0, message="Queued")
            background_tasks.add_task(sync_playlist_videos, playlist.id)
    finally:
        db.close()


def sync_pinned_now():
    """Force a sync of all pinned playlists (used before exports)."""
    db = database.SessionLocal()
    try:
        pinned_playlists = crud.get_pinned_playlists(db)
        if not pinned_playlists:
            now = datetime.datetime.utcnow()
            state.last_sync_started_at = now
            state.last_sync_completed_at = now
            state.sync_in_progress = False
            state.active_sync_jobs = 0
            state.total_sync_jobs = 0
            state.sync_message = "No pinned playlists to sync."
            state.sync_steps_done = 0
            state.sync_steps_total = 0
            return
        state.sync_error_message = None
        state.sync_in_progress = True
        state.active_sync_jobs = len(pinned_playlists)
        state.total_sync_jobs = len(pinned_playlists)
        state.last_sync_started_at = datetime.datetime.utcnow()
        state.sync_message = "Sync started."
        state.sync_steps_done = 0
        state.sync_steps_total = len(pinned_playlists)
        for playlist in pinned_playlists:
            state.set_playlist_status(playlist.id, state="queued", total=0, done=0, message="Queued")
            sync_playlist_videos(playlist.id)
        state.last_auto_sync_at = datetime.datetime.utcnow()
    finally:
        state.sync_in_progress = False
        state.active_sync_jobs = 0
        state.last_sync_completed_at = datetime.datetime.utcnow()
        state.sync_message = "Sync completed."
        db.close()


def sync_playlist_videos(playlist_id: int):
    """Background job to sync a single playlist."""
    db = database.SessionLocal()
    try:
        playlist = crud.get_playlist(db, playlist_id=playlist_id)
        if not playlist:
            return
        current_status = state.get_playlist_status(playlist_id)
        if current_status.get("state") == "cancelled":
            return

        videos_data = youtube.get_videos_for_playlist(playlist.external_id)
        state.sync_steps_total += len(videos_data)
        state.set_playlist_status(playlist.id, state="fetching", total=len(videos_data), done=0, message="Fetching videos")
        new_count = 0
        for item in videos_data:
            if playlist_id in state.playlist_cancelled:
                state.set_playlist_status(
                    playlist.id,
                    state="cancelled",
                    total=len(videos_data),
                    done=state.get_playlist_status(playlist.id).get("done", 0),
                    message="Cancelled",
                )
                break
            video_id = item["id"]
            existing_video = crud.get_video_by_external_id(db, external_id=video_id)
            if existing_video:
                state.sync_steps_done += 1
                status = state.get_playlist_status(playlist.id)
                state.set_playlist_status(
                    playlist.id,
                    state=status.get("state", "fetching"),
                    total=status.get("total", len(videos_data)),
                    done=status.get("done", 0) + 1,
                    message="Processing videos",
                )
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
            state.sync_steps_done += 1
            status = state.get_playlist_status(playlist.id)
            state.set_playlist_status(
                playlist.id,
                state=status.get("state", "fetching"),
                total=status.get("total", len(videos_data)),
                done=status.get("done", 0) + 1,
                message="Processing videos",
            )
        playlist.last_synced_at = datetime.datetime.utcnow()
        db.commit()
        state.set_playlist_status(
            playlist.id,
            state="ready",
            total=len(videos_data),
            done=len(videos_data),
            message=f"Synced {new_count} new videos",
        )
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
        state.sync_error_message = f"Sync failed; check API key/network. Details: {exc}.{suggestion_text}"
        state.sync_message = state.sync_error_message
        state.set_playlist_status(
            playlist_id,
            state="error",
            total=state.get_playlist_status(playlist_id).get("total", 0),
            done=state.get_playlist_status(playlist_id).get("done", 0),
            message=str(exc),
        )
    finally:
        db.close()
        state.sync_steps_done += 1
        if state.active_sync_jobs > 0:
            state.active_sync_jobs -= 1
            if state.active_sync_jobs == 0:
                state.sync_in_progress = False
                state.last_sync_completed_at = datetime.datetime.utcnow()
                state.sync_message = "Sync completed."
